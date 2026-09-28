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
- charts each junction's typical pattern by hour of day and weekday, and lists its
  nearest emergency hospitals

## Files

| File | What it does |
|---|---|
| `config.py` | The junction list (name + lat/lon) and settings like the poll interval |
| `db.py` | Creates the SQLite table and has helper functions to save/query readings |
| `collector.py` | Fetches traffic data from TomTom (or fakes it) and saves it |
| `app.py` | The web server: a small JSON API plus the map page |
| `fetch_hospitals.py` | Downloads Bengaluru hospitals from OpenStreetMap into `static/hospitals.json` |
| `static/index.html` | The map + charts (Leaflet and Chart.js, loaded from a CDN) |
| `static/hospitals.json` | Hospital names, locations, emergency flag and phone (already included) |

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
  `?hour=9&junction=silk_board` also selects Silk Board.

Check the API directly (in a second terminal):
```bash
curl http://127.0.0.1:8000/api/junctions
curl http://127.0.0.1:8000/api/patterns/silk_board
curl "http://127.0.0.1:8000/api/patterns/silk_board?weekday=0"   # Mondays only (0=Mon … 6=Sun)
curl "http://127.0.0.1:8000/api/typical?hour=19"                 # every junction at 7pm
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

- `POST /api/ambulance/location`: receives GPS positions from a driver app
- A simulated traffic signal controller that turns green when an ambulance is within ~200 m
- Using the stored patterns to predict the fastest route at a given time of day
