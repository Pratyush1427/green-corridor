"""Ambulance fleet, incidents, traffic-police clearance, signal commands and the simulation.

An incident has two legs, each with its own route and its own green corridor:

    to_scene     ambulance -> accident scene
    at_scene     patient being loaded (the crew taps "Patient on board", or it happens automatically)
    to_hospital  scene -> hospital (a chosen one, or the one reachable fastest)
    at_hospital  handover, then the ambulance is available again

Clearance, per leg:
- The traffic control room approves the whole leg, approves it except some junctions ("partial"),
  or declines it ("not possible"). No answer within CLEARANCE_TIMEOUT_S counts as not possible.
- The constable at a junction can answer for that junction alone: "clearing" or "can't". A junction
  answer overrides the control room for that junction.
- A cleared signal is held green from LEAD_S before the ambulance reaches it until RELEASE_S after.

Simulation: ambulances flagged `simulated` are moved along their route by a background loop, as if
they were sending GPS. A real ambulance app would instead call update_location().

NOTE: there is no authentication yet. Before any real use, only verified ambulances may trigger
incidents and only traffic police accounts may answer clearance requests.
"""
import bisect
import json
import threading
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional

import db
import routing
from osm import distance_m

LEAD_S = 45                 # hold a cleared signal green this long before the ambulance arrives
RELEASE_S = 3               # ...and release it this long after it passes
ALERT_S = 150               # junction screens start alerting this long before arrival
CLEARANCE_TIMEOUT_S = 60    # real seconds; unanswered control-room requests expire
SCENE_TIME_S = 120          # simulated seconds at the scene before the patient is loaded automatically
HANDOVER_TIME_S = 90        # simulated seconds at the hospital before the ambulance is free again
TICK_S = 0.25               # simulation step (real seconds)
FLEET_SIZE = 8

CORRIDOR_ON = ("approved", "partial")
DECISIONS = ("approved", "partial", "declined")
PHASES = ("to_scene", "at_scene", "to_hospital", "at_hospital", "done")

sim = {"speed": 10.0}       # simulated seconds per real second
_routes: Dict[int, dict] = {}  # leg id -> parsed route (routes never change once planned)
_lock = threading.Lock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _age_s(ts: str) -> float:
    dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - dt).total_seconds()


# ---------- schema ----------

