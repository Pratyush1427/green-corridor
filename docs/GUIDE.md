# Green Corridor: detailed guide

Everything beyond the [README](../README.md): setup in detail, collecting real traffic data,
the API, how routing works, and how to refresh the map data.

- [Setup, step by step](#setup-step-by-step)
- [Traffic data on the map](#traffic-data-on-the-map)
- [The four screens](#the-four-screens)
- [API](#api)
- [How routing works (and its limits)](#how-routing-works-and-its-limits)
- [Collecting real traffic data](#collecting-real-traffic-data)
- [Map data: hospitals, signals, roads](#map-data-hospitals-signals-roads)
- [Project files](#project-files)

## Setup, step by step

`./run.sh` does all of this for you. To do it by hand, run these in a terminal, one at a time.

```bash
git clone https://github.com/Pratyush1427/green-corridor.git
cd green-corridor
```
Download the project and move into its folder.

```bash
python3 -m venv venv
```
Create a *virtual environment*: a private folder (`venv/`) for this project's Python packages,
so they don't clash with other projects. You only do this once.

```bash
source venv/bin/activate
```
Turn the virtual environment on. Your prompt will show `(venv)`. Do this **every time** you open
a new terminal to work on the project. (`deactivate` turns it off.)

```bash
pip install -r requirements.txt
```
Install the packages listed in `requirements.txt` (FastAPI, uvicorn, httpx, python-dotenv).

```bash
uvicorn app:app --reload
```
Start the web server. `--reload` restarts it automatically when you edit code.
Open <http://127.0.0.1:8000>. Press `Ctrl+C` to stop the server.

On the first start without a TomTom key, the app fills its database (`traffic.db`) with
14 days of realistic **demo traffic data** (rush hours around 9–11am and 6–9pm, lighter
weekends), so everything works straight away. To start over, delete `traffic.db`.

**With Docker** instead: `docker build -t green-corridor . && docker run -p 8000:8000 green-corridor`

## Traffic data on the map

The **Traffic** tab of `/dispatch` shows the 19 monitored junctions: **Right now** uses the latest
reading, **Usual traffic at…** the average for an hour (▶ plays through the day). Click a junction
for its usual traffic through the day. Congestion = `1 - current_speed / free_flow_speed`:
0% is a clear road, near 100% is a jam.

Shortcut links:

| Link | Opens |
|---|---|
| `/dispatch?demo=1` | Starts the practice run (three made-up accidents) |
| `/driver?amb=3` | The ambulance screen for ambulance 3 |
| `/junction?signal=<id>` | The signal officer screen for one signal |
| `/driver?amb=3&theme=light` | Force day (or `dark`) colours on the driver screen |

## The four screens

Open <http://127.0.0.1:8000> and pick who you are. Everything is simulated on the server, so
all screens show the same live state, in separate tabs or on phones on the same Wi-Fi
(`HOST=0.0.0.0 ./run.sh`; there's no login yet, so only on a network you trust).

The screens are designed for first-time users with little tech experience: plain words, big
buttons, one clear action at a time, and colours that always mean the same thing:
**green** = go / cleared, **orange** = waiting, **red** = stop / not cleared, **blue** = the button to press.
First-time tips appear once and can be closed.

### 🏥 Hospital or ambulance service (`/dispatch`)
- **Emergencies** tab: press **🚨 Report an accident**, tap the place on the map, then check and
  send. Before sending you see which ambulance will go and how long it will take; you can pick
  another ambulance or hospital. Below that, every ambulance on the way, with its progress and
  whether the police cleared its road.
- **Ambulances** tab: who is free or on a call; **＋ Add** parks a new ambulance on the map.
- **Traffic** tab: how busy the monitored junctions are right now, or usually at a chosen hour.
- **Practice** box: three made-up accidents in evening traffic, and the simulation speed.

### 🚑 Ambulance driver (`/driver`), on a phone
- Pick your ambulance once; the phone remembers it.
- A new emergency fills the screen in red. One tap on **OK** starts the trip and voice guidance.
- While driving: a green turn banner ("1.0 km · Go straight · Varthur Road"), a chip for the
  next signal ("Next signal 590 m · Will turn green for you"), and minutes to go at the bottom.
- At the accident: one big button, **Patient is in the ambulance**. At the hospital:
  **Patient handed over**.
- **English, ಕನ್ನಡ, हिन्दी**, for screen text and voice. Night colours after 6 pm.

### 🚦 Police at a signal (`/junction`), on a phone
- Three-step setup: your name and language → your signal (📍 find it with the phone's location,
  or tap it on the map) → turn on the alarm sound and test it.
- When an ambulance is coming: **AMBULANCE COMING**, a big countdown, where it comes from and
  where it goes (with an arrow), and two buttons: **✓ I will clear the road** or **✕ Not possible**
  (then tap a reason). The phone rings, vibrates and speaks.

### 🚓 Traffic control room (`/police`)
- A banner says whether anyone needs an answer. Each request says "AMB-03 needs a clear road",
  how far, how many signals, how much faster it would be, and how long is left to answer.
- **✓ Yes, clear the road**, **Choose signals** (untick the ones you can't clear), or
  **✕ Not possible** (then tap a reason). Requests expire after 60 seconds.
- Ambulances on the road show which signals are green and any officer's "not possible".
- Optional ring for new requests, and a practice mode that says yes automatically.

## API

Interactive API docs are at <http://127.0.0.1:8000/docs>.

### Dispatch

The interface a real ambulance app, junction officers' phones and signal controllers would use:

| Endpoint | Who calls it | What it does |
|---|---|---|
| `GET /api/state` | Every screen | Fleet, active and recent incidents, signals held green (no route geometry) |
| `POST /api/incidents` | Organisation | Report: `{"scene": [lat, lon], "ambulance_id": null, "hospital": null, "description": "..."}` |
| `GET /api/incidents/{id}` | Any screen | One incident with the full route of both legs |
| `POST /api/incidents/{id}/hospital` | Organisation | Choose the hospital before the patient is on board (`{"hospital": [lat, lon]}` or `null`) |
| `POST /api/incidents/{id}/patient-on-board` | Ambulance | At the scene: start the hospital leg |
| `POST /api/incidents/{id}/handover` | Ambulance | At the hospital: finish, ambulance available again |
| `POST /api/incidents/{id}/cancel` | Organisation | Cancel an incident |
| `GET /api/incidents/{id}/events` | Anyone | Audit log |
| `POST /api/ambulances` | Organisation | Add an ambulance: `{"lat": ..., "lon": ..., "callsign": "AMB-09"}` |
| `POST /api/ambulances/{id}/location` | Ambulance app | Real GPS `{"lat": ..., "lon": ...}`; stops simulating that ambulance |
| `POST /api/legs/{id}/clearance` | Control room | `{"decision": "approved" / "partial" / "declined", "declined_signals": [...], "note": "..."}` |
| `POST /api/legs/{id}/signals/{signal_id}/answer` | Junction officer | `{"answer": "clearing" / "cant", "reason": "Gridlock"}` |
| `GET /api/signals/upcoming` | Junction screen | Junctions ambulances are heading for, soonest first |
| `GET /api/signals/{signal_id}/incoming` | Junction screen | Ambulances coming to one junction, with direction and ETA |
| `GET /api/signals/holds` | Anyone | Every signal held green right now |
| `GET /api/signals/{signal_id}/command` | Signal controller | `"hold_green"` or `"normal"` |
| `POST /api/sim` | Organisation | Simulation speed `{"speed": 10}` (0 pauses) |
| `POST /api/demo` | Organisation | Start the three-accident demo |
| `POST /api/fleet/reset` | Presenter | Cancel active incidents and send every ambulance back to its base |

⚠️ **There is no login yet.** Anyone who can reach the server can report incidents, answer
clearance requests or move ambulances. Before any real use, only verified ambulances may
report and only traffic police accounts may answer.

### Traffic and routing

```bash
curl http://127.0.0.1:8000/api/junctions                          # latest reading per junction
curl http://127.0.0.1:8000/api/patterns/silk_board                # typical congestion by hour
curl "http://127.0.0.1:8000/api/patterns/silk_board?weekday=0"   # Mondays only (0=Mon … 6=Sun)
curl "http://127.0.0.1:8000/api/typical?hour=19"                 # every junction at 7pm
curl -X POST http://127.0.0.1:8000/api/route -H "Content-Type: application/json" \
     -d '{"start": [12.93, 77.62], "hour": 19}'                   # plan a trip (no police request)
```

## How routing works (and its limits)

- The road network is Bengaluru's **main roads** only (motorways down to tertiary roads), to
  keep it small. An ambulance dropped on a side street starts from the nearest main-road junction.
  One-way streets are respected.
- Each road's speed is its speed limit (or a typical speed for its road type), slowed by the
  typical congestion at the nearest monitored junction for that hour.
- The ambulance goes to the emergency hospital it can reach **fastest**, not the nearest one.
- **Normal traffic**: the ambulance moves at the congested speed and waits an average of
  ~12 s at each red signal.
- **Green corridor**: cleared signals are green and traffic is cleared, so the ambulance feels
  only a third of the congestion. At junctions police didn't clear, it stops like normal traffic.

These are **simple, made-up assumptions**, set as constants at the top of `routing.py`, not a
validated traffic model. They're a starting point for experiments. A more realistic
comparison would use a traffic simulator such as [SUMO](https://eclipse.dev/sumo/).

## Collecting real traffic data

The demo data is generated. To collect real congestion from the
[TomTom Traffic API](https://developer.tomtom.com/traffic-api/documentation):

```bash
cp .env.example .env
```
Open `.env` and paste your key after `TOMTOM_API_KEY=`. Get a free key at
[developer.tomtom.com](https://developer.tomtom.com) (free tier: 2,500 requests/day;
19 junctions every 15 minutes uses about 1,824/day). `.env` is in `.gitignore`, so your key
never gets committed.

```bash
rm traffic.db
```
Delete the demo data so it doesn't mix with real readings. With a key set, the app no longer
generates demo data.

```bash
python collector.py --once
```
Poll TomTom one time. It should print `Stored 19/19 readings`.

```bash
python collector.py
```
Poll forever, every 15 minutes. Patterns get useful after a week or two of data.

To keep it running after you close the terminal:
```bash
nohup python collector.py > collector.log 2>&1 &
```
- `nohup` keeps it alive after the terminal closes, `&` runs it in the background
- output goes to `collector.log` (see it with `tail -f collector.log`)
- stop it later with `pkill -f collector.py`

A laptop stops collecting when it sleeps (`caffeinate -i python collector.py` prevents that
on a Mac). For continuous data, run it on an always-on machine such as a small cloud server
or a Raspberry Pi.

Other collector options: `--fake` generates fake readings instead of calling TomTom, and
`--fake --backfill-days N` fills N days of past fake data.

### Adding junctions

Add an entry to `JUNCTIONS` in `config.py` with a unique `id`, a `name`, and `lat`/`lon`.
Entries marked "(approx)" have rough coordinates, so check those on the map: TomTom snaps to
the nearest road segment, so a point on the main road through the junction gives the best
results. Each junction costs 96 requests/day at a 15-minute interval, so about 26 junctions is
the maximum on the free tier.

## Map data: hospitals, signals, roads

All three come from OpenStreetMap (© OpenStreetMap contributors, ODbL) and are already
included. The public download server is often busy, so the scripts retry a few times.

| Data | Refresh with | Notes |
|---|---|---|
| Hospitals (`static/hospitals.json`) | `python fetch_hospitals.py` | 1,097 hospitals; 111 tagged `emergency=yes`. Many real emergency hospitals aren't tagged yet: fix that on OpenStreetMap, or set `"emergency": true` in the file |
| Traffic signals (`static/signals.json`) | `python fetch_signals.py` | 1,384 signal points merged into 611 junctions (points within 40 m). Locations are real. Each route's signals are shown on every screen; a signal is held green only for a cleared ambulance |
| Roads (`data/roads.json.gz`) | `python fetch_roads.py` | Main roads only, 16.5k junctions, 1 MB. Large download |

## Project files

| File | What it does |
|---|---|
| `app.py` | The web server: JSON API, the ambulance map and the control room |
| `routing.py` | Traffic-aware ambulance routing, with and without a green corridor |
| `dispatch.py` | Fleet, incidents and their two legs, police and junction answers, signal commands, the simulation loop and audit log |
| `collector.py` | Fetches traffic data from TomTom (or generates demo data) |
| `db.py` | SQLite tables and queries for traffic readings |
| `config.py` | The monitored junctions and settings |
| `osm.py` | Shared helper for downloading OpenStreetMap data |
| `fetch_hospitals.py`, `fetch_signals.py`, `fetch_roads.py` | Refresh the map data |
| `static/home.html` | Start page: "Who are you?" |
| `static/dispatch.html`, `static/dispatch-view.js` | Hospital & ambulance service (`/dispatch`): report accidents, ambulances, traffic |
| `static/driver.html` | The ambulance screen (`/driver`) |
| `static/junction.html` | The junction officer screen (`/junction`) |
| `static/common.js`, `static/common.css` | Helpers and styles shared by the screens |
| `static/pitch.html` | The presenter view (`/pitch`): all screens and a narrated story |
| `static/police.html` | The traffic control room (`/police`) |
| `run.sh`, `Dockerfile` | One-command start, locally or in a container |
