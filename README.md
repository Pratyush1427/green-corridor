# Bengaluru Traffic Pattern Tracker

The first step toward a **green corridor** system (maps + traffic signals + ambulances).
India has no public API for live ambulance locations or signal state, so this template
starts by collecting **everyday traffic patterns** at key Bengaluru junctions using the
[TomTom Traffic API](https://developer.tomtom.com/traffic-api/documentation).

It:
- logs congestion at 19 junctions every 15 minutes into a local SQLite database
- shows congestion on a blue map (green / amber / red markers; jammed junctions pulse),
  either **live** (latest reading) or **typical by hour** with a slider and a ▶ play button
- shows hospitals from OpenStreetMap (the 111 with emergency departments by default, all 1,097 optional)
- shows 611 real traffic signal locations from OpenStreetMap, each cycling through a
  **simulated** red/amber/green state (real signal timings aren't public)
- lets you **drop simulated ambulances** that drive to the fastest emergency hospital (or one
  you pick) along real roads, with the signals ahead held green: a simulated green corridor
- charts each junction's typical pattern by hour of day and weekday, and lists its
  nearest emergency hospitals

## Files

| File | What it does |
|---|---|
| `config.py` | The junction list (name + lat/lon) and settings like the poll interval |
| `db.py` | Creates the SQLite table and has helper functions to save/query readings |
| `collector.py` | Fetches traffic data from TomTom (or fakes it) and saves it |
| `app.py` | The web server: a small JSON API plus the map page |
| `osm.py` | Shared helper for downloading OpenStreetMap data (with retries) |
| `fetch_hospitals.py` | Downloads Bengaluru hospitals from OpenStreetMap into `static/hospitals.json` |
| `fetch_signals.py` | Downloads Bengaluru traffic signals from OpenStreetMap into `static/signals.json` |
| `fetch_roads.py` | Downloads Bengaluru's main roads from OpenStreetMap into `data/roads.json.gz` |
| `routing.py` | Traffic-aware ambulance routing, with and without a green corridor |
| `static/ambulances.js` | The simulated ambulances on the map |
| `data/roads.json.gz` | The road network used for routing (already included, 1 MB) |
| `static/index.html` | The map + charts (Leaflet and Chart.js, loaded from a CDN) |
| `static/hospitals.json` | Hospital names, locations, emergency flag and phone (already included) |
| `static/signals.json` | Traffic signal locations (already included) |

**Congestion** = `1 - current_speed / free_flow_speed`. 0% means the road is clear,
close to 100% means it's jammed. It's calculated when data is read, not stored.

## Setup

Run these in a terminal, one at a time.

```bash
git clone https://github.com/Pratyush1427/green-corridor.git
cd green-corridor
```
Download the project (skip `git clone` if you already have it) and move into its folder.

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
cp .env.example .env
```
Copy the example settings file. Then open `.env` and paste your TomTom key after
`TOMTOM_API_KEY=`. Get a free key at [developer.tomtom.com](https://developer.tomtom.com)
(free tier: 2,500 requests/day; 19 junctions every 15 minutes uses about 1,824/day).
`.env` is listed in `.gitignore`, so your key never gets committed.

## Try it without an API key (fake data)

```bash
python collector.py --fake --backfill-days 7
```
Fills the database with 7 days of realistic fake data (rush hours around 9–11am and 6–9pm,
lighter weekends), so the charts have something to show.

```bash
uvicorn app:app --reload
```
Start the web server. `--reload` restarts it automatically when you edit code.
Open <http://127.0.0.1:8000> and click a junction. Press `Ctrl+C` to stop the server.

On the map:
- **Live (latest)** colours each junction by its most recent reading. At night that's mostly green,
  which is correct.
- **Typical by hour** colours junctions by their average congestion at the hour on the slider.
  Press ▶ to watch the whole day play out.
- Shortcut links: <http://127.0.0.1:8000/?hour=19> opens at 7pm, and
  `?hour=9&junction=silk_board` also selects Silk Board. Add `&zoom=15` to zoom in on it.
- **Traffic signals** appear once you zoom in (they'd clutter the city-wide view).

Check the API directly (in a second terminal):
```bash
curl http://127.0.0.1:8000/api/junctions
curl http://127.0.0.1:8000/api/patterns/silk_board
curl "http://127.0.0.1:8000/api/patterns/silk_board?weekday=0"   # Mondays only (0=Mon … 6=Sun)
curl "http://127.0.0.1:8000/api/typical?hour=19"                 # every junction at 7pm
curl -X POST http://127.0.0.1:8000/api/route -H "Content-Type: application/json" \
     -d '{"start": [12.93, 77.62], "hour": 19}'                   # plan an ambulance trip
```
Interactive API docs are at <http://127.0.0.1:8000/docs>.

To start over with an empty database, delete it: `rm traffic.db`
(do this before collecting real data so fake readings don't mix into your patterns).

## Collect real data

```bash
python collector.py --once
```
Poll TomTom one time. It should print `Stored 6/6 readings`. Check the speeds look plausible
on the map.

```bash
python collector.py
```
Poll forever, every 15 minutes. Leave this terminal open (or run it in the background, below).
The patterns get more useful after a week or two of data.

To keep it running after you close the terminal:
```bash
nohup python collector.py > collector.log 2>&1 &
```
- `nohup` keeps it alive after the terminal closes, `&` runs it in the background
- output goes to `collector.log` (see it with `tail -f collector.log`)
- stop it later with `pkill -f collector.py`

Your Mac must stay awake for polling to continue. `caffeinate -i python collector.py` prevents
sleep while it runs.

## Useful checks

```bash
sqlite3 traffic.db "select count(*) from readings"
sqlite3 traffic.db "select * from readings order by id desc limit 6"
```

## Hospitals

`static/hospitals.json` is already included. To refresh it from OpenStreetMap:
```bash
python fetch_hospitals.py
```
The public server is often busy, so the script retries a few times. Hospital data is
© OpenStreetMap contributors (ODbL). Only hospitals tagged `emergency=yes` count as
emergency hospitals, and many real emergency hospitals aren't tagged yet. You can fix that
by editing OpenStreetMap, or by setting `"emergency": true` in the JSON file.

## Traffic signals

`static/signals.json` is already included. To refresh it from OpenStreetMap:
```bash
python fetch_signals.py
```
OpenStreetMap often maps one signal per approach road, so the script merges points within
40 m into one signal per junction (1,384 points become 611 signals).

The **locations are real, the colours are simulated**: each signal runs a 90-second cycle
(40s green, 4s amber, 46s red) with its own offset. The cycle is set by `CYCLE_S`,
`GREEN_S` and `AMBER_S` in `static/index.html`. This is where the green-corridor
controller will plug in: overriding a signal to green when an ambulance approaches.

## Simulated ambulances

1. Click **＋ Drop ambulance**, then click anywhere on the map.
2. The ambulance picks the **fastest emergency hospital** (by travel time, not distance) and
   drives there. Use its dropdown to send it to a specific hospital instead.
3. Signals on its route turn **green 45 seconds before it arrives** and go back to normal
   after it passes. On the map: route signals are red (not yet), green (held for the
   ambulance) or grey (passed).
4. **Drag** an ambulance to move it; it re-plans from the new spot. Drop as many as you like.
5. The **Speed** dropdown speeds up the simulation (10× by default).

Each ambulance shows its trip time with the corridor, the time the same trip would take in
normal traffic (the dashed grey line is the route a normal driver would pick), and the
difference. In "Typical by hour" mode, routes use the traffic at the slider's hour; otherwise
the current hour.

Shortcut link for demos: <http://127.0.0.1:8000/?hour=19&amb=12.945,77.61&amb=13.02,77.60>
drops two ambulances at 7pm traffic.

### How routing works (and its limits)

- The road network is Bengaluru's **main roads** only (motorways down to tertiary roads), to
  keep it small. An ambulance dropped on a side street starts from the nearest main-road junction.
  One-way streets are respected.
- Each road's speed is its speed limit (or a typical speed for its road type), slowed by the
  typical congestion at the nearest monitored junction for that hour.
- **Normal traffic**: the ambulance moves at the congested speed and waits an average of
  ~12 s at each red signal.
- **Green corridor**: signals are green and traffic is cleared, so the ambulance feels only
  a third of the congestion.

These are **simple, made-up assumptions**, set as constants at the top of `routing.py`, not a
validated traffic model. They're a starting point for experiments. A more realistic
comparison would use a traffic simulator such as [SUMO](https://eclipse.dev/sumo/).

To refresh the road data: `python fetch_roads.py` (large download; the script retries if the
server is busy).

## Adding junctions

Add an entry to `JUNCTIONS` in `config.py` with a unique `id`, a `name`, and `lat`/`lon`.
Entries marked "(approx)" have rough coordinates, so check those on the map: TomTom snaps to the nearest road
segment, so a point on the main road through the junction gives the best results.
Keep an eye on the budget: each junction costs 96 requests/day at a 15-minute interval,
so about 26 junctions is the maximum on the free tier.

## Saving your work with git

```bash
git add .
git commit -m "Initial traffic tracker template"
```
`git add .` stages every changed file (except those in `.gitignore`); `git commit` saves a
snapshot with a message. `git status` shows what's changed, `git log --oneline` shows history.

## Future hooks (not built yet)

- `POST /api/ambulance/location`: receives GPS positions from a real driver app, replacing
  the simulated ambulances
- Direction-aware corridors: today a held signal is simply "green"; real junctions need green
  only for the ambulance's approach, and a rule for two ambulances meeting at one junction
- Alerts to traffic police at each junction on the route ("ambulance arriving in 90 s")
