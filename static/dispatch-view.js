// Hospital / ambulance service screen (/dispatch): report accidents, follow every ambulance,
// manage the fleet, and look at traffic. Ambulances are simulated on the server (dispatch.py);
// this page shows the shared state and sends the organisation's actions.

(() => {
  const POLL_MS = 1000;
  topbar($('topbar'), 'Hospital & ambulance service');

  // ---------- map ----------
  const map = L.map('map', { zoomControl: true, maxZoom: 19 }).setView([12.975, 77.62], 12);
  addBaseMap(map);
  if (EMBED) {  // inside the presenter view: map only
    $('aside').remove();
    // the frame is narrow, so override the phone layout too: full-height map only
    Object.assign(document.querySelector('.layout').style, { gridTemplateColumns: '1fr', gridTemplateRows: '1fr', height: '100vh' });
    Object.assign(document.body.style, { gridTemplateRows: '1fr', overflow: 'hidden' });
    setTimeout(() => map.invalidateSize(), 50);
  } else {
    makeResizableSidebar(document.querySelector('.layout'), $('aside'), map, 'gc-side-dispatch', { side: 'left', min: 360, max: 640 });
  }

  let state = null;
  const ambMarkers = new Map();   // ambulance id -> marker
  const incLayers = new Map();    // incident id -> { group, legId, line, signals, dest, building }
  let focusId = null;             // incident the presenter view wants kept in view

  // ---------- tabs ----------
  let tab = 'emergencies';
  document.querySelectorAll('.tabs button').forEach(b => b.addEventListener('click', () => {
    tab = b.dataset.tab;
    document.querySelectorAll('.tabs button').forEach(x => x.classList.toggle('on', x === b));
    document.querySelectorAll('[data-pane]').forEach(p => { p.hidden = p.dataset.pane !== tab; });
    trafficLayer[tab === 'traffic' ? 'addTo' : 'remove'](map);
    if (tab === 'traffic') loadTraffic();
  }));

  // ---------- hospitals: only when zoomed in, to keep the city view clean ----------
  const hospitalLayer = L.layerGroup();
  let hospitals = [];
  fetch('/static/hospitals.json').then(r => r.json()).then(list => {
    hospitals = list.filter(h => h.emergency);
    const icon = L.divIcon({ className: '', iconSize: [18, 18], html: '<div class="hosp">H</div>' });
    for (const h of hospitals) L.marker([h.lat, h.lon], { icon }).bindTooltip(`🏥 ${escapeHtml(h.name)}`).addTo(hospitalLayer);
  });
  const showHospitals = () => { if (!EMBED) hospitalLayer[map.getZoom() >= 14 ? 'addTo' : 'remove'](map); };
  map.on('zoomend', showHospitals);

  // ---------- polling ----------
  async function poll() {
    try { state = await api('/api/state'); } catch (e) { return; }
    drawFleet();
    drawIncidents();
    if (!EMBED) { renderTrips(); renderFleet(); syncSpeed(); }
  }
  setInterval(poll, POLL_MS);

  window.addEventListener('message', (e) => {
    if (e.origin === location.origin && e.data?.focusIncident) { focusId = e.data.focusIncident; poll(); }
  });

  function drawFleet() {
    const ids = new Set();
    for (const a of state.fleet) {
      ids.add(a.id);
      const idle = a.status === 'available';
      let m = ambMarkers.get(a.id);
      if (!m) {
        m = L.marker([a.lat, a.lon], { icon: ambIcon(a.callsign, idle), zIndexOffset: 3000 }).addTo(map);
        m._idle = idle;
        ambMarkers.set(a.id, m);
      } else {
        glide(m, [a.lat, a.lon]);
        if (m._idle !== idle) { m.setIcon(ambIcon(a.callsign, idle)); m._idle = idle; }
      }
      if (EMBED) m.setOpacity(idle ? 0.35 : 1);
      m.bindTooltip(`<b>${escapeHtml(a.callsign)}</b> · ${idle ? 'Free, at ' + escapeHtml(a.base || 'base') : 'On a call'}`, { direction: 'top', offset: [0, -16] });
    }
    for (const [id, m] of ambMarkers) if (!ids.has(id)) { m.remove(); ambMarkers.delete(id); }
  }

  function drawIncidents() {
    const active = state.incidents.filter(i => i.status === 'active');
    for (const inc of active) {
      const leg = inc.current_leg;
      let lay = incLayers.get(inc.id);
      if (!lay) {
        lay = { group: L.layerGroup().addTo(map), legId: null, signals: [] };
        L.marker([inc.scene.lat, inc.scene.lon], { icon: sceneIcon(), zIndexOffset: 2000 })
          .bindTooltip(`<b>Accident</b><br>${escapeHtml(inc.description || '')}`).addTo(lay.group);
        incLayers.set(inc.id, lay);
      }
      if (leg && lay.legId !== leg.id && !lay.building) buildLeg(inc, leg, lay);
      if (leg && lay.legId === leg.id) styleLeg(leg, lay);
    }
    const ids = new Set(active.map(i => i.id));
    for (const [id, lay] of incLayers) if (!ids.has(id)) { lay.group.remove(); incLayers.delete(id); }
  }

  async function buildLeg(inc, leg, lay) {
    lay.building = true;
    try {
      const geo = await legGeometry(inc.id, leg.id);
      [lay.line, lay.casing, lay.dest, ...lay.signals].forEach(l => l?.remove());
      lay.casing = L.polyline(geo.coords, { color: '#fff', weight: 10, opacity: .9, interactive: false }).addTo(lay.group);
      lay.line = L.polyline(geo.coords, { weight: 6, opacity: 1, interactive: false }).addTo(lay.group);
      lay.dest = leg.kind === 'to_hospital'
        ? L.marker([leg.destination.lat, leg.destination.lon], { icon: destIcon() }).bindTooltip(`🏥 ${escapeHtml(leg.destination.name)}`).addTo(lay.group) : null;
      lay.signals = leg.signals.map(s => L.circleMarker([s.lat, s.lon], { radius: 7, weight: 3, color: '#fff', fillOpacity: 1 })
        .bindTooltip(() => signalTip(inc.id, s.id)).addTo(lay.group));
      lay.legId = leg.id;
      styleLeg(leg, lay);
      if (inc.id === focusId || lay.fitOnBuild) {
        lay.fitOnBuild = false;
        map.fitBounds(L.latLngBounds([...geo.coords, [inc.ambulance.lat, inc.ambulance.lon]]).pad(0.15));
      }
    } finally {
      lay.building = false;
    }
  }

  function styleLeg(leg, lay) {
    lay.line?.setStyle(routeStyle(leg.clearance.status));
    leg.signals.forEach((s, i) => lay.signals[i]?.setStyle({
      fillColor: signalColor(s.state), radius: s.state === 'held' ? 9 : 7,
      opacity: s.state === 'passed' ? .4 : 1, fillOpacity: s.state === 'passed' ? .4 : 1,
    }).bringToFront());
  }

  function signalTip(incId, sigId) {
    const inc = state.incidents.find(i => i.id === incId);
    const s = inc?.current_leg?.signals.find(x => x.id === sigId);
    if (!s) return '';
    const roads = [s.from_road, s.to_road].filter((x, i, a) => x && a.indexOf(x) === i).join(' → ');
    return `<b>🚦 ${escapeHtml(junctionName(s))}</b>${roads ? '<br>' + escapeHtml(roads) : ''}<br>${SIGNAL[s.state].text}` +
      (s.reason ? ` (${escapeHtml(s.reason)})` : '') + (s.eta_s != null && s.state !== 'passed' ? ` · ambulance in ${fmtMin(s.eta_s)} min` : '');
  }

  const showTrip = (id) => {
    const lay = incLayers.get(id);
    if (lay?.line) map.fitBounds(lay.line.getBounds().pad(0.2));
  };

  if (EMBED) { poll(); return; }   // nothing else is shown in the presenter view

  // ---------- reporting an accident (2 steps, with a check before sending) ----------
  const WHAT = ['Road accident', 'Fall or injury', 'Breathing or heart problem', 'Other emergency'];
  const report = { step: 'idle', point: null, preview: null, what: WHAT[0], ambulanceId: null, hospital: null, error: null, pin: null };
  let picking = null;  // 'accident' | 'ambulance' | null

  function setPicking(kind, text) {
    picking = kind;
    document.body.classList.toggle('picking', !!kind);
    $('banner').hidden = !kind;
    $('banner-text').textContent = text || '';
  }
  $('banner-cancel').addEventListener('click', () => { setPicking(null); if (report.step === 'pick') resetReport(); });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && picking) { setPicking(null); if (report.step === 'pick') resetReport(); } });

  function resetReport() {
    report.pin?.remove();
    Object.assign(report, { step: 'idle', point: null, preview: null, what: WHAT[0], ambulanceId: null, hospital: null, error: null, pin: null });
    setPicking(null);
    renderReport();
  }

  map.on('click', async (e) => {
    if (picking === 'accident') {
      setPicking(null);
      choosePlace([e.latlng.lat, e.latlng.lng]);
    } else if (picking === 'ambulance') {
      setPicking(null);
      try {
        const a = await api('/api/ambulances', { lat: e.latlng.lat, lon: e.latlng.lng });
        toast(`${a.callsign} added to your ambulances`, 'good');
        poll();
      } catch (err) { toast(err.message, 'bad'); }
    }
  });

  async function choosePlace(point) {
    report.point = point;
    report.step = 'confirm';
    report.preview = null; report.error = null;
    report.pin?.remove();
    report.pin = L.marker(point, { draggable: true, zIndexOffset: 4000,
      icon: L.divIcon({ className: '', iconSize: [34, 34], iconAnchor: [17, 32], html: '<div class="pin">📍</div>' }) })
      .bindTooltip('Accident here (drag to move)', { permanent: false }).addTo(map);
    report.pin.on('dragend', () => { const p = report.pin.getLatLng(); choosePlace([p.lat, p.lng]); });
    renderReport();
    try {
      report.preview = await api('/api/incidents/preview', { scene: point, ambulance_id: report.ambulanceId });
    } catch (err) {
      report.error = err.message;
    }
    renderReport();
  }

  function hospitalOptions() {
    const near = hospitals.map(h => ({ ...h, d: map.distance(report.point, [h.lat, h.lon]) / 1000 }))
      .sort((a, b) => a.d - b.d).slice(0, 15);
    return `<option value="">Automatic: best nearby hospital</option>` + near.map(h => {
      const v = JSON.stringify([h.lat, h.lon]);
      return `<option value='${v}' ${JSON.stringify(report.hospital) === v ? 'selected' : ''}>${escapeHtml(h.name)} · ${h.d.toFixed(1)} km</option>`;
    }).join('');
  }

  function renderReport() {
    const box = $('report');
    if (report.step === 'idle') {
      box.innerHTML = `<button class="btn primary huge" id="start-report">🚨 Report an accident</button>`;
      tip(box, 'dispatch-start', 'To send an ambulance: press <b>Report an accident</b>, then tap the place on the map. You will see which ambulance goes before you send it.');
      $('start-report').addEventListener('click', () => {
        report.step = 'pick';
        setPicking('accident', '👆 Tap where the accident is');
        renderReport();
      });
      return;
    }
    if (report.step === 'pick') {
      box.innerHTML = `<div class="card report-card"><div class="step">Step 1 of 2</div>
        <h2>Tap the accident place on the map</h2>
        <p class="muted" style="margin:6px 0 14px">Zoom in with + if you need to. You can still move it in the next step.</p>
        <button class="btn block" id="cancel-report">Cancel</button></div>`;
      $('cancel-report').addEventListener('click', resetReport);
      return;
    }
    // confirm
    const p = report.preview;
    let sendLine;
    if (report.error) {
      sendLine = `<div class="sendline" style="background:var(--red-bg)"><span class="big">⚠️</span><div><b style="color:var(--red)">${escapeHtml(report.error)}</b></div></div>`;
    } else if (!p) {
      sendLine = `<div class="sendline"><span class="big">⏳</span><div><b>Finding the fastest ambulance…</b></div></div>`;
    } else {
      sendLine = `<div class="sendline"><span class="big">🚑</span><div><b>${escapeHtml(p.ambulance.callsign)} will go</b>
        <span class="muted">from ${escapeHtml(p.ambulance.base || 'its base')} · reaches the accident in about <b style="display:inline;font-size:inherit">${fmtMin(p.eta_s)} min</b></span></div></div>`;
    }
    box.innerHTML = `<div class="card report-card stack"><div><div class="step">Step 2 of 2</div><h2>Check and send</h2></div>
      <div><label class="field">What happened?</label>
        <div class="chips">${WHAT.map(w => `<button data-what="${w}" class="${w === report.what ? 'on' : ''}">${w}</button>`).join('')}</div></div>
      ${sendLine}
      ${p ? `<div><label class="field" for="amb-choice">Ambulance</label><select id="amb-choice">
        <option value="">Fastest one (recommended)</option>${p.free.map(a => `<option value="${a.id}" ${a.id === report.ambulanceId ? 'selected' : ''}>${escapeHtml(a.callsign)}</option>`).join('')}
        </select></div>
      <div><label class="field" for="hosp-choice">Hospital</label><select id="hosp-choice">${hospitalOptions()}</select></div>` : ''}
      <button class="btn go huge" id="send" ${p && !report.error ? '' : 'disabled'}>${p ? `Send ${escapeHtml(p.ambulance.callsign)} now` : 'Send'}</button>
      <div class="row"><button class="btn small" id="move">📍 Choose another place</button><span class="grow"></span><button class="btn small" id="cancel-report">Cancel</button></div>
      <p class="muted small" style="margin:0">When you send, the traffic police are asked to clear the road straight away.</p></div>`;
    box.querySelectorAll('[data-what]').forEach(b => b.addEventListener('click', () => { report.what = b.dataset.what; renderReport(); }));
    $('amb-choice')?.addEventListener('change', (e) => { report.ambulanceId = e.target.value ? Number(e.target.value) : null; choosePlace(report.point); });
    $('hosp-choice')?.addEventListener('change', (e) => { report.hospital = e.target.value ? JSON.parse(e.target.value) : null; });
    $('move').addEventListener('click', () => { report.step = 'pick'; setPicking('accident', '👆 Tap where the accident is'); renderReport(); });
    $('cancel-report').addEventListener('click', resetReport);
    $('send').addEventListener('click', send);
  }

  async function send() {
    $('send').disabled = true;
    try {
      const inc = await api('/api/incidents', { scene: report.point, ambulance_id: report.ambulanceId, hospital: report.hospital, description: report.what });
      toast(`🚑 ${inc.ambulance.callsign} is on the way. The police have been asked to clear the road.`, 'good');
      resetReport();
      const lay = { group: L.layerGroup().addTo(map), legId: null, signals: [], fitOnBuild: true };
      L.marker([inc.scene.lat, inc.scene.lon], { icon: sceneIcon(), zIndexOffset: 2000 }).addTo(lay.group);
      incLayers.set(inc.id, lay);
      poll();
    } catch (err) {
      toast(err.message, 'bad');
      $('send').disabled = false;
    }
  }
  renderReport();

  // ---------- trips list ----------
  const cards = new Map();
  function renderTrips() {
    const active = state.incidents.filter(i => i.status === 'active');
    const finished = state.incidents.filter(i => i.status !== 'active').slice(0, 5);
    $('tab-count').hidden = !active.length;
    $('tab-count').textContent = active.length;
    $('active-title').hidden = !active.length;
    const box = $('active');
    for (const inc of active) {
      if (!cards.has(inc.id)) cards.set(inc.id, tripCard(inc));
      updateTrip(cards.get(inc.id), inc);
      box.appendChild(cards.get(inc.id));
    }
    const ids = new Set(active.map(i => i.id));
    for (const [id, el] of cards) if (!ids.has(id)) { el.remove(); cards.delete(id); }
    if (!active.length) box.innerHTML = '';
    $('finished-box').hidden = !finished.length;
    $('finished').innerHTML = finished.map(inc => {
      const total = inc.legs.reduce((t, l) => t + l.elapsed_s, 0);
      return `<div class="amb-row"><span style="font-size:22px">${inc.status === 'closed' ? '✅' : '✖️'}</span><div class="grow">
        <b>${escapeHtml(inc.ambulance.callsign)}</b><span>${inc.status === 'closed' ? `Patient reached hospital · ${fmtMin(total)} min in total` : 'Cancelled'}
        · ${escapeHtml(inc.description || '')}</span></div></div>`;
    }).join('');
  }

  function tripCard(inc) {
    const el = document.createElement('div');
    el.className = 'card trip';
    el.innerHTML = `
      <div class="trip-top"><span class="ic" data-f="icon"></span><div class="grow"><b data-f="title"></b><span data-f="sub"></span></div>
        <div class="eta-big" data-f="eta"></div></div>
      <div class="row" style="gap:8px"><span class="pill" data-f="police"></span></div>
      <div class="bar"><div data-f="bar"></div></div>
      <div class="meta"><span data-f="left"></span><span data-f="dest"></span></div>
      <div class="acts">
        <button class="btn small" data-act="show">🗺️ Show on map</button>
        <a class="btn small" href="/driver?amb=${inc.ambulance.id}" target="_blank">📱 Driver's screen</a>
        <button class="btn small stop" data-act="cancel" style="margin-left:auto">Cancel</button>
      </div>`;
    el.querySelector('[data-act=show]').addEventListener('click', () => showTrip(inc.id));
    el.querySelector('[data-act=cancel]').addEventListener('click', async () => {
      if (!confirm(`Cancel this trip? ${inc.ambulance.callsign} will become free again.`)) return;
      await api(`/api/incidents/${inc.id}/cancel`, {}).catch(err => toast(err.message, 'bad'));
      poll();
    });
    return el;
  }

  function updateTrip(el, inc) {
    const f = (n) => el.querySelector(`[data-f=${n}]`);
    const leg = inc.current_leg;
    const driving = inc.phase === 'to_scene' || inc.phase === 'to_hospital';
    f('icon').textContent = PHASE_ICON[inc.phase];
    f('title').textContent = `${inc.ambulance.callsign} · ${PHASE[inc.phase]}`;
    f('sub').textContent = inc.description || '';
    f('eta').innerHTML = driving ? `${fmtMin(leg.eta_s)} min` : inc.phase === 'at_scene' ? '<span class="pill info">Loading patient</span>' : '<span class="pill info">Handing over</span>';
    const pol = POLICE[leg?.clearance.status] || POLICE.pending;
    f('police').className = 'pill ' + pol.kind;
    f('police').textContent = driving ? `${pol.kind === 'ok' ? '✓' : pol.kind === 'wait' ? '⏳' : '✕'} ${pol.text} · ${leg.clearance.cleared} of ${leg.clearance.total} signals`
      : `${PHASE_ICON[inc.phase]} ${PHASE[inc.phase]}`;
    f('bar').style.width = (100 * (leg?.progress || 0)).toFixed(1) + '%';
    f('left').textContent = driving ? `${fmtKm(leg.left_m)} to go` : '';
    f('dest').textContent = leg?.kind === 'to_hospital' ? `🏥 ${leg.destination.name}` : '📍 To the accident';
  }

  // ---------- fleet ----------
  function renderFleet() {
    const free = state.fleet.filter(a => a.status === 'available').length;
    $('fleet-summary').textContent = `${free} of ${state.fleet.length} free right now`;
    $('fleet').innerHTML = state.fleet.map(a => {
      const inc = a.incident_id ? state.incidents.find(i => i.id === a.incident_id) : null;
      return `<div class="amb-row"><span class="dot ${a.status === 'available' ? 'ok' : 'wait'}"></span><div class="grow">
        <b>${escapeHtml(a.callsign)}</b><span>${a.status === 'available' ? 'Free · at ' + escapeHtml(a.base || 'base') : 'On a call · ' + (inc ? PHASE[inc.phase] : '')}</span></div>
        <a class="btn small" href="/driver?amb=${a.id}" target="_blank">📱 Driver's screen</a></div>`;
    }).join('');
  }
  $('add-amb').addEventListener('click', () => setPicking('ambulance', '👆 Tap where the new ambulance is parked'));

  // ---------- practice run & speed ----------
  $('demo').addEventListener('click', async () => {
    try {
      await api('/api/demo?hour=19', {});
      toast('Practice run started: three made-up accidents in evening traffic.', 'good');
      for (const lay of incLayers.values()) lay.group.remove();
      incLayers.clear();
      setTimeout(() => { poll().then(() => {
        const pts = state.incidents.filter(i => i.status === 'active').flatMap(i => [[i.scene.lat, i.scene.lon], [i.ambulance.lat, i.ambulance.lon]]);
        if (pts.length) map.fitBounds(L.latLngBounds(pts).pad(0.3));
      }); }, 300);
    } catch (err) { toast(err.message, 'bad'); }
  });
  function syncSpeed() {
    const sel = $('speed'), v = String(state.sim.speed);
    if (![...sel.options].some(o => o.value === v)) sel.add(new Option(`${v}× faster`, v));
    if (document.activeElement !== sel) sel.value = v;
  }
  $('speed').addEventListener('change', (e) => api('/api/sim', { speed: Number(e.target.value) }).catch(err => toast(err.message, 'bad')));

  // ---------- traffic ----------
  const trafficLayer = L.layerGroup();
  const jMarkers = {};
  let junctions = {}, shown = {}, tmode = 'live', chart = null, selectedJ = null, playing = null;
  const level = (c) => c == null ? 'info' : c < 0.3 ? 'ok' : c < 0.6 ? 'wait' : 'bad';
  const hourText = (h) => `${h % 12 || 12} ${h < 12 ? 'am' : 'pm'}`;
  const pct = (c) => c == null ? 'no data' : Math.round(c * 100) + '% slower than free-flowing';

  async function loadTraffic() {
    const list = await api('/api/junctions');
    junctions = Object.fromEntries(list.map(j => [j.id, j]));
    if (tmode === 'live') shown = Object.fromEntries(list.map(j => [j.id, j.latest?.congestion ?? null]));
    else {
      const wd = $('weekday').value;
      const rows = await api(`/api/typical?hour=${$('hour').value}` + (wd ? `&weekday=${wd}` : ''));
      shown = Object.fromEntries(rows.map(r => [r.junction_id, r.congestion]));
    }
    const times = list.filter(j => j.latest).map(j => j.latest.ts_utc).sort();
    $('data-note').textContent = times.length ? `Latest reading: ${new Date(times.at(-1).replace(' ', 'T') + 'Z').toLocaleString('en-IN', { timeZone: 'Asia/Kolkata', dateStyle: 'medium', timeStyle: 'short' })}.` : 'No traffic readings yet.';
    const counts = { ok: 0, wait: 0, bad: 0 };
    for (const j of list) {
      const c = shown[j.id] ?? null, lv = level(c);
      if (counts[lv] != null) counts[lv]++;
      const size = Math.round(16 + (c ?? 0) * 18);
      const icon = L.divIcon({ className: '', iconSize: [size, size],
        html: `<div class="jn" style="--c:${css(KIND_COLOR[lv])};width:${size}px;height:${size}px"></div>` });
      if (!jMarkers[j.id]) {
        jMarkers[j.id] = L.marker([j.lat, j.lon], { icon }).on('click', () => selectJunction(j.id)).addTo(trafficLayer);
      } else jMarkers[j.id].setIcon(icon);
      jMarkers[j.id].bindTooltip(`<b>${escapeHtml(j.name)}</b><br>${pct(c)}`);
    }
    $('n-jam').textContent = counts.bad; $('n-slow').textContent = counts.wait; $('n-clear').textContent = counts.ok;
    if (selectedJ) loadPattern();
  }

  async function selectJunction(id) {
    selectedJ = id;
    $('jdetail').hidden = false;
    loadPattern();
  }

  async function loadPattern() {
    const j = junctions[selectedJ];
    const wd = $('weekday').value;
    const data = await api(`/api/patterns/${selectedJ}` + (wd ? `?weekday=${wd}` : ''));
    $('j-name').textContent = j.name;
    $('j-sub').textContent = `Usual traffic through the day${wd ? ' on ' + $('weekday').selectedOptions[0].text + 's' : ''}. Higher = more jammed.`;
    const cfg = {
      type: 'line',
      data: { labels: data.hours.map(h => hourText(h.hour)),
        datasets: [{ data: data.hours.map(h => h.congestion == null ? null : Math.round(h.congestion * 100)), spanGaps: true, tension: .35,
          borderColor: css('--primary'), backgroundColor: 'rgba(23,103,216,.12)', fill: true, pointRadius: 0, borderWidth: 3 }] },
      options: { maintainAspectRatio: false, plugins: { legend: { display: false },
          tooltip: { callbacks: { label: (it) => `${it.formattedValue}% slower than free-flowing` } } },
        scales: { y: { min: 0, max: 100, ticks: { callback: (v) => v + '%', stepSize: 50 } }, x: { ticks: { maxTicksLimit: 6 } } } },
    };
    if (chart) chart.destroy();
    chart = new Chart($('chart'), cfg);
  }

  document.querySelectorAll('.seg button').forEach(b => b.addEventListener('click', () => {
    tmode = b.dataset.mode;
    document.querySelectorAll('.seg button').forEach(x => x.classList.toggle('on', x === b));
    $('typical-box').hidden = tmode !== 'typical';
    loadTraffic();
  }));
  $('hour').addEventListener('input', () => { $('hour-label').textContent = hourText(Number($('hour').value)); loadTraffic(); });
  $('weekday').addEventListener('change', loadTraffic);
  $('play').addEventListener('click', () => {
    if (playing) { clearInterval(playing); playing = null; $('play').textContent = '▶ Play the day'; return; }
    $('play').textContent = '⏸ Stop';
    playing = setInterval(() => { $('hour').value = (Number($('hour').value) + 1) % 24; $('hour').dispatchEvent(new Event('input')); }, 800);
  });
  setInterval(() => { if (tab === 'traffic' && tmode === 'live') loadTraffic(); }, 60000);

  // ---------- start ----------
  poll().then(() => {
    if (params.get('demo')) $('demo').click();
  });
})();