def init() -> None:
    with db.connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS ambulances (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                callsign TEXT NOT NULL,
                base_name TEXT,
                lat REAL NOT NULL, lon REAL NOT NULL,
                status TEXT NOT NULL DEFAULT 'available',   -- available | on_incident
                incident_id INTEGER,
                simulated INTEGER NOT NULL DEFAULT 1,
                updated_utc TEXT
            );
            CREATE TABLE IF NOT EXISTS incidents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_utc TEXT NOT NULL,
                status TEXT NOT NULL,                       -- active | closed | cancelled
                phase TEXT NOT NULL,                        -- see PHASES
                ambulance_id INTEGER NOT NULL,
                scene_lat REAL NOT NULL, scene_lon REAL NOT NULL,
                description TEXT,
                hospital_json TEXT,                         -- [lat, lon] chosen by the organisation, or null
                hour INTEGER,
                dwell_s REAL NOT NULL DEFAULT 0,            -- simulated seconds left at scene / hospital
                demo_json TEXT                              -- scripted police answers for the demo
            );
            CREATE TABLE IF NOT EXISTS legs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                incident_id INTEGER NOT NULL,
                kind TEXT NOT NULL,                         -- to_scene | to_hospital
                created_utc TEXT NOT NULL,
                route_json TEXT NOT NULL,
                along_m REAL NOT NULL DEFAULT 0,
                elapsed_s REAL NOT NULL DEFAULT 0,          -- simulated seconds driven so far
                wait_s REAL NOT NULL DEFAULT 0,             -- seconds left stopped at a red signal
                waited_json TEXT NOT NULL DEFAULT '[]',     -- signals it had to stop at
                done INTEGER NOT NULL DEFAULT 0,
                clearance TEXT NOT NULL DEFAULT 'pending',
                clearance_utc TEXT,
                clearance_by TEXT,
                clearance_note TEXT,
                declined_json TEXT NOT NULL DEFAULT '[]'
            );
            CREATE TABLE IF NOT EXISTS junction_answers (
                leg_id INTEGER NOT NULL,
                signal_id INTEGER NOT NULL,
                answer TEXT NOT NULL,                       -- clearing | cant
                reason TEXT,
                officer TEXT,
                ts_utc TEXT NOT NULL,
                PRIMARY KEY (leg_id, signal_id)
            );
            CREATE TABLE IF NOT EXISTS incident_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                incident_id INTEGER NOT NULL,
                ts_utc TEXT NOT NULL,
                actor TEXT NOT NULL,
                event TEXT NOT NULL,
                detail TEXT
            );
            """
        )
        cols = {r[1] for r in conn.execute("PRAGMA table_info(ambulances)")}
        if "base_lat" not in cols:  # older databases: remember where each ambulance is based
            conn.execute("ALTER TABLE ambulances ADD COLUMN base_lat REAL")
            conn.execute("ALTER TABLE ambulances ADD COLUMN base_lon REAL")
            hospitals = {h["name"]: h for h in routing.graph().er_hospitals}
            for a in conn.execute("SELECT id, base_name, lat, lon FROM ambulances").fetchall():
                h = hospitals.get(a["base_name"])
                conn.execute("UPDATE ambulances SET base_lat = ?, base_lon = ? WHERE id = ?",
                             (h["lat"] if h else a["lat"], h["lon"] if h else a["lon"], a["id"]))
        # Anything left running when the server stopped is closed on restart.
        conn.execute("UPDATE incidents SET status = 'cancelled', phase = 'done' WHERE status = 'active'")
        conn.execute("UPDATE ambulances SET status = 'available', incident_id = NULL")
        if conn.execute("SELECT COUNT(*) FROM ambulances").fetchone()[0] == 0:
            _seed_fleet(conn)


def _seed_fleet(conn) -> None:
    """Park a demo fleet at emergency hospitals spread across the city."""
    center = (12.9716, 77.5946)  # keep the fleet within the inner city
    hospitals = [h for h in routing.graph().general_hospitals if distance_m(h["lat"], h["lon"], *center) < 9000]
    if not hospitals:
        return
    chosen = [min(hospitals, key=lambda h: distance_m(h["lat"], h["lon"], *center))]
    while len(chosen) < min(FLEET_SIZE, len(hospitals)):  # farthest-point spread
        chosen.append(max(hospitals, key=lambda h: min(distance_m(h["lat"], h["lon"], c["lat"], c["lon"]) for c in chosen)))
    for i, h in enumerate(chosen, 1):
        conn.execute("INSERT INTO ambulances (callsign, base_name, lat, lon, base_lat, base_lon, updated_utc) VALUES (?, ?, ?, ?, ?, ?, ?)",
                     (f"AMB-{i:02d}", h["name"], h["lat"], h["lon"], h["lat"], h["lon"], _now_iso()))


def _log(conn, incident_id: int, actor: str, event: str, detail: str = "") -> None:
    conn.execute("INSERT INTO incident_events (incident_id, ts_utc, actor, event, detail) VALUES (?, ?, ?, ?, ?)",
                 (incident_id, _now_iso(), actor, event, detail))


# ---------- route helpers ----------

def _route(conn, leg_id: int) -> dict:
    if leg_id not in _routes:
        row = conn.execute("SELECT route_json FROM legs WHERE id = ?", (leg_id,)).fetchone()
        _routes[leg_id] = json.loads(row["route_json"])
    return _routes[leg_id]


def _seg(along: List[float], d: float) -> int:
    return max(0, min(len(along) - 2, bisect.bisect_right(along, d) - 1))


def _interp(values: List[float], along: List[float], d: float) -> float:
    k = _seg(along, d)
    span = along[k + 1] - along[k]
    f = 0.0 if span <= 0 else min(1.0, max(0.0, (d - along[k]) / span))
    return values[k] + f * (values[k + 1] - values[k])


def _point(route: dict, d: float) -> List[float]:
    k = _seg(route["along"], d)
    a, b = route["coords"][k], route["coords"][k + 1]
    span = route["along"][k + 1] - route["along"][k]
    f = 0.0 if span <= 0 else min(1.0, max(0.0, (d - route["along"][k]) / span))
    return [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f]


def _answers(conn, leg_id: int) -> Dict[int, dict]:
    rows = conn.execute("SELECT * FROM junction_answers WHERE leg_id = ?", (leg_id,)).fetchall()
    return {r["signal_id"]: dict(r) for r in rows}


def _cleared(leg, answers: Dict[int, dict], signal_id: int) -> bool:
    """Is this junction cleared for the ambulance? A junction's own answer wins."""
    if signal_id in answers:
        return answers[signal_id]["answer"] == "clearing"
    return leg["clearance"] in CORRIDOR_ON and signal_id not in json.loads(leg["declined_json"])


def _signal_state(leg, answers, sig, route) -> str:
    """passed | held | cleared | cant | not_cleared | pending"""
    if sig["along_m"] <= leg["along_m"]:
        return "passed"
    if _cleared(leg, answers, sig["id"]):
        until = sig["eta_s"] - _interp(route["times"], route["along"], leg["along_m"])
        return "held" if -RELEASE_S <= until <= LEAD_S else "cleared"
    if answers.get(sig["id"], {}).get("answer") == "cant":
        return "cant"
    return "pending" if leg["clearance"] == "pending" else "not_cleared"


def _remaining_s(leg, answers, route) -> float:
    """Rough time left: corridor pace while cleared, otherwise normal traffic plus red-light waits."""
    fast = leg["clearance"] in CORRIDOR_ON
    times = route["times"] if fast else route["times_normal"]
    ahead = [s for s in route["signals"] if s["along_m"] > leg["along_m"]]
    stops = sum(1 for s in ahead if not _cleared(leg, answers, s["id"]))
    return max(0.0, times[-1] - _interp(times, route["along"], leg["along_m"])) + stops * route["red_wait_s"] + leg["wait_s"]


