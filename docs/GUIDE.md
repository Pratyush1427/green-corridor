# Green Corridor: detailed guide

Everything beyond the [README](../README.md): setup in detail, collecting real traffic data,
the API, how routing works, and how to refresh the map data.

- [Setup, step by step](#setup-step-by-step)
- [Using the maps](#using-the-maps)
- [Simulated ambulances and traffic police clearance](#simulated-ambulances-and-traffic-police-clearance)
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

## Using the maps

- **Live (latest)** colours each monitored junction by its most recent reading.
- **Typical by hour** colours junctions by their average congestion at the hour on the slider.
  Press ▶ to watch the whole day play out.
- Click a junction to see its daily pattern chart and the nearest emergency hospitals.
- **Traffic signals** appear once you zoom in (they'd clutter the city-wide view).
- **Congestion** = `1 - current_speed / free_flow_speed`: 0% is a clear road, near 100% is a jam.

Shortcut links:

| Link | Opens |
|---|---|
| `/?demo=1` | Runs the one-click demo |
| `/?hour=19` | "Typical by hour" at 7pm |
| `/?hour=9&junction=silk_board&zoom=15` | Silk Board at 9am, zoomed in |
| `/?hour=19&amb=12.945,77.61&amb=13.02,77.60` | Drops two ambulances into 7pm traffic |

## Simulated ambulances and traffic police clearance

Open two browser tabs: the **ambulance map** (<http://127.0.0.1:8000>) and the **traffic
control room** (<http://127.0.0.1:8000/police>). You play both the ambulance crew and the police.
Or click **▶ Run demo**, and the page plays the police for you.

**On the ambulance map:**
1. Click **＋ Add ambulance**, then click anywhere on the map. This triggers an emergency:
   the route is planned and a clearance request goes to the control room.
2. The ambulance picks the **fastest emergency hospital** (by travel time, not distance).
   Use its dropdown to send it to a specific hospital instead.
3. It **sets off immediately in normal traffic**. It never waits for the police's answer.
4. **Drag** an ambulance to move it; it re-plans and sends a new request. Add as many as you like.
5. The speed dropdown speeds up the simulation (10× by default).

**In the control room**, each request shows the route, its junctions and the time a corridor
would save. The officer can:
- **Clear all junctions**: approved signals are held green from 45 seconds before the
  ambulance reaches them until it passes, and the ambulance drives at corridor speed.
- **Choose junctions…**: clear only some (e.g. not the one with road works), with a note.
- **Not possible**: the ambulance continues in normal traffic and stops at red signals.
- **Revoke clearance** later, if things change.

Requests with no answer within **60 seconds** expire and count as "not possible".
Ambulances that stop reporting their position for 2 minutes are marked "lost contact".
Tick **Auto-approve** for hands-free demos. Every trigger, decision and arrival is recorded;
click **Log** on a request to see it.

Route signal colours: amber = waiting for police, dark with green ring = cleared,
bright green = held green now, red = not cleared, grey = passed.

## API

Interactive API docs are at <http://127.0.0.1:8000/docs>.

### Emergencies

This is the interface a real ambulance app and real signal controllers would use:

| Endpoint | Who calls it | What it does |
|---|---|---|
| `POST /api/emergencies` | Ambulance app | Trigger: `{"ambulance": "KA-01-1234", "start": [lat, lon], "hospital": [lat, lon] or null}` |
| `POST /api/emergencies/{id}/location` | Ambulance app | GPS update `{"lat": ..., "lon": ...}`, every few seconds |
| `POST /api/emergencies/{id}/close` | Ambulance app | `{"status": "arrived"}` or `"cancelled"` |
| `GET /api/emergencies` | Control room | Active emergencies (`?include_closed=true` for recent ones too) |
| `POST /api/emergencies/{id}/clearance` | Traffic police | `{"decision": "approved" / "partial" / "declined", "declined_signals": [...], "note": "..."}` |
| `GET /api/emergencies/{id}/events` | Anyone | Audit log |
| `GET /api/signals/holds` | Anyone | Every signal held green right now |
| `GET /api/signals/{signal_id}/command` | Signal controller | `"hold_green"` or `"normal"` |

⚠️ **There is no login yet.** Anyone who can reach the server can trigger emergencies or
approve them. Before any real use, triggering must be limited to verified ambulances and
decisions to traffic police accounts.

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
| Traffic signals (`static/signals.json`) | `python fetch_signals.py` | 1,384 signal points merged into 611 junctions (points within 40 m). Locations are real; the red/amber/green cycle is simulated (90 s: 40 green, 4 amber, 46 red), set in `static/index.html` |
| Roads (`data/roads.json.gz`) | `python fetch_roads.py` | Main roads only, 16.5k junctions, 1 MB. Large download |

## Project files

| File | What it does |
|---|---|
| `app.py` | The web server: JSON API, the ambulance map and the control room |
| `routing.py` | Traffic-aware ambulance routing, with and without a green corridor |
| `emergencies.py` | Emergencies, traffic-police clearance, signal commands and the audit log |
| `collector.py` | Fetches traffic data from TomTom (or generates demo data) |
| `db.py` | SQLite tables and queries for traffic readings |
| `config.py` | The monitored junctions and settings |
| `osm.py` | Shared helper for downloading OpenStreetMap data |
| `fetch_hospitals.py`, `fetch_signals.py`, `fetch_roads.py` | Refresh the map data |
| `static/index.html` | The ambulance map (Leaflet + Chart.js, loaded from a CDN) |
| `static/ambulances.js` | The simulated ambulances and the one-click demo |
| `static/police.html` | The traffic control room (`/police`) |
| `run.sh`, `Dockerfile` | One-command start, locally or in a container |
