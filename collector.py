"""Polls TomTom traffic flow for each junction and stores it in SQLite.

Usage:
    python collector.py                              # poll forever, every POLL_MINUTES
    python collector.py --once                       # poll one time (for testing)
    python collector.py --fake                       # generate fake data instead of calling TomTom
    python collector.py --fake --backfill-days 7     # fill 7 days of past fake data, then exit
"""
import argparse
import math
import random
import sys
import time
from datetime import datetime, timedelta, timezone

import httpx

import db
from config import JUNCTIONS, POLL_MINUTES, TOMTOM_API_KEY

TOMTOM_URL = "https://api.tomtom.com/traffic/services/4/flowSegmentData/absolute/10/json"
IST = timezone(timedelta(hours=5, minutes=30))


def utc_str(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


# ---------- real data ----------

def fetch_tomtom(client: httpx.Client, junction: dict, now: datetime) -> dict:
    resp = client.get(
        TOMTOM_URL,
        params={"point": f"{junction['lat']},{junction['lon']}", "key": TOMTOM_API_KEY},
        timeout=15,
    )
    resp.raise_for_status()
    flow = resp.json()["flowSegmentData"]
    return {
        "junction_id": junction["id"],
        "ts_utc": utc_str(now),
        "current_speed": flow["currentSpeed"],
        "free_flow_speed": flow["freeFlowSpeed"],
        "current_travel_time": flow["currentTravelTime"],
        "free_flow_travel_time": flow["freeFlowTravelTime"],
        "confidence": flow.get("confidence"),
        "road_closure": flow.get("roadClosure", False),
    }


# ---------- fake data ----------

def fake_congestion(ist_time: datetime, junction_id: str) -> float:
    """Rush-hour shaped congestion (0-1) for a given IST time."""
    hour = ist_time.hour + ist_time.minute / 60
    # Two bell curves: morning peak ~10am, evening peak ~7:30pm.
    morning = 0.55 * math.exp(-((hour - 10) ** 2) / 2.0)
    evening = 0.65 * math.exp(-((hour - 19.5) ** 2) / 3.0)
    base = 0.12 + morning + evening
    if ist_time.weekday() >= 5:  # weekends are lighter
        base *= 0.6
    # Some junctions are just worse than others (stable per junction).
    base *= random.Random(junction_id).uniform(0.85, 1.15)
    return max(0.0, min(0.95, base + random.gauss(0, 0.05)))


def fake_reading(junction: dict, now: datetime) -> dict:
    free_flow_speed = random.Random(junction["id"]).choice([35, 40, 45, 50])
    congestion = fake_congestion(now.astimezone(IST), junction["id"])
    current_speed = round(free_flow_speed * (1 - congestion))
    segment_m = 800
    return {
        "junction_id": junction["id"],
        "ts_utc": utc_str(now),
        "current_speed": current_speed,
        "free_flow_speed": free_flow_speed,
        "current_travel_time": round(segment_m / max(current_speed, 1) * 3.6),
        "free_flow_travel_time": round(segment_m / free_flow_speed * 3.6),
        "confidence": 1.0,
        "road_closure": False,
    }


def backfill(days: int) -> None:
    end = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    t = end - timedelta(days=days)
    readings = []
    while t <= end:
        readings.extend(fake_reading(j, t) for j in JUNCTIONS)
        t += timedelta(minutes=POLL_MINUTES)
    db.insert_readings(readings)
    log(f"Backfilled {len(readings)} fake readings over {days} days")


# ---------- polling loop ----------

def poll_once(client: httpx.Client, fake: bool) -> None:
    now = datetime.now(timezone.utc)
    ok = 0
    for junction in JUNCTIONS:
        try:
            reading = fake_reading(junction, now) if fake else fetch_tomtom(client, junction, now)
            db.insert_reading(reading)
            ok += 1
        except Exception as e:  # one bad junction shouldn't stop the others
            log(f"ERROR {junction['id']}: {e}")
    log(f"Stored {ok}/{len(JUNCTIONS)} readings{' (fake)' if fake else ''}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect Bengaluru traffic readings.")
    parser.add_argument("--once", action="store_true", help="poll one time and exit")
    parser.add_argument("--fake", action="store_true", help="generate fake data, no API key needed")
    parser.add_argument("--backfill-days", type=int, default=0, metavar="N",
                        help="with --fake: fill N days of past data and exit")
    args = parser.parse_args()

    db.init_db()

    if args.backfill_days:
        if not args.fake:
            sys.exit("--backfill-days only works together with --fake")
        backfill(args.backfill_days)
        return

    if not args.fake and not TOMTOM_API_KEY:
        sys.exit("TOMTOM_API_KEY is missing. Put it in .env, or use --fake to test without one.")

    with httpx.Client() as client:
        if args.once:
            poll_once(client, args.fake)
            return
        log(f"Polling {len(JUNCTIONS)} junctions every {POLL_MINUTES} min. Ctrl+C to stop.")
        while True:
            poll_once(client, args.fake)
            time.sleep(POLL_MINUTES * 60)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("Stopped.")