def _eta_to(leg, route, along_m: float) -> float:
    """Planned seconds until the ambulance reaches a point on its route."""
    now = _interp(route["times"], route["along"], leg["along_m"])
    return _interp(route["times"], route["along"], along_m) - now + leg["wait_s"]


# ---------- views ----------

def _leg_view(conn, leg, full: bool = False) -> dict:
    route = _route(conn, leg["id"])
    answers = _answers(conn, leg["id"])
    signals = []
    for s in route["signals"]:
        state = _signal_state(leg, answers, s, route)
        a = answers.get(s["id"])
        signals.append({
            "id": s["id"], "lat": s["lat"], "lon": s["lon"], "name": s.get("name"),
            "along_m": s["along_m"], "from_road": s.get("from_road"), "to_road": s.get("to_road"),
            "turn": s.get("turn"), "state": state,
            "eta_s": None if state == "passed" else round(_eta_to(leg, route, s["along_m"])),
            "answer": a["answer"] if a else None, "reason": a["reason"] if a else None,
            "answered_by": a["officer"] if a else None,
        })
    total = route["along"][-1]
    turns_ahead = [t for t in route.get("turns", []) if t["along_m"] > leg["along_m"]]
    view = {
        "id": leg["id"], "kind": leg["kind"], "done": bool(leg["done"]), "created_utc": leg["created_utc"],
        "destination": route["destination"],
        "distance_m": route["distance_m"], "left_m": round(max(0.0, total - leg["along_m"])),
        "along_m": round(leg["along_m"]), "progress": round(min(1.0, leg["along_m"] / (total or 1)), 3),
        "eta_s": round(_remaining_s(leg, answers, route)), "elapsed_s": round(leg["elapsed_s"]),
        "stopped": leg["wait_s"] > 0,
        "plan": {"corridor_s": route["eta_s"], "normal_s": route["normal"]["eta_s"], "saved_s": route["saved_s"],
                 "hour": route["hour"]},
        "clearance": {
            "status": leg["clearance"], "by": leg["clearance_by"], "note": leg["clearance_note"],
            "decided_utc": leg["clearance_utc"],
            "expires_in_s": max(0, round(CLEARANCE_TIMEOUT_S - _age_s(leg["created_utc"]))) if leg["clearance"] == "pending" else None,
            "cleared": sum(1 for s in signals if s["state"] in ("held", "cleared") or (s["state"] == "passed" and _cleared(leg, answers, s["id"]))),
            "total": len(signals),
        },
        "signals": signals,
        "next_turn": ({**turns_ahead[0], "in_m": round(turns_ahead[0]["along_m"] - leg["along_m"])} if turns_ahead else None),
    }
    if full:
        view["route"] = {"coords": route["coords"], "normal_coords": route["normal"]["coords"], "start": route["start"]}
    return view


def _incident_view(conn, inc, full: bool = False) -> dict:
    amb = conn.execute("SELECT * FROM ambulances WHERE id = ?", (inc["ambulance_id"],)).fetchone()
    legs = conn.execute("SELECT * FROM legs WHERE incident_id = ? ORDER BY id", (inc["id"],)).fetchall()
    leg_views = [_leg_view(conn, l, full) for l in legs]
    current = next((l for l in leg_views if not l["done"]), leg_views[-1] if leg_views else None)
    return {
        "id": inc["id"], "status": inc["status"], "phase": inc["phase"], "created_utc": inc["created_utc"],
        "description": inc["description"],
        "scene": {"lat": inc["scene_lat"], "lon": inc["scene_lon"]},
        "ambulance": {"id": amb["id"], "callsign": amb["callsign"], "lat": amb["lat"], "lon": amb["lon"]} if amb else None,
        "dwell_s": round(inc["dwell_s"]),
        "hospital_choice": json.loads(inc["hospital_json"]) if inc["hospital_json"] else None,
        "legs": leg_views,
        "current_leg": current,
    }


def _ambulance_view(amb) -> dict:
    return {"id": amb["id"], "callsign": amb["callsign"], "base": amb["base_name"], "lat": amb["lat"],
            "lon": amb["lon"], "status": amb["status"], "incident_id": amb["incident_id"],
            "simulated": bool(amb["simulated"])}


def state(include_closed: int = 10) -> dict:
    """Everything a screen needs, without full route geometry (fetch get_incident(full) for that)."""
    with db.connect() as conn:
        _expire(conn)
        fleet = [_ambulance_view(a) for a in conn.execute("SELECT * FROM ambulances ORDER BY id")]
        active = conn.execute("SELECT * FROM incidents WHERE status = 'active' ORDER BY id DESC").fetchall()
        recent = conn.execute("SELECT * FROM incidents WHERE status != 'active' ORDER BY id DESC LIMIT ?",
                              (include_closed,)).fetchall()
        incidents = [_incident_view(conn, i) for i in list(active) + list(recent)]
    holds = [{"signal_id": s["id"], "incident_id": i["id"], "leg_id": l["id"], "ambulance": i["ambulance"]["callsign"]}
             for i in incidents if i["status"] == "active" for l in i["legs"] if not l["done"]
             for s in l["signals"] if s["state"] == "held"]
    return {"sim": dict(sim), "fleet": fleet, "incidents": incidents, "holds": holds}


