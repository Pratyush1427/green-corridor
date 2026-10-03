"""FastAPI app: JSON API and four screens:

    /          start page: "Who are you?"
    /dispatch  hospital / ambulance service: report accidents, fleet, all trips, traffic
    /driver    ambulance driver: their own trip, next signals, spoken alerts
    /junction  constable at a junction: incoming ambulances, "clearing" / "can't"
    /police    traffic control room: approve, partly approve or decline corridors
    /pitch     presenter view for demos: all of the above on one screen, with a narrated story

Run with:  uvicorn app:app --reload   (or ./run.sh)
"""
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import collector
import db
import dispatch
import routing
from config import JUNCTIONS, JUNCTIONS_BY_ID, TOMTOM_API_KEY

STATIC_DIR = Path(__file__).parent / "static"

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run the ambulance simulation in the background while the server is up."""
    stop = threading.Event()
    thread = threading.Thread(target=dispatch.run_simulation, args=(stop,), daemon=True)
    thread.start()
    yield
    stop.set()
    thread.join(timeout=2)


app = FastAPI(
    title="Green Corridor",
    description="Simulated green corridors for ambulances in Bengaluru.",
    lifespan=lifespan,
)
db.init_db()

# First run without a TomTom key: fill the database with realistic demo data so the maps and
# charts work straight away. With a key, the database is left empty for real readings.
DEMO_DAYS = 14
if not TOMTOM_API_KEY and db.reading_count() == 0:
    collector.log(f"No traffic data yet and no TOMTOM_API_KEY: generating {DEMO_DAYS} days of demo data")
    collector.backfill(DEMO_DAYS)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.middleware("http")
async def always_fresh_pages(request, call_next):
    """Pages and scripts change often during development and demos: make browsers re-check them
    (they still get a quick 'not modified' when nothing changed), so nobody sees a stale screen."""
    response = await call_next(request)
    path = request.url.path
    if not path.startswith("/api/") and not path.endswith((".png", ".gif", ".json", ".gz")):
        response.headers["Cache-Control"] = "no-cache"
    return response
dispatch.init()


@app.get("/")
def home(request: Request):
    """Start page: "Who are you?". Old links with options (e.g. /?demo=1) go to the dispatch screen."""
    if request.url.query:
        return RedirectResponse(f"/dispatch?{request.url.query}")
    return FileResponse(STATIC_DIR / "home.html")


@app.get("/dispatch")
def dispatch_screen() -> FileResponse:
    """Hospital / ambulance service: report accidents, follow every ambulance."""
    return FileResponse(STATIC_DIR / "dispatch.html")


@app.get("/police")
def police() -> FileResponse:
    return FileResponse(STATIC_DIR / "police.html")


@app.get("/driver")
def driver() -> FileResponse:
    return FileResponse(STATIC_DIR / "driver.html")


@app.get("/junction")
def junction() -> FileResponse:
    return FileResponse(STATIC_DIR / "junction.html")


@app.get("/pitch")
def pitch() -> FileResponse:
    """Presenter view for demos: all screens on one page, with a narrated story."""
    return FileResponse(STATIC_DIR / "pitch.html")


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


# ---------- dispatch: fleet, incidents, clearance ----------
# NOTE: no authentication yet. Anyone who can reach the server can report, dispatch or approve.

class IncidentRequest(BaseModel):
    scene: List[float] = Field(..., min_length=2, max_length=2, description="[lat, lon] of the accident")
    ambulance_id: Optional[int] = Field(None, description="omit to send the ambulance that can get there fastest")
    hospital: Optional[List[float]] = Field(None, min_length=2, max_length=2,
                                            description="[lat, lon]; omit for the fastest emergency hospital")
    description: Optional[str] = Field(None, max_length=200)
    hour: Optional[int] = Field(None, ge=0, le=23, description="IST hour for traffic; default: now")


class AmbulanceRequest(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)
    callsign: Optional[str] = Field(None, max_length=20)


class LocationUpdate(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)


class ClearanceDecision(BaseModel):
    decision: str = Field(..., description="approved | partial | declined")
    declined_signals: List[int] = Field(default_factory=list, description="for 'partial': signal ids NOT cleared")
    officer: str = Field("traffic control room", max_length=60)
    note: Optional[str] = Field(None, max_length=300)


class JunctionAnswer(BaseModel):
    answer: str = Field(..., description="clearing | cant")
    reason: Optional[str] = Field(None, max_length=120)
    officer: str = Field("junction officer", max_length=60)


class SimSettings(BaseModel):
    speed: float = Field(..., ge=0, le=60, description="simulated seconds per real second (0 = paused)")


def _call(fn, *args):
    """Run a dispatch action, turning its errors into HTTP responses."""
    try:
        result = fn(*args)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e).strip("'"))
    except (ValueError, routing.RouteError) as e:
        raise HTTPException(status_code=409 if isinstance(e, ValueError) else 422, detail=str(e))
    if result is None:
        raise HTTPException(status_code=404, detail="Not found")
    return result


@app.get("/api/state")
def get_state() -> dict:
    """Fleet, active and recent incidents, and signals held green (no route geometry)."""
    return dispatch.state()


class PreviewRequest(BaseModel):
    scene: List[float] = Field(..., min_length=2, max_length=2)
    ambulance_id: Optional[int] = None
    hour: Optional[int] = Field(None, ge=0, le=23)


@app.post("/api/incidents/preview")
def preview_incident(req: PreviewRequest) -> dict:
    """Which ambulance would go and how long it would take, without sending it (to confirm first)."""
    hour = ist_hour_now() if req.hour is None else req.hour
    return _call(dispatch.preview_incident, req.scene, hour, req.ambulance_id)


@app.post("/api/incidents")
def report_incident(req: IncidentRequest) -> dict:
    """Report an accident and dispatch an ambulance to it."""
    hour = ist_hour_now() if req.hour is None else req.hour
    return _call(dispatch.create_incident, req.scene, hour, req.ambulance_id, req.hospital, req.description)


@app.get("/api/incidents/{incident_id}")
def get_incident(incident_id: int) -> dict:
    """One incident with full route geometry for both legs."""
    return _call(dispatch.get_incident, incident_id)


@app.get("/api/incidents/{incident_id}/events")
def incident_events(incident_id: int) -> list:
    _call(dispatch.get_incident, incident_id, False)
    return dispatch.events(incident_id)


@app.post("/api/incidents/{incident_id}/patient-on-board")
def patient_on_board(incident_id: int) -> dict:
    """Ambulance crew at the scene: start the hospital leg."""
    return _call(dispatch.patient_on_board, incident_id)


class HospitalChoice(BaseModel):
    hospital: Optional[List[float]] = Field(None, min_length=2, max_length=2, description="[lat, lon]; null = fastest")


@app.post("/api/incidents/{incident_id}/hospital")
def choose_hospital(incident_id: int, body: HospitalChoice) -> dict:
    """Organisation: choose the destination hospital before the patient is on board."""
    return _call(dispatch.set_hospital, incident_id, body.hospital)


@app.post("/api/incidents/{incident_id}/handover")
def handover(incident_id: int) -> dict:
    """Ambulance crew at the hospital: patient handed over, ambulance free again."""
    return _call(dispatch.handover, incident_id)


@app.post("/api/incidents/{incident_id}/cancel")
def cancel_incident(incident_id: int) -> dict:
    return _call(dispatch.cancel, incident_id)


@app.post("/api/legs/{leg_id}/clearance")
def leg_clearance(leg_id: int, body: ClearanceDecision) -> dict:
    """Traffic control room: clear the whole leg, some junctions, or 'not possible'."""
    return _call(dispatch.decide, leg_id, body.decision, body.declined_signals, body.officer, body.note)


@app.post("/api/legs/{leg_id}/signals/{signal_id}/answer")
def junction_answer(leg_id: int, signal_id: int, body: JunctionAnswer) -> dict:
    """Constable at one junction: 'clearing' or 'cant'. Overrides the control room for that junction."""
    return _call(dispatch.junction_answer, leg_id, signal_id, body.answer, body.officer, body.reason)


@app.post("/api/ambulances")
def add_ambulance(body: AmbulanceRequest) -> dict:
    return dispatch.add_ambulance(body.lat, body.lon, body.callsign)


@app.post("/api/ambulances/{ambulance_id}/location")
def ambulance_location(ambulance_id: int, loc: LocationUpdate) -> dict:
    """GPS from a real ambulance app (replaces the simulation for that ambulance)."""
    return _call(dispatch.update_location, ambulance_id, loc.lat, loc.lon)


@app.get("/api/signals/upcoming")
def upcoming_signals() -> list:
    """Junctions active ambulances are heading for, soonest first."""
    return dispatch.upcoming_junctions()


@app.get("/api/signals/holds")
def signal_holds() -> list:
    """Every signal currently held green for an ambulance."""
    return dispatch.state(0)["holds"]


@app.get("/api/signals/{signal_id}/incoming")
def signal_incoming(signal_id: int) -> dict:
    """Ambulances heading for one junction, with direction and ETA (for the junction screen)."""
    return _call(dispatch.junction_view, signal_id)


@app.get("/api/signals/{signal_id}/command")
def signal_command(signal_id: int) -> dict:
    """What a signal controller at this junction should do now: 'hold_green' or 'normal'."""
    return dispatch.signal_command(signal_id)


@app.post("/api/fleet/reset")
def fleet_reset() -> dict:
    """Cancel all active incidents and return every ambulance to its base (repeatable demos)."""
    return dispatch.reset_fleet()


@app.post("/api/sim")
def sim_settings(body: SimSettings) -> dict:
    return dispatch.set_speed(body.speed)


@app.post("/api/demo")
def demo(hour: int = Query(19, ge=0, le=23)) -> list:
    """Three accidents at once, with scripted control-room answers."""
    return _call(dispatch.start_demo, hour)
