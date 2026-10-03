# Hackathon pitch run-sheet

Everything you need to present Green Corridor in 3 minutes (or 5).

## Before you go on stage

- [ ] Laptop charged, charger in the bag.
- [ ] **Internet:** the map tiles and map library load from the web. Venue Wi-Fi is often
      overloaded, so use a **phone hotspot** as backup.
- [ ] Start the app: `./run.sh`
- [ ] **Close every other tab of the app** (organisation view, control room, driver, junction).
      All tabs share one live simulation, so a stray click in another tab (a cancel, an
      approval, a new accident) changes your demo. Keep only `/pitch` open.
- [ ] Open **<http://127.0.0.1:8000/pitch>**, go full screen (**F11**, or ⌃⌘F on a Mac), and
      set browser zoom so the whole layout fits the projector (usually 90–100%).
- [ ] The presenter view opens on an **intro card** with your hook. Leave it on screen while you
      introduce yourself; start the demo from there.
- [ ] **Clicker / keyboard:** → , PageDown or Space = next step (starts the story from the intro),
      **A** = auto on/off, **R** = restart, **F** = full screen. Most presentation clickers send
      → / PageDown, so a clicker works out of the box.
- [ ] Run the story once to warm up (**▶ Play the story**, let it finish). The first run loads the map tiles
      into the browser cache, which makes the real run smoother.
- [ ] Decide: **▶ Play the story** (Auto on: it plays by itself, ~2¼ minutes) or **Step through
      it myself** (Auto off: you press **Next ▶** / → when you've finished each point). Off is safer if the judges interrupt, and it
      lets you **tap the buttons yourself**, which lands better with judges:
      - step 3: **Clear all junctions** in the control room panel
      - step 4: **✅ Clearing** on the junction officer's phone (it lights up amber when it's time)
      - step 6: **Clear all junctions** again for the hospital leg

      Each tap moves the story on by itself; press **Next ▶** for the talking points in between.
- [ ] **Backup:** if the demo fails on stage, show `docs/screenshots/demo.gif` and the
      screenshots in the README. Better still, screen-record one full run of `/pitch` beforehand.
- [ ] Optional wow moment: open `/driver` on your phone (`HOST=0.0.0.0 ./run.sh`, same Wi-Fi)
      and hold it up while the story runs.

## The 3-minute pitch

### 0:00–0:30 · The problem (no slides needed, just say it)

> "Every minute an ambulance loses in traffic matters to the patient inside. In Bengaluru,
> clearing a road for an ambulance is still done by hand: someone phones the police, and
> officers at each junction wave traffic through, *if* they hear about it in time.
> We built a system that tells every junction on the route, in advance, and turns the
> signals green just before the ambulance arrives."

Add **one sourced statistic** here if you have it (ambulance response times, deaths linked to
delays, Bengaluru traffic speeds). Only use numbers you can cite. Judges ask.

### 0:30–2:45 · Live demo (press ▶ Start)

The captions narrate; you add one line per step:

| Step | On screen | You say |
|---|---|---|
| 1 | Accident on Marathahalli bridge, 7 pm | "Rush hour on the Outer Ring Road. An accident is reported." |
| 2 | AMB-03 dispatched | "The system sends the ambulance that can get there **fastest in this traffic**, not the nearest one. It leaves immediately." |
| 3 | Control room panel lights up; you tap **Clear all junctions** | "The traffic control room sees the whole route and clears it in one tap, or only some junctions, or says no." |
| 4 | Officer's phone lights up: "1:23 away, from HAL Old Airport Road"; you tap **Clearing** | "The officer at the junction gets an alert with the **direction** the ambulance comes from, and taps Clearing. Watch the driver's screen turn green." |
| 5 | Ambulance reaches the scene | "Signals go green just before it arrives and back to normal after. Cross traffic is held only for seconds." |
| 6 | Patient on board, hospital leg; you tap **Clear all junctions** again | "Now it picks the emergency hospital it can reach fastest, and skips specialist clinics, and requests a second corridor." |
| 7 | Summary card | "In our simulation: under 15 minutes instead of about 44. A pilot would measure this on real trips." |

### 2:45–3:00 · The ask

> "Next: a pilot with one hospital and one traffic police division, junction alerts only, no
> signal hardware changes. We're looking for [mentors / a hospital partner / an introduction
> to the traffic police]."

### If you have 5 minutes, add

- **How it works (40 s):** Dijkstra routing over 16,500 real road junctions from OpenStreetMap,
  travel times from hourly congestion patterns, a server-side simulation so every screen on
  every device stays in sync, and a per-signal API (`hold_green` / `normal`) that real signal
  controllers could read.
- **Four screens, four users (20 s):** organisation, driver, junction officer, control room.
  Open `/driver` or `/junction` on your phone to show it's real.
- **Roadmap (20 s):** real GPS from phones, logins, a hospital arrival screen, a pilot.

## Judges' questions: honest answers

| Question | Answer |
|---|---|
| Is the traffic data real? | "The roads, 1,097 hospitals and 611 signal locations are real, from OpenStreetMap. Congestion is simulated for the demo; the collector for TomTom's live traffic API is built and ready to run." |
| Is the time saved real? | "No, it's from a simple model with stated assumptions. Measuring it on real trips is exactly what the pilot is for." |
| Can you control real traffic signals? | "Not yet; that needs the traffic police. That's why the pilot uses junction officers' phones first. The signal API is ready for when they integrate." |
| What if the police say no? | "The ambulance never waits. It drives in normal traffic, and the driver sees which junctions aren't cleared." |
| Couldn't someone fake an emergency? | "In production, only verified ambulances can trigger it, every step is logged, and the GPS must match the route. The demo has no login yet." |
| Why not just Google Maps? | "Google routes the ambulance but can't clear the road. Our value is coordination: control room, junction officers and signals." |
| Who pays? | "Hospitals, for dispatch, arrival alerts and analytics. The police side is free; public ambulances could be covered by government or CSR funding." |
| What about patient privacy? | "We store no patient data beyond 'patient on board'. Anything more would follow India's DPDP Act." |
| Where's the AI? | "Traffic-aware routing and choosing the fastest hospital today. Next: predicting congestion 30–60 minutes ahead from collected traffic data." |

## Things not to claim

- Don't present the time saved as measured or proven.
- Don't say it works with real signals, or that the traffic police are using it.
- Don't imply any partnership or endorsement you don't have (hospital, police, or your employer).

## One more thing

If you work somewhere with rules on outside projects (most tech employers have them), check that
presenting and entering competitions is fine, and read the hackathon's rules on who owns the IP,
**before** the event.
