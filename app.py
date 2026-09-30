"""FastAPI app: JSON API + the map page.

Run with:  uvicorn app:app --reload
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import db
import routing
from config import JUNCTIONS, JUNCTIONS_BY_ID

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="Bengaluru Traffic Pattern Tracker")
db.init_db()
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


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


@app.get("/api/typical")
def typical(
    hour: int = Query(..., ge=0, le=23, description="Hour of day in IST"),
    weekday: Optional[int] = Query(None, ge=0, le=6, description="0 = Monday ... 6 = Sunday"),
) -> list:
    """Typical (average) congestion at every junction for one hour of the day."""
    return [
        {**r, "congestion": None if r["congestion"] is None else round(r["congestion"], 3)}
        for r in db.typical_at_hour(hour, weekday)
    ]


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


class RouteRequest(BaseModel):
    start: List[float] = Field(..., min_length=2, max_length=2, description="[lat, lon] of the ambulance")
    hospital: Optional[List[float]] = Field(
        None, min_length=2, max_length=2,
        description="[lat, lon] of the destination; omit for the fastest emergency hospital",
    )
    hour: Optional[int] = Field(None, ge=0, le=23, description="IST hour for traffic; default: now")


@app.post("/api/route")
def route(req: RouteRequest) -> dict:
    """Plan a simulated ambulance trip, with and without a green corridor."""
    hour = req.hour
    if hour is None:
        hour = datetime.now(timezone(timedelta(hours=5, minutes=30))).hour
    try:
        return routing.plan_route(req.start[0], req.start[1], hour,
                                  tuple(req.hospital) if req.hospital else None)
    except routing.RouteError as e:
        raise HTTPException(status_code=422, detail=str(e))
