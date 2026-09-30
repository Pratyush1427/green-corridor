"""Emergencies, traffic-police clearance and signal commands.

Flow:
1. An ambulance crew triggers an emergency (start point + destination). The route is planned
   and a clearance request goes to the traffic control room. The ambulance sets off at once;
   it never waits for the answer.
2. Police approve the whole route, approve only some junctions ("partial"), or decline
   ("not possible"). No answer within CLEARANCE_TIMEOUT_S counts as not possible.
3. The ambulance reports its GPS position. Approved signals are held green from LEAD_S seconds
   before it arrives until RELEASE_S after it passes. Signal controllers read their command
   from signal_command().
4. The emergency ends when the ambulance arrives or the crew cancels it.

Every step is recorded in the events table for audit.

NOTE: there is no authentication yet. Before any real use, triggering must be limited to
verified ambulances and clearance decisions to traffic police accounts.
"""
import json
import math
from datetime import datetime, timezone
from typing import List, Optional

import db
import routing
from osm import distance_m

LEAD_S = 45                 # hold a signal green this many seconds before the ambulance arrives
RELEASE_S = 3               # ...and release it this long after it passes
CLEARANCE_TIMEOUT_S = 60    # unanswered requests expire (treated as "not possible")
ABANDON_AFTER_S = 120       # active emergencies with no GPS update for this long are closed

ACTIVE = "active"
CLOSED_STATUSES = ("arrived", "cancelled", "abandoned")
DECISIONS = ("approved", "partial", "declined")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _parse(ts: str) -> datetime:
    return datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)


def init() -> None:
    with db.connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS emergencies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ambulance TEXT NOT NULL,
                status TEXT NOT NULL,
                created_utc TEXT NOT NULL,
                updated_utc TEXT NOT NULL,
                route_json TEXT NOT NULL,
                lat REAL, lon REAL,
                along_m REAL NOT NULL DEFAULT 0,
                route_index INTEGER NOT NULL DEFAULT 0,
                clearance TEXT NOT NULL DEFAULT 'pending',
                clearance_utc TEXT,
                declined_json TEXT NOT NULL DEFAULT '[]',
                clearance_note TEXT
            );
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                emergency_id INTEGER NOT NULL,
                ts_utc TEXT NOT NULL,
                actor TEXT NOT NULL,
                event TEXT NOT NULL,
                detail TEXT
            );
            """
        )


def _log(conn, emergency_id: int, actor: str, event: str, detail: str = "") -> None:
    conn.execute(
        "INSERT INTO events (emergency_id, ts_utc, actor, event, detail) VALUES (?, ?, ?, ?, ?)",
        (emergency_id, _iso(_now()), actor, event, detail),
    )


def _expire_stale(conn) -> None:
    """Lazily apply timeouts: unanswered clearance requests and silent ambulances."""
    now = _now()
    for row in conn.execute("SELECT id, created_utc, updated_utc, clearance FROM emergencies WHERE status = ?", (ACTIVE,)):
        if row["clearance"] == "pending" and (now - _parse(row["created_utc"])).total_seconds() > CLEARANCE_TIMEOUT_S:
            conn.execute("UPDATE emergencies SET clearance = 'expired', clearance_utc = ? WHERE id = ?", (_iso(now), row["id"]))
            _log(conn, row["id"], "system", "clearance_expired", f"No police response within {CLEARANCE_TIMEOUT_S}s")
        if (now - _parse(row["updated_utc"])).total_seconds() > ABANDON_AFTER_S:
            conn.execute("UPDATE emergencies SET status = 'abandoned' WHERE id = ?", (row["id"],))
            _log(conn, row["id"], "system", "abandoned", f"No position update for {ABANDON_AFTER_S}s")


def _elapsed_plan_s(route: dict, along_m: float) -> float:
    """Where the ambulance is, expressed as corridor-plan seconds from the start."""
    return routing.time_at(route, along_m)


def _is_cleared(e_row, signal_id: int) -> bool:
    if e_row["clearance"] not in ("approved", "partial"):
        return False
    return signal_id not in json.loads(e_row["declined_json"])


def _held_signals(e_row, route: dict) -> List[int]:
    if e_row["status"] != ACTIVE:
        return []
    t = _elapsed_plan_s(route, e_row["along_m"])
    return [
        s["id"] for s in route["signals"]
        if _is_cleared(e_row, s["id"]) and -RELEASE_S <= s["eta_s"] - t <= LEAD_S
    ]


def _to_dict(row) -> dict:
    route = json.loads(row["route_json"])
    created = _parse(row["created_utc"])
    expires_in = None
    if row["clearance"] == "pending":
        expires_in = max(0, round(CLEARANCE_TIMEOUT_S - (_now() - created).total_seconds()))
    declined = json.loads(row["declined_json"])
    return {
        "id": row["id"],
        "ambulance": row["ambulance"],
        "status": row["status"],
        "created_utc": row["created_utc"],
        "updated_utc": row["updated_utc"],
        "hospital": route["hospital"],
        "route": route,
        "position": {"lat": row["lat"], "lon": row["lon"], "along_m": round(row["along_m"])},
        "clearance": {
            "status": row["clearance"],
            "decided_utc": row["clearance_utc"],
            "declined_signals": declined,
            "cleared_signals": [s["id"] for s in route["signals"] if _is_cleared(row, s["id"])],
            "note": row["clearance_note"],
            "expires_in_s": expires_in,
        },
        "held_signals": _held_signals(row, route),
    }


# ---------- public API ----------

def create(ambulance: str, start: List[float], hospital: Optional[List[float]], hour: int) -> dict:
    route = routing.plan_route(start[0], start[1], hour, tuple(hospital) if hospital else None)
    now = _iso(_now())
    with db.connect() as conn:
        cur = conn.execute(
            """INSERT INTO emergencies (ambulance, status, created_utc, updated_utc, route_json, lat, lon)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (ambulance, ACTIVE, now, now, json.dumps(route), route["start"][0], route["start"][1]),
        )
        eid = cur.lastrowid
        _log(conn, eid, ambulance, "triggered",
             f"To {route['hospital']['name']}, {route['distance_m']} m, {len(route['signals'])} signals")
        _log(conn, eid, "system", "clearance_requested", "Sent to traffic control room")
    return get(eid)