def get_incident(incident_id: int, full: bool = True) -> Optional[dict]:
    with db.connect() as conn:
        inc = conn.execute("SELECT * FROM incidents WHERE id = ?", (incident_id,)).fetchone()
        return _incident_view(conn, inc, full) if inc else None


def events(incident_id: int) -> List[dict]:
    with db.connect() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT ts_utc, actor, event, detail FROM incident_events WHERE incident_id = ? ORDER BY id", (incident_id,))]


def junction_view(signal_id: int) -> dict:
    """Ambulances heading for one junction, for the constable standing there."""
    sig = next((s for s in routing.graph().signals if s["id"] == signal_id), None)
    if sig is None:
        raise KeyError("Unknown signal")
    coming = []
    with db.connect() as conn:
        _expire(conn)
        rows = conn.execute(
            """SELECT l.*, i.id AS inc_id, a.callsign FROM legs l JOIN incidents i ON i.id = l.incident_id
               JOIN ambulances a ON a.id = i.ambulance_id WHERE i.status = 'active' AND l.done = 0""").fetchall()
        for leg in rows:
            view = _leg_view(conn, leg)
            for s in view["signals"]:
                if s["id"] == signal_id and s["state"] != "passed":
                    coming.append({"incident_id": leg["inc_id"], "leg_id": leg["id"], "ambulance": leg["callsign"],
                                   "kind": leg["kind"], "destination": view["destination"]["name"],
                                   "clearance": view["clearance"]["status"], "alert": s["eta_s"] <= ALERT_S, **s})
    coming.sort(key=lambda c: c["eta_s"])
    return {"signal": {**sig, "roads": _roads_at(sig)}, "coming": coming, "alert_s": ALERT_S}


def _roads_at(sig: dict) -> List[str]:
    """Names of the roads meeting at a signal, so officers recognise their junction."""
    g = routing.graph()
    vertex, _ = g.snap(sig["lat"], sig["lon"])
    names = []
    for e in g.edges:
        if e[0] == vertex or e[1] == vertex:
            name = g.names[e[6]] if len(e) > 6 and e[6] >= 0 else None
            if name and name not in names:
                names.append(name)
    return names[:3]


def upcoming_junctions(limit: int = 40) -> List[dict]:
    """Junctions that active ambulances will pass, soonest first (to pick one on the junction screen)."""
    out = {}
    for inc in state(0)["incidents"]:
        for leg in inc["legs"]:
            if leg["done"]:
                continue
            for s in leg["signals"]:
                if s["state"] != "passed" and (s["id"] not in out or s["eta_s"] < out[s["id"]]["eta_s"]):
                    out[s["id"]] = {"id": s["id"], "name": s["name"], "from_road": s["from_road"],
                                    "to_road": s["to_road"], "eta_s": s["eta_s"], "ambulance": inc["ambulance"]["callsign"],
                                    "lat": s["lat"], "lon": s["lon"]}
    return sorted(out.values(), key=lambda s: s["eta_s"])[:limit]


# ---------- actions ----------

def _plan_leg(conn, incident_id: int, kind: str, start: List[float], hour: int,
              destination=None, hospital=None) -> int:
    route = routing.plan_route(start[0], start[1], hour, hospital=hospital,
                               destination=destination, destination_name="Accident scene")
    cur = conn.execute("INSERT INTO legs (incident_id, kind, created_utc, route_json) VALUES (?, ?, ?, ?)",
                       (incident_id, kind, _now_iso(), json.dumps(route)))
    _routes[cur.lastrowid] = route
    _log(conn, incident_id, "system", f"{kind}_planned",
         f"To {route['destination']['name']}: {route['distance_m']} m, {len(route['signals'])} signals. "
         "Clearance request sent to traffic control room")
    return cur.lastrowid


def _choose_ambulance(conn, scene: List[float], hour: int, ambulance_id: Optional[int] = None):
    """The given ambulance, or the free one that can reach the scene fastest. Returns (row, route)."""
    if ambulance_id is not None:
        amb = conn.execute("SELECT * FROM ambulances WHERE id = ?", (ambulance_id,)).fetchone()
        if amb is None or amb["status"] != "available":
            raise routing.RouteError("That ambulance is busy. Choose another one.")
        return amb, routing.plan_route(amb["lat"], amb["lon"], hour, destination=tuple(scene))
    free = conn.execute("SELECT * FROM ambulances WHERE status = 'available'").fetchall()
    if not free:
        raise routing.RouteError("All ambulances are busy right now.")
    best = None
    for amb in free:
        try:
            r = routing.plan_route(amb["lat"], amb["lon"], hour, destination=tuple(scene))
        except routing.RouteError:
            continue
        if best is None or r["eta_s"] < best[1]["eta_s"]:
            best = (amb, r)
    if best is None:
        raise routing.RouteError("No ambulance can reach that spot. Try a place on or near a main road.")
    return best


