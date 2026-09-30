"""FastAPI app: JSON API, the ambulance map (/) and the traffic control room (/police).

Run with:  uvicorn app:app --reload   (or ./run.sh)
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import collector
import db
import emergencies
import routing
from config import JUNCTIONS, JUNCTIONS_BY_ID, TOMTOM_API_KEY

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(
    title="Green Corridor",
    description="Simulated green corridors for ambulances in Bengaluru.",
)
db.init_db()
emergencies.init()

# First run without a TomTom key: fill the database with realistic demo data so the maps and
# charts work straight away. With a key, the database is left empty for real readings.
DEMO_DAYS = 14
if not TOMTOM_API_KEY and db.reading_count() == 0:
    collector.log(f"No traffic data yet and no TOMTOM_API_KEY: generating {DEMO_DAYS} days of demo data")
    collector.backfill(DEMO_DAYS)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/police")
def police() -> FileResponse:
    return FileResponse(STATIC_DIR / "police.html")


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


def ist_hour_now() -> int:
    return datetime.now(timezone(timedelta(hours=5, minutes=30))).hour


@app.post("/api/route")
def route(req: RouteRequest) -> dict:
    """Plan a simulated ambulance trip, with and without a green corridor."""
    hour = ist_hour_now() if req.hour is None else req.hour
    try:
        return routing.plan_route(req.start[0], req.start[1], hour,
                                  tuple(req.hospital) if req.hospital else None)
    except routing.RouteError as e:
        raise HTTPException(status_code=422, detail=str(e))


# ---------- emergencies & traffic police clearance ----------
# NOTE: no authentication yet. Anyone who can reach the server can trigger or approve.

class EmergencyRequest(RouteRequest):
    ambulance: str = Field(..., min_length=1, max_length=40, description="Ambulance name or number")


class LocationUpdate(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)


class ClearanceDecision(BaseModel):
    decision: str = Field(..., description="approved | partial | declined")
    declined_signals: List[int] = Field(default_factory=list, description="for 'partial': signal ids NOT cleared")
    officer: str = Field("traffic police", max_length=60)
    note: Optional[str] = Field(None, max_length=300)


class CloseRequest(BaseModel):
    status: str = Field(..., description="arrived | cancelled")


def _found(e: Optional[dict]) -> dict:
    if e is None:
        raise HTTPException(status_code=404, detail="Emergency not found")
    return e


@app.post("/api/emergencies")
def create_emergency(req: EmergencyRequest) -> dict:
    """Trigger an emergency: plans the route and sends a clearance request to traffic police."""
    hour = ist_hour_now() if req.hour is None else req.hour
    try:
        return emergencies.create(req.ambulance, req.start, req.hospital, hour)
    except routing.RouteError as e:
        raise HTTPException(status_code=422, detail=str(e))


@app.get("/api/emergencies")
def list_emergencies(include_closed: bool = False, limit: int = Query(30, ge=1, le=200)) -> list:
    return emergencies.list_all(include_closed, limit)


@app.get("/api/emergencies/{emergency_id}")
def get_emergency(emergency_id: int) -> dict:
    return _found(emergencies.get(emergency_id))


@app.get("/api/emergencies/{emergency_id}/events")
def emergency_events(emergency_id: int) -> list:
    _found(emergencies.get(emergency_id))
    return emergencies.events(emergency_id)


@app.post("/api/emergencies/{emergency_id}/location")
def emergency_location(emergency_id: int, loc: LocationUpdate) -> dict:
    """GPS update from the ambulance (a real phone app would call this every few seconds)."""
    return _found(emergencies.update_location(emergency_id, loc.lat, loc.lon))


@app.post("/api/emergencies/{emergency_id}/clearance")
def emergency_clearance(emergency_id: int, body: ClearanceDecision) -> dict:
    """Traffic police decision: clear the whole route, some junctions, or 'not possible'."""
    try:
        return _found(emergencies.decide(emergency_id, body.decision, body.declined_signals,
                                         body.officer, body.note))
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@app.post("/api/emergencies/{emergency_id}/close")
def emergency_close(emergency_id: int, body: CloseRequest) -> dict:
    try:
        return _found(emergencies.close(emergency_id, body.status, "ambulance crew"))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@app.get("/api/signals/holds")
def signal_holds() -> list:
    """Every signal currently held green for an ambulance."""
    return emergencies.signal_holds()


@app.get("/api/signals/{signal_id}/command")
def signal_command(signal_id: int) -> dict:
    """What a signal controller at this junction should do now: 'hold_green' or 'normal'."""
    return emergencies.signal_command(signal_id)