def get(emergency_id: int) -> Optional[dict]:
    with db.connect() as conn:
        _expire_stale(conn)
        row = conn.execute("SELECT * FROM emergencies WHERE id = ?", (emergency_id,)).fetchone()
    return _to_dict(row) if row else None


def list_all(include_closed: bool = False, limit: int = 30) -> List[dict]:
    sql = "SELECT * FROM emergencies"
    if not include_closed:
        sql += f" WHERE status = '{ACTIVE}'"
    sql += " ORDER BY id DESC LIMIT ?"
    with db.connect() as conn:
        _expire_stale(conn)
        rows = conn.execute(sql, (limit,)).fetchall()
    return [_to_dict(r) for r in rows]


def update_location(emergency_id: int, lat: float, lon: float) -> Optional[dict]:
    """Project a GPS fix onto the planned route to find how far along the ambulance is."""
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM emergencies WHERE id = ?", (emergency_id,)).fetchone()
        if not row:
            return None
        if row["status"] != ACTIVE:
            return _to_dict(row)
        route = json.loads(row["route_json"])
        coords, along = route["coords"], route["along"]
        # Search a little behind the last known point and forward, so routes that loop back
        # near themselves don't make the ambulance jump.
        lo = max(0, row["route_index"] - 5)
        best_k, best_d = lo, math.inf
        for k in range(lo, len(coords)):
            d = distance_m(lat, lon, *coords[k])
            if d < best_d:
                best_k, best_d = k, d
        conn.execute(
            "UPDATE emergencies SET lat = ?, lon = ?, along_m = ?, route_index = ?, updated_utc = ? WHERE id = ?",
            (lat, lon, max(row["along_m"], along[best_k]), best_k, _iso(_now()), emergency_id),
        )
    return get(emergency_id)


def decide(emergency_id: int, decision: str, declined_signals: List[int], officer: str,
           note: Optional[str]) -> Optional[dict]:
    if decision not in DECISIONS:
        raise ValueError(f"decision must be one of {DECISIONS}")
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM emergencies WHERE id = ?", (emergency_id,)).fetchone()
        if not row:
            return None
        if row["status"] != ACTIVE:
            raise ValueError("This emergency has already ended.")
        route = json.loads(row["route_json"])
        route_ids = {s["id"] for s in route["signals"]}
        if decision == "declined":
            declined = sorted(route_ids)
        elif decision == "approved":
            declined = []
        else:
            declined = sorted(set(declined_signals) & route_ids)
            if not declined:
                decision = "approved"
            elif len(declined) == len(route_ids):
                decision = "declined"
        conn.execute(
            "UPDATE emergencies SET clearance = ?, clearance_utc = ?, declined_json = ?, clearance_note = ? WHERE id = ?",
            (decision, _iso(_now()), json.dumps(declined), note, emergency_id),
        )
        detail = f"{len(route_ids) - len(declined)}/{len(route_ids)} junctions cleared"
        _log(conn, emergency_id, officer or "traffic police", f"clearance_{decision}",
             detail + (f". Note: {note}" if note else ""))
    return get(emergency_id)


def close(emergency_id: int, status: str, actor: str) -> Optional[dict]:
    if status not in ("arrived", "cancelled"):
        raise ValueError("status must be 'arrived' or 'cancelled'")
    with db.connect() as conn:
        row = conn.execute("SELECT status FROM emergencies WHERE id = ?", (emergency_id,)).fetchone()
        if not row:
            return None
        if row["status"] == ACTIVE:
            conn.execute("UPDATE emergencies SET status = ?, updated_utc = ? WHERE id = ?",
                         (status, _iso(_now()), emergency_id))
            _log(conn, emergency_id, actor, status)
    return get(emergency_id)


def events(emergency_id: int) -> List[dict]:
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT ts_utc, actor, event, detail FROM events WHERE emergency_id = ? ORDER BY id", (emergency_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def signal_holds() -> List[dict]:
    """Every signal currently held green, and for which emergency."""
    holds = []
    for e in list_all():
        for sid in e["held_signals"]:
            holds.append({"signal_id": sid, "emergency_id": e["id"], "ambulance": e["ambulance"]})
    return holds


def signal_command(signal_id: int) -> dict:
    """What a real signal controller at this junction should do right now."""
    for h in signal_holds():
        if h["signal_id"] == signal_id:
            return {"signal_id": signal_id, "command": "hold_green", "emergency_id": h["emergency_id"],
                    "ambulance": h["ambulance"]}
    return {"signal_id": signal_id, "command": "normal"}