def preview_incident(scene: List[float], hour: int, ambulance_id: Optional[int] = None) -> dict:
    """What would happen if this accident were reported now: which ambulance, how far, how long.
    Nothing is created, so the organisation can check before sending."""
    with db.connect() as conn:
        amb, route = _choose_ambulance(conn, scene, hour, ambulance_id)
        free = conn.execute("SELECT id, callsign FROM ambulances WHERE status = 'available' ORDER BY id").fetchall()
    return {
        "ambulance": {"id": amb["id"], "callsign": amb["callsign"], "base": amb["base_name"]},
        "eta_s": route["eta_s"], "normal_eta_s": route["normal"]["eta_s"], "distance_m": route["distance_m"],
        "signals": len(route["signals"]), "free": [dict(a) for a in free],
    }


def create_incident(scene: List[float], hour: int, ambulance_id: Optional[int] = None,
                    hospital: Optional[List[float]] = None, description: Optional[str] = None,
                    demo: Optional[dict] = None) -> dict:
    """Report an accident and dispatch an ambulance (the one that can get there fastest, if not given)."""
    with _lock, db.connect() as conn:
        amb, _ = _choose_ambulance(conn, scene, hour, ambulance_id)
        cur = conn.execute(
            """INSERT INTO incidents (created_utc, status, phase, ambulance_id, scene_lat, scene_lon, description,
               hospital_json, hour, demo_json) VALUES (?, 'active', 'to_scene', ?, ?, ?, ?, ?, ?, ?)""",
            (_now_iso(), amb["id"], scene[0], scene[1], description,
             json.dumps(hospital) if hospital else None, hour, json.dumps(demo) if demo else None))
        iid = cur.lastrowid
        _log(conn, iid, "organisation", "reported", description or "Accident reported")
        _log(conn, iid, "organisation", "dispatched", f"{amb['callsign']} sent from {amb['base_name'] or 'its position'}")
        _plan_leg(conn, iid, "to_scene", [amb["lat"], amb["lon"]], hour, destination=tuple(scene))
        conn.execute("UPDATE ambulances SET status = 'on_incident', incident_id = ?, updated_utc = ? WHERE id = ?",
                     (iid, _now_iso(), amb["id"]))
    return get_incident(iid)


def add_ambulance(lat: float, lon: float, callsign: Optional[str] = None) -> dict:
    with db.connect() as conn:
        n = conn.execute("SELECT COUNT(*) FROM ambulances").fetchone()[0] + 1
        cur = conn.execute("INSERT INTO ambulances (callsign, base_name, lat, lon, base_lat, base_lon, updated_utc) VALUES (?, ?, ?, ?, ?, ?, ?)",
                           (callsign or f"AMB-{n:02d}", "Added on the map", lat, lon, lat, lon, _now_iso()))
        return _ambulance_view(conn.execute("SELECT * FROM ambulances WHERE id = ?", (cur.lastrowid,)).fetchone())


def patient_on_board(incident_id: int, actor: str = "ambulance crew") -> dict:
    """At the scene: plan the hospital leg (chosen hospital, or the fastest emergency hospital)."""
    with _lock, db.connect() as conn:
        inc = conn.execute("SELECT * FROM incidents WHERE id = ?", (incident_id,)).fetchone()
        if inc is None:
            raise KeyError("Unknown incident")
        if inc["status"] != "active" or inc["phase"] not in ("to_scene", "at_scene"):
            raise ValueError("The patient can only be loaded at the scene.")
        _start_hospital_leg(conn, inc, actor)
    return get_incident(incident_id)


def _start_hospital_leg(conn, inc, actor: str) -> None:
    amb = conn.execute("SELECT * FROM ambulances WHERE id = ?", (inc["ambulance_id"],)).fetchone()
    conn.execute("UPDATE legs SET done = 1 WHERE incident_id = ? AND kind = 'to_scene'", (inc["id"],))
    hospital = tuple(json.loads(inc["hospital_json"])) if inc["hospital_json"] else None
    _log(conn, inc["id"], actor, "patient_on_board")
    _plan_leg(conn, inc["id"], "to_hospital", [amb["lat"], amb["lon"]], inc["hour"], hospital=hospital)
    conn.execute("UPDATE incidents SET phase = 'to_hospital', dwell_s = 0 WHERE id = ?", (inc["id"],))


