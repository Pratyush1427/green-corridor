"""SQLite setup and query helpers."""
import sqlite3
from typing import List, Optional

from config import DB_PATH

# congestion = 1 - current / free-flow speed, clamped to [0, 1]. Computed at read time.
CONGESTION_SQL = (
    "MAX(0.0, MIN(1.0, 1.0 - CAST(current_speed AS REAL) / NULLIF(free_flow_speed, 0)))"
)


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS readings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                junction_id TEXT NOT NULL,
                ts_utc TEXT NOT NULL,
                current_speed REAL,
                free_flow_speed REAL,
                current_travel_time INTEGER,
                free_flow_travel_time INTEGER,
                confidence REAL,
                road_closure INTEGER
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_readings_junction_ts ON readings (junction_id, ts_utc)"
        )


INSERT_SQL = """
    INSERT INTO readings (junction_id, ts_utc, current_speed, free_flow_speed,
        current_travel_time, free_flow_travel_time, confidence, road_closure)
    VALUES (:junction_id, :ts_utc, :current_speed, :free_flow_speed,
        :current_travel_time, :free_flow_travel_time, :confidence, :road_closure)
"""


def insert_reading(reading: dict) -> None:
    """Store one reading.

    Keys match the table columns. ts_utc is a string like '2026-09-27 10:15:00' (UTC).
    """
    insert_readings([reading])


def insert_readings(readings: List[dict]) -> None:
    """Store many readings in one transaction (much faster for backfills)."""
    rows = [dict(r, road_closure=int(bool(r["road_closure"]))) for r in readings]
    with connect() as conn:
        conn.executemany(INSERT_SQL, rows)


def latest_per_junction() -> List[dict]:
    """The most recent reading for every junction that has data."""
    with connect() as conn:
        rows = conn.execute(
            f"""
            SELECT r.*, {CONGESTION_SQL} AS congestion
            FROM readings r
            JOIN (
                SELECT junction_id, MAX(ts_utc) AS max_ts
                FROM readings GROUP BY junction_id
            ) latest ON r.junction_id = latest.junction_id AND r.ts_utc = latest.max_ts
            GROUP BY r.junction_id
            """
        ).fetchall()
    return [dict(r) for r in rows]


IST_SQL = "datetime(ts_utc, '+5 hours', '+30 minutes')"
# SQLite's %w is 0 = Sunday; this converts it to Python's 0 = Monday.
WEEKDAY_SQL = f"(CAST(strftime('%w', {IST_SQL}) AS INTEGER) + 6) % 7"


def typical_at_hour(hour: int, weekday: Optional[int] = None) -> List[dict]:
    """Average congestion per junction at one IST hour (0-23), optionally one weekday."""
    sql = f"""
        SELECT junction_id, AVG({CONGESTION_SQL}) AS congestion, COUNT(*) AS samples
        FROM readings
        WHERE CAST(strftime('%H', {IST_SQL}) AS INTEGER) = ?
    """
    params = [hour]
    if weekday is not None:
        sql += f" AND {WEEKDAY_SQL} = ?"
        params.append(weekday)
    sql += " GROUP BY junction_id"
    with connect() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def hourly_pattern(junction_id: str, weekday: Optional[int] = None) -> List[dict]:
    """Average congestion for each IST hour (0-23).

    weekday uses Python's convention: 0 = Monday ... 6 = Sunday.
    Hours with no data come back with congestion None.
    """
    sql = f"""
        SELECT CAST(strftime('%H', {IST_SQL}) AS INTEGER) AS hour,
               AVG({CONGESTION_SQL}) AS congestion,
               COUNT(*) AS samples
        FROM readings
        WHERE junction_id = ?
    """
    params = [junction_id]
    if weekday is not None:
        sql += f" AND {WEEKDAY_SQL} = ?"
        params.append(weekday)
    sql += " GROUP BY hour ORDER BY hour"

    with connect() as conn:
        rows = {r["hour"]: r for r in conn.execute(sql, params).fetchall()}

    return [
        {
            "hour": h,
            "congestion": round(rows[h]["congestion"], 3) if h in rows else None,
            "samples": rows[h]["samples"] if h in rows else 0,
        }
        for h in range(24)
    ]
