"""FastAPI app: JSON API + the map page.

Run with:  uvicorn app:app --reload
"""
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse

import db
from config import JUNCTIONS, JUNCTIONS_BY_ID

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="Bengaluru Traffic Pattern Tracker")
db.init_db()


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/junctions")
def junctions() -> list:
    latest = {r["junction_id"]: r for r in db.latest_per_junction()}
    result = []
    for j in JUNCTIONS:
        r = latest.get(j["id"])
        result.append({
            **j,
            "latest": None if r is None else {
                "ts_utc": r["ts_utc"],
                "current_speed": r["current_speed"],
                "free_flow_speed": r["free_flow_speed"],
                "current_travel_time": r["current_travel_time"],
                "free_flow_travel_time": r["free_flow_travel_time"],
                "confidence": r["confidence"],
                "road_closure": bool(r["road_closure"]),
                "congestion": None if r["congestion"] is None else round(r["congestion"], 3),
            },
        })
    return result


@app.get("/api/patterns/{junction_id}")
def patterns(
    junction_id: str,
    weekday: Optional[int] = Query(None, ge=0, le=6, description="0 = Monday ... 6 = Sunday"),
) -> dict:
    if junction_id not in JUNCTIONS_BY_ID:
        raise HTTPException(status_code=404, detail=f"Unknown junction '{junction_id}'")
    return {
        "junction_id": junction_id,
        "weekday": weekday,
        "hours": db.hourly_pattern(junction_id, weekday),
    }