def set_hospital(incident_id: int, hospital: Optional[List[float]], actor: str = "organisation") -> dict:
    """Choose the destination hospital (None = fastest) before the patient is on board."""
    with _lock, db.connect() as conn:
        inc = conn.execute("SELECT * FROM incidents WHERE id = ?", (incident_id,)).fetchone()
        if inc is None:
            raise KeyError("Unknown incident")
        if inc["status"] != "active" or inc["phase"] not in ("to_scene", "at_scene"):
            raise ValueError("The hospital can only be changed before the patient is on board.")
        conn.execute("UPDATE incidents SET hospital_json = ? WHERE id = ?",
                     (json.dumps(hospital) if hospital else None, incident_id))
        name = "fastest emergency hospital"
        if hospital:
            name = next((h["name"] for h in routing.graph().er_hospitals
                         if (h["lat"], h["lon"]) == tuple(hospital)), "chosen hospital")
        _log(conn, incident_id, actor, "hospital_set", name)
    return get_incident(incident_id)


def handover(incident_id: int, actor: str = "ambulance crew") -> dict:
    with _lock, db.connect() as conn:
        inc = conn.execute("SELECT * FROM incidents WHERE id = ?", (incident_id,)).fetchone()
        if inc is None:
            raise KeyError("Unknown incident")
        if inc["phase"] != "at_hospital":
            raise ValueError("Handover happens at the hospital.")
        _finish(conn, inc, "closed", actor, "handover", "Patient handed over; ambulance available")
    return get_incident(incident_id)


def cancel(incident_id: int, actor: str = "organisation") -> dict:
    with _lock, db.connect() as conn:
        inc = conn.execute("SELECT * FROM incidents WHERE id = ?", (incident_id,)).fetchone()
        if inc is None:
            raise KeyError("Unknown incident")
        if inc["status"] == "active":
            _finish(conn, inc, "cancelled", actor, "cancelled")
    return get_incident(incident_id)


def _finish(conn, inc, status: str, actor: str, event: str, detail: str = "") -> None:
    conn.execute("UPDATE incidents SET status = ?, phase = 'done' WHERE id = ?", (status, inc["id"]))
    conn.execute("UPDATE legs SET done = 1 WHERE incident_id = ?", (inc["id"],))
    conn.execute("UPDATE ambulances SET status = 'available', incident_id = NULL, updated_utc = ? WHERE id = ?",
                 (_now_iso(), inc["ambulance_id"]))
    _log(conn, inc["id"], actor, event, detail)


def decide(leg_id: int, decision: str, declined_signals: List[int], officer: str, note: Optional[str]) -> dict:
    """Traffic control room decision for one leg."""
    if decision not in DECISIONS:
        raise ValueError(f"decision must be one of {DECISIONS}")
    with _lock, db.connect() as conn:
        leg = conn.execute("SELECT * FROM legs WHERE id = ?", (leg_id,)).fetchone()
        if leg is None:
            raise KeyError("Unknown leg")
        inc = conn.execute("SELECT * FROM incidents WHERE id = ?", (leg["incident_id"],)).fetchone()
        if inc["status"] != "active" or leg["done"]:
            raise ValueError("This trip has already ended.")
        ids = {s["id"] for s in _route(conn, leg_id)["signals"]}
        declined = sorted(ids) if decision == "declined" else [] if decision == "approved" else sorted(set(declined_signals) & ids)
        if decision == "partial" and not declined:
            decision = "approved"
        conn.execute("UPDATE legs SET clearance = ?, clearance_utc = ?, clearance_by = ?, clearance_note = ?, declined_json = ? WHERE id = ?",
                     (decision, _now_iso(), officer, note, json.dumps(declined), leg_id))
        _log(conn, inc["id"], officer or "traffic control room", f"clearance_{decision}",
             f"{leg['kind'].replace('_', ' ')}: {len(ids) - len(declined)}/{len(ids)} junctions" + (f". {note}" if note else ""))
    return get_incident(inc["id"])


def junction_answer(leg_id: int, signal_id: int, answer: str, officer: str, reason: Optional[str]) -> dict:
    """The constable at one junction: 'clearing' or 'cant'."""
    if answer not in ("clearing", "cant"):
        raise ValueError("answer must be 'clearing' or 'cant'")
    with _lock, db.connect() as conn:
        leg = conn.execute("SELECT * FROM legs WHERE id = ?", (leg_id,)).fetchone()
        if leg is None or signal_id not in {s["id"] for s in _route(conn, leg_id)["signals"]}:
            raise KeyError("That junction isn't on this ambulance's route")
        if leg["done"]:
            raise ValueError("This trip has already ended.")
        conn.execute("INSERT OR REPLACE INTO junction_answers VALUES (?, ?, ?, ?, ?, ?)",
                     (leg_id, signal_id, answer, reason, officer, _now_iso()))
        sig = next(s for s in _route(conn, leg_id)["signals"] if s["id"] == signal_id)
        where = sig.get("name") or " / ".join(n for n in (sig.get("from_road"), sig.get("to_road")) if n) or f"signal {signal_id}"
        _log(conn, leg["incident_id"], officer or "junction officer", f"junction_{answer}",
             where + (f": {reason}" if reason else ""))
    return junction_view(signal_id)


def update_location(ambulance_id: int, lat: float, lon: float) -> dict:
    """GPS from a real ambulance app: stops simulating it and moves it along its route."""
    with _lock, db.connect() as conn:
        amb = conn.execute("SELECT * FROM ambulances WHERE id = ?", (ambulance_id,)).fetchone()
        if amb is None:
            raise KeyError("Unknown ambulance")
        conn.execute("UPDATE ambulances SET lat = ?, lon = ?, simulated = 0, updated_utc = ? WHERE id = ?",
                     (lat, lon, _now_iso(), ambulance_id))
        if amb["incident_id"]:
            leg = conn.execute("SELECT * FROM legs WHERE incident_id = ? AND done = 0 ORDER BY id DESC LIMIT 1",
                               (amb["incident_id"],)).fetchone()
            if leg:
                route = _route(conn, leg["id"])
                k = min(range(len(route["coords"])), key=lambda i: distance_m(lat, lon, *route["coords"][i]))
                conn.execute("UPDATE legs SET along_m = MAX(along_m, ?) WHERE id = ?", (route["along"][k], leg["id"]))
        return _ambulance_view(conn.execute("SELECT * FROM ambulances WHERE id = ?", (ambulance_id,)).fetchone())


def reset_fleet() -> dict:
    """Cancel every active incident and send each ambulance back to its base (for repeatable demos)."""
    with _lock, db.connect() as conn:
        for inc in conn.execute("SELECT * FROM incidents WHERE status = 'active'").fetchall():
            _finish(conn, inc, "cancelled", "demo reset", "cancelled", "Fleet reset")
        conn.execute("""UPDATE ambulances SET lat = COALESCE(base_lat, lat), lon = COALESCE(base_lon, lon),
                        status = 'available', incident_id = NULL, simulated = 1, updated_utc = ?""", (_now_iso(),))
    return state(0)


def set_speed(speed: float) -> dict:
    sim["speed"] = max(0.0, min(60.0, speed))
    return dict(sim)


# ---------- timeouts & simulation ----------

def _expire(conn) -> None:
    for leg in conn.execute("SELECT id, incident_id, kind, created_utc FROM legs WHERE clearance = 'pending' AND done = 0").fetchall():
        if _age_s(leg["created_utc"]) > CLEARANCE_TIMEOUT_S:
            conn.execute("UPDATE legs SET clearance = 'expired', clearance_utc = ? WHERE id = ?", (_now_iso(), leg["id"]))
            _log(conn, leg["incident_id"], "system", "clearance_expired",
                 f"{leg['kind'].replace('_', ' ')}: no control-room answer within {CLEARANCE_TIMEOUT_S}s")


def _advance(leg: dict, route: dict, answers: Dict[int, dict], dt: float) -> bool:
    """Move a simulated ambulance dt seconds along its leg. Corridor pace while the next signal is
    cleared, normal traffic otherwise, with a red-light stop at each uncleared signal."""
    along, total = route["along"], route["along"][-1]
    waited = set(leg["waited"])
    for _ in range(1000):
        if dt <= 1e-6 or leg["along_m"] >= total:
            break
        if leg["wait_s"] > 0:
            w = min(leg["wait_s"], dt)
            leg["wait_s"] -= w; dt -= w; leg["elapsed_s"] += w
            continue
        d = leg["along_m"]
        k = _seg(along, d)
        nxt = next((s for s in route["signals"] if s["along_m"] > d), None)
        fast = _cleared(leg, answers, nxt["id"]) if nxt else leg["clearance"] in CORRIDOR_ON
        times = route["times"] if fast else route["times_normal"]
        seg_t, seg_l = times[k + 1] - times[k], along[k + 1] - along[k]
        v = seg_l / seg_t if seg_t > 0 else 50.0
        target = along[k + 1]
        stop = nxt is not None and nxt["along_m"] <= target and not _cleared(leg, answers, nxt["id"]) and nxt["id"] not in waited
        if stop:
            target = nxt["along_m"]
        need = (target - d) / v
        if need <= dt:
            leg["along_m"] = target; dt -= need; leg["elapsed_s"] += need
            if stop:
                waited.add(nxt["id"]); leg["wait_s"] = route["red_wait_s"]; leg["along_m"] += 0.01
        else:
            leg["along_m"] = d + v * dt; leg["elapsed_s"] += dt; dt = 0
    leg["waited"] = sorted(waited)
    return leg["along_m"] >= total


def _demo_police(conn, inc, leg) -> None:
    """Scripted control-room answers for the one-click demo."""
    script = json.loads(inc["demo_json"] or "{}").get(leg["kind"])
    if not script or leg["clearance"] != "pending" or _age_s(leg["created_utc"]) < script.get("after_s", 3):
        return
    ids = [s["id"] for s in _route(conn, leg["id"])["signals"]]
    decision, declined = script["decision"], []
    if decision == "partial":
        declined = ids[1:2]
        decision = "partial" if declined else "approved"
    elif decision == "declined":
        declined = ids
    conn.execute("UPDATE legs SET clearance = ?, clearance_utc = ?, clearance_by = ?, clearance_note = ?, declined_json = ? WHERE id = ?",
                 (decision, _now_iso(), "Demo control room", script.get("note"), json.dumps(declined), leg["id"]))
    _log(conn, inc["id"], "Demo control room", f"clearance_{decision}",
         f"{leg['kind'].replace('_', ' ')}: {len(ids) - len(declined)}/{len(ids)} junctions" + (f". {script['note']}" if script.get("note") else ""))


def tick(dt_real: float) -> None:
    dt = dt_real * sim["speed"]
    with _lock, db.connect() as conn:
        _expire(conn)
        for inc in conn.execute("SELECT * FROM incidents WHERE status = 'active'").fetchall():
            amb = conn.execute("SELECT * FROM ambulances WHERE id = ?", (inc["ambulance_id"],)).fetchone()
            if inc["phase"] in ("at_scene", "at_hospital"):
                if not amb["simulated"] or dt == 0:
                    continue
                left = inc["dwell_s"] - dt
                if left > 0:
                    conn.execute("UPDATE incidents SET dwell_s = ? WHERE id = ?", (left, inc["id"]))
                elif inc["phase"] == "at_scene":
                    _start_hospital_leg(conn, inc, "ambulance crew (simulated)")
                else:
                    _finish(conn, inc, "closed", "ambulance crew (simulated)", "handover", "Patient handed over; ambulance available")
                continue
            row = conn.execute("SELECT * FROM legs WHERE incident_id = ? AND done = 0 ORDER BY id DESC LIMIT 1",
                               (inc["id"],)).fetchone()
            if row is None:
                continue
            _demo_police(conn, inc, row)
            row = conn.execute("SELECT * FROM legs WHERE id = ?", (row["id"],)).fetchone()
            if not amb["simulated"] or dt == 0:
                continue
            route = _route(conn, row["id"])
            leg = dict(row, waited=json.loads(row["waited_json"]))
            arrived = _advance(leg, route, _answers(conn, row["id"]), dt)
            lat, lon = _point(route, leg["along_m"])
            conn.execute("UPDATE legs SET along_m = ?, elapsed_s = ?, wait_s = ?, waited_json = ?, done = ? WHERE id = ?",
                         (leg["along_m"], leg["elapsed_s"], leg["wait_s"], json.dumps(leg["waited"]), int(arrived), row["id"]))
            conn.execute("UPDATE ambulances SET lat = ?, lon = ?, updated_utc = ? WHERE id = ?", (lat, lon, _now_iso(), amb["id"]))
            if arrived:
                if row["kind"] == "to_scene":
                    conn.execute("UPDATE incidents SET phase = 'at_scene', dwell_s = ? WHERE id = ?", (SCENE_TIME_S, inc["id"]))
                    _log(conn, inc["id"], amb["callsign"], "at_scene", f"Arrived after {round(leg['elapsed_s'])} s")
                else:
                    conn.execute("UPDATE incidents SET phase = 'at_hospital', dwell_s = ? WHERE id = ?", (HANDOVER_TIME_S, inc["id"]))
                    _log(conn, inc["id"], amb["callsign"], "at_hospital",
                         f"Arrived at {route['destination']['name']} after {round(leg['elapsed_s'])} s")


def run_simulation(stop: threading.Event) -> None:
    last = time.monotonic()
    while not stop.wait(TICK_S):
        now = time.monotonic()
        try:
            tick(now - last)
        except Exception as e:  # keep the loop alive; the next tick retries
            print(f"[simulation] {type(e).__name__}: {e}", flush=True)
        last = now


def signal_command(signal_id: int) -> dict:
    """What a real signal controller at this junction should do right now."""
    for h in state(0)["holds"]:
        if h["signal_id"] == signal_id:
            return {"signal_id": signal_id, "command": "hold_green", "incident_id": h["incident_id"],
                    "ambulance": h["ambulance"]}
    return {"signal_id": signal_id, "command": "normal"}


def start_demo(hour: int) -> List[dict]:
    """Three accidents at once, with scripted control-room answers: cleared, partly cleared, declined."""
    scenes = [
        ([12.9352, 77.6245], "Two-wheeler collision near Koramangala", {"decision": "approved", "after_s": 3}),
        ([12.9784, 77.6408], "Pedestrian hit near Indiranagar", {"decision": "partial", "note": "Road works at one junction", "after_s": 4}),
        ([13.0070, 77.5700], "Car overturned near Malleshwaram", {"decision": "declined", "note": "VIP movement on this route", "after_s": 5}),
    ]
    with db.connect() as conn:
        for inc in conn.execute("SELECT * FROM incidents WHERE status = 'active'").fetchall():
            _finish(conn, inc, "cancelled", "demo", "cancelled", "Cleared for a new demo")
    created = []
    for scene, text, police in scenes:
        demo = {"to_scene": police, "to_hospital": {"decision": "approved", "after_s": 3}}
        created.append(create_incident(scene, hour, description=text, demo=demo))
    return created
