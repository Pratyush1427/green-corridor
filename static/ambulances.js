// Simulated ambulances. Dropping one triggers an emergency on the server (/api/emergencies),
// which plans the route and asks traffic police for clearance (see /police). The ambulance
// sets off at once in normal traffic; if police approve, the approved signals are held green
// by the server and the ambulance moves at corridor speed. It reports its GPS position like
// a real phone app would. Loaded after index.html's main script and uses its globals.

(() => {
  const TICK_MS = 100;
  const GPS_EVERY_MS = 1000;

  const ambulances = new Map();  // local id -> ambulance
  let nextId = 1;
  let dropping = false;

  const fmt = (s) => {
    s = Math.max(0, Math.round(s));
    return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
  };
  const speedFactor = () => Number($('amb-speed').value);
  const post = (url, body) => fetch(url, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  });

  // ---------- dropping ----------
  function setDropping(on) {
    dropping = on;
    $('amb-drop').classList.toggle('armed', on);
    $('amb-drop').textContent = on ? 'Click the map… (Esc)' : '＋ Add ambulance';
    map.getContainer().classList.toggle('dropping', on);
  }
  $('amb-drop').addEventListener('click', () => setDropping(!dropping));
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') setDropping(false); });
  map.on('click', (e) => {
    if (!dropping) return;
    setDropping(false);
    addAmbulance(e.latlng.lat, e.latlng.lng);
  });

  // ---------- lifecycle ----------
  function addAmbulance(lat, lon, hospital = null) {
    const id = nextId++;
    const amb = { id, label: 'A' + id, hospital, emergency: null, route: null, status: 'routing', error: null,
                  layer: L.layerGroup().addTo(map) };
    amb.marker = L.marker([lat, lon], { icon: ambIcon(amb), draggable: true, zIndexOffset: 3000 })
      .addTo(amb.layer)
      .on('dragstart', () => { amb.status = 'dragging'; closeEmergency(amb, 'cancelled'); refreshItem(amb); })
      .on('dragend', () => { const p = amb.marker.getLatLng(); trigger(amb, p.lat, p.lng); });
    amb.marker.bindTooltip(() => tooltip(amb), { direction: 'top', offset: [0, -16] });
    ambulances.set(id, amb);
    renderList();
    trigger(amb, lat, lon);
    return amb;
  }

  function removeAmbulance(amb) {
    closeEmergency(amb, 'cancelled');
    amb.layer.remove();
    ambulances.delete(amb.id);
    renderList();
  }

  function closeEmergency(amb, status) {
    if (amb.emergency && amb.emergency.status === 'active') {
      post(`/api/emergencies/${amb.emergency.id}/close`, { status }).catch(() => {});
      amb.emergency.status = status;
    }
  }

  // Trigger (or re-trigger, after a drag or destination change) an emergency on the server.
  async function trigger(amb, lat, lon) {
    closeEmergency(amb, 'cancelled');
    Object.assign(amb, { status: 'routing', error: null, route: null, emergency: null });
    clearRoute(amb);
    refreshItem(amb);
    const body = { ambulance: amb.label, start: [lat, lon], hospital: amb.hospital };
    if (mode === 'typical') body.hour = Number($('hour').value);
    try {
      const resp = await post('/api/emergencies', body);
      const data = await resp.json();
      if (!resp.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Could not plan a route');
      if (!ambulances.has(amb.id)) {  // removed while waiting
        post(`/api/emergencies/${data.id}/close`, { status: 'cancelled' });
        return;
      }
      Object.assign(amb, { emergency: data, route: data.route, status: 'driving',
                           d: 0, elapsed: 0, wait: 0, waited: new Set(), lastGps: 0 });
      drawRoute(amb);
      if (amb.demo) playDemoPolice(amb);
    } catch (e) {
      Object.assign(amb, { status: 'error', error: e.message });
    }
    amb.marker.setIcon(ambIcon(amb));
    renderList();
  }

  // ---------- clearance helpers ----------
  const clearanceOn = (amb) => ['approved', 'partial'].includes(amb.emergency?.clearance.status);
  const isCleared = (amb, sid) => clearanceOn(amb) && amb.emergency.clearance.cleared_signals.includes(sid);
  const isHeld = (amb, sid) => corridorHolds.get(sid)?.has(amb.emergency?.id);
  const nextSignal = (amb) => amb.route.signals.find(s => s.along_m > amb.d);

  function clearanceText(amb) {
    const c = amb.emergency.clearance, total = amb.route.signals.length;
    switch (c.status) {
      case 'pending': return `🚓 Waiting for traffic police (${c.expires_in_s}s)`;
      case 'approved': return `🚓 Police cleared all ${total} junctions`;
      case 'partial': return `🚓 Police cleared ${c.cleared_signals.length}/${total} junctions`;
      case 'declined': return `🚓 Police: not possible${c.note ? ' (' + c.note + ')' : ''}`;
      case 'expired': return '🚓 No police response: driving in normal traffic';
      default: return '';
    }
  }

  // ---------- drawing ----------
  function ambIcon(amb) {
    const cls = amb.status === 'error' ? 'amb err' : amb.status === 'arrived' ? 'amb done' : 'amb';
    return L.divIcon({ className: '', iconSize: [30, 30], html: `<div class="${cls}">🚑<span>${amb.label}</span></div>` });
  }

  function clearRoute(amb) {
    amb.layer.eachLayer(l => { if (l !== amb.marker) amb.layer.removeLayer(l); });
  }

  function drawRoute(amb) {
    const r = amb.route;
    clearRoute(amb);
    if (JSON.stringify(r.normal.coords) !== JSON.stringify(r.coords)) {
      L.polyline(r.normal.coords, { color: css('--muted'), weight: 2, dashArray: '4 6', opacity: 0.7, interactive: false })
        .addTo(amb.layer);
    }
    amb.done = L.polyline([], { color: css('--corridor'), weight: 4, opacity: 0.25, interactive: false }).addTo(amb.layer);
    amb.ahead = L.polyline(r.coords, { color: css('--corridor'), weight: 5, opacity: 0.95, className: 'route-line', interactive: false })
      .addTo(amb.layer);
    L.marker([r.hospital.lat, r.hospital.lon], {
      icon: L.divIcon({ className: '', iconSize: [26, 26], html: '<div class="dest"></div>' }), interactive: false,
    }).addTo(amb.layer);
    amb.signalMarkers = r.signals.map(s =>
      L.circleMarker([s.lat, s.lon], { radius: 6, weight: 2, color: '#fff', fillColor: css('--amber'), fillOpacity: 1 })
        .bindTooltip(() => signalTip(amb, s)).addTo(amb.layer));
    amb.marker.setLatLng(r.coords[0]);
  }

  function signalState(amb, s) {
    if (s.along_m <= amb.d) return 'passed';
    if (isHeld(amb, s.id)) return 'held';
    if (isCleared(amb, s.id)) return 'cleared';
    if (amb.emergency.clearance.status === 'pending') return 'pending';
    return 'declined';
  }

  const SIGNAL_STYLE = {
    passed:   () => ({ radius: 5, color: '#fff', fillColor: css('--grey'), opacity: 0.4, fillOpacity: 0.4 }),
    held:     () => ({ radius: 8, color: '#fff', fillColor: css('--green'), opacity: 1, fillOpacity: 1 }),
    cleared:  () => ({ radius: 6, color: css('--green'), fillColor: '#050b16', opacity: 1, fillOpacity: 1 }),
    pending:  () => ({ radius: 6, color: '#fff', fillColor: css('--amber'), opacity: 1, fillOpacity: 1 }),
    declined: () => ({ radius: 6, color: '#050b16', fillColor: css('--red'), opacity: 1, fillOpacity: 1 }),
  };

  function signalTip(amb, s) {
    const name = s.name ? escapeHtml(s.name) : 'Signal';
    return `<b>${name}</b><br>` + {
      passed: `${amb.label} has passed`,
      held: `Held green for ${amb.label}`,
      cleared: 'Police approved: turns green shortly before the ambulance arrives',
      pending: 'Waiting for traffic police',
      declined: 'Not cleared: the ambulance may have to stop here',
    }[signalState(amb, s)];
  }

  function tooltip(amb) {
    if (amb.status === 'error') return `${amb.label}: ${escapeHtml(amb.error)}`;
    if (!amb.route) return `${amb.label}: planning route…`;
    const dest = escapeHtml(amb.route.hospital.name);
    if (amb.status === 'arrived') return `${amb.label} arrived at ${dest}`;
    return `${amb.label} → ${dest}<br>${amb.wait > 0 ? 'Stopped at a red signal' : 'ETA ' + fmt(remainingS(amb))}`;
  }

  // ---------- simulation ----------
  const segIndex = (along, d) => {  // k such that along[k] <= d < along[k+1]
    let lo = 0, hi = along.length - 1;
    while (hi - lo > 1) { const mid = (lo + hi) >> 1; if (along[mid] <= d) lo = mid; else hi = mid; }
    return lo;
  };
  const interp = (arr, along, d) => {
    const k = segIndex(along, d);
    if (k >= along.length - 1) return arr[arr.length - 1];
    const f = (d - along[k]) / (along[k + 1] - along[k] || 1);
    return arr[k] + f * (arr[k + 1] - arr[k]);
  };

  // Moves the ambulance forward by dt simulated seconds. It drives at corridor speed while the
  // next signal ahead is cleared by police, otherwise at normal speed, and stops at uncleared
  // signals for the average red-light wait.
  function advance(amb, dt) {
    const r = amb.route, total = r.along[r.along.length - 1];
    for (let guard = 0; dt > 1e-6 && amb.d < total && guard < 1000; guard++) {
      if (amb.wait > 0) {
        const w = Math.min(amb.wait, dt);
        amb.wait -= w; dt -= w; amb.elapsed += w;
        continue;
      }
      const k = segIndex(r.along, amb.d);
      const next = nextSignal(amb);
      const fast = clearanceOn(amb) && (!next || isCleared(amb, next.id));
      const times = fast ? r.times : r.times_normal;
      const segT = times[k + 1] - times[k], segL = r.along[k + 1] - r.along[k];
      const v = segT > 0 ? segL / segT : 50;  // m/s
      let target = r.along[k + 1];
      const stopHere = next && next.along_m <= target && !isCleared(amb, next.id) && !amb.waited.has(next.id);
      if (stopHere) target = next.along_m;
      const need = (target - amb.d) / v;
      if (need <= dt) {
        amb.d = target; dt -= need; amb.elapsed += need;
        if (stopHere) { amb.waited.add(next.id); amb.wait = r.red_wait_s; amb.d += 0.01; }
      } else {
        amb.d += v * dt; amb.elapsed += dt; dt = 0;
      }
    }
    return amb.d >= total;
  }

  function positionAt(r, d) {
    const k = segIndex(r.along, d);
    if (k >= r.along.length - 1) return { k, point: r.coords[r.coords.length - 1] };
    const f = Math.min(1, (d - r.along[k]) / (r.along[k + 1] - r.along[k] || 1));
    const [a, b] = [r.coords[k], r.coords[k + 1]];
    return { k, point: [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f] };
  }

  // Rough time left: corridor or normal pace, plus a red-light wait for each uncleared signal ahead.
  function remainingS(amb) {
    const r = amb.route, times = clearanceOn(amb) ? r.times : r.times_normal;
    const ahead = r.signals.filter(s => s.along_m > amb.d && !isCleared(amb, s.id)).length;
    return times[times.length - 1] - interp(times, r.along, amb.d) + ahead * r.red_wait_s + amb.wait;
  }

  function tick() {
    const dt = TICK_MS / 1000 * speedFactor();
    const now = Date.now();
    for (const amb of ambulances.values()) {
      if (amb.status !== 'driving') continue;
      const r = amb.route;
      const arrived = advance(amb, dt);
      const { k, point } = positionAt(r, amb.d);
      amb.marker.setLatLng(point);
      amb.done.setLatLngs([...r.coords.slice(0, k + 1), point]);
      amb.ahead.setLatLngs([point, ...r.coords.slice(k + 1)]);
      r.signals.forEach((s, i) => amb.signalMarkers[i].setStyle(SIGNAL_STYLE[signalState(amb, s)]()).bringToFront());

      if (arrived || now - amb.lastGps >= GPS_EVERY_MS) {
        amb.lastGps = now;
        sendGps(amb, point, arrived);
      }
      if (arrived) {
        amb.status = 'arrived';
        amb.marker.setIcon(ambIcon(amb));
        renderList();
      }
      refreshItem(amb);
    }
    updateSummary();
  }
  setInterval(tick, TICK_MS);

  // Report position like a phone app would; the reply carries the latest police decision.
  async function sendGps(amb, point, arrived) {
    const e = amb.emergency;
    try {
      const resp = await post(`/api/emergencies/${e.id}/location`, { lat: point[0], lon: point[1] });
      if (resp.ok && amb.emergency?.id === e.id) amb.emergency = await resp.json();
      if (arrived) {
        const done = await post(`/api/emergencies/${e.id}/close`, { status: 'arrived' });
        if (done.ok && amb.emergency?.id === e.id) amb.emergency = await done.json();
      }
    } catch (err) { /* offline for a moment; the next update will retry */ }
  }

  // Which signals the server is holding green right now (for all ambulances).
  async function pollHolds() {
    try {
      const holds = await (await fetch('/api/signals/holds')).json();
      corridorHolds.clear();
      for (const h of holds) {
        if (!corridorHolds.has(h.signal_id)) corridorHolds.set(h.signal_id, new Set());
        corridorHolds.get(h.signal_id).add(h.emergency_id);
      }
      updateSignals();
    } catch (err) { /* server restarting */ }
  }
  setInterval(pollHolds, 1000);

  // Cancel this page's emergencies if the tab closes, so police don't see ghost requests.
  window.addEventListener('pagehide', () => {
    for (const amb of ambulances.values()) {
      if (amb.emergency?.status === 'active') {
        navigator.sendBeacon(`/api/emergencies/${amb.emergency.id}/close`,
          new Blob([JSON.stringify({ status: 'cancelled' })], { type: 'application/json' }));
      }
    }
  });

  // ---------- side panel ----------
  function renderList() {
    $('amb-hint').hidden = ambulances.size > 0;
    $('amb-list').innerHTML = [...ambulances.values()].map(amb => `
      <div class="amb-item" id="amb-${amb.id}">
        <div class="amb-head">
          <span class="amb-tag">${amb.label}</span>
          <b data-f="dest"></b>
          <button data-act="remove" title="Remove ambulance">×</button>
        </div>
        <select data-act="dest">${destinationOptions(amb)}</select>
        <div data-f="police" class="amb-police"></div>
        <div data-f="stats" class="muted"></div>
        <div data-f="saved" class="amb-saved"></div>
        <div class="bar"><div data-f="bar"></div></div>
      </div>`).join('');
    for (const amb of ambulances.values()) {
      const el = $('amb-' + amb.id);
      el.querySelector('[data-act=remove]').addEventListener('click', () => removeAmbulance(amb));
      el.querySelector('[data-act=dest]').addEventListener('change', (e) => {
        amb.hospital = e.target.value ? JSON.parse(e.target.value) : null;
        const p = amb.marker.getLatLng();
        trigger(amb, p.lat, p.lng);
      });
      refreshItem(amb);
    }
    updateSummary();
  }

  function destinationOptions(amb) {
    const here = amb.marker.getLatLng();
    const er = hospitals.filter(h => h.emergency)
      .map(h => ({ ...h, d: km({ lat: here.lat, lon: here.lng }, h) }))
      .sort((a, b) => a.d - b.d);
    const current = amb.hospital ? JSON.stringify(amb.hospital) : '';
    return `<option value="">Auto: fastest emergency hospital</option>` + er.map(h => {
      const v = JSON.stringify([h.lat, h.lon]);
      return `<option value='${v}' ${v === current ? 'selected' : ''}>${escapeHtml(h.name)} (${h.d.toFixed(1)} km)</option>`;
    }).join('');
  }

  function refreshItem(amb) {
    const el = $('amb-' + amb.id);
    if (!el) return;
    const f = (name) => el.querySelector(`[data-f=${name}]`);
    const r = amb.route;
    if (amb.status === 'error') {
      f('dest').textContent = 'No route';
      f('police').textContent = '';
      f('stats').innerHTML = `<span class="amb-err">${escapeHtml(amb.error)}</span> Drag the ambulance to try another spot.`;
      f('saved').textContent = '';
      f('bar').style.width = '0';
      return;
    }
    if (!r) {
      f('dest').textContent = amb.status === 'dragging' ? 'Moving…' : 'Planning route…';
      for (const k of ['police', 'stats', 'saved']) f(k).textContent = '';
      f('bar').style.width = '0';
      return;
    }
    const total = r.along[r.along.length - 1];
    f('dest').textContent = '→ ' + r.hospital.name;
    f('police').textContent = clearanceText(amb);
    f('police').dataset.state = amb.emergency.clearance.status;
    const traffic = `traffic at ${String(r.hour).padStart(2, '0')}:00`;
    if (amb.status === 'arrived') {
      f('stats').textContent = `Arrived in ${fmt(amb.elapsed)} · ${(r.distance_m / 1000).toFixed(1)} km · ` +
        `${amb.waited.size} red-light stop${amb.waited.size === 1 ? '' : 's'} · ${traffic}`;
      const saved = r.normal.eta_s - amb.elapsed;
      f('saved').textContent = saved > 5
        ? `~${fmt(saved)} faster than normal traffic (${fmt(r.normal.eta_s)})`
        : `About the same as normal traffic (${fmt(r.normal.eta_s)})`;
    } else {
      const passed = r.signals.filter(s => s.along_m <= amb.d).length;
      const held = r.signals.filter(s => isHeld(amb, s.id)).length;
      f('stats').textContent = (amb.wait > 0 ? 'Stopped at a red signal · ' : '') +
        `ETA ${fmt(remainingS(amb))} · ${((total - amb.d) / 1000).toFixed(1)} km left · ` +
        `signals ${passed}/${r.signals.length} · ${held} held green · ${traffic}`;
      f('saved').textContent = `With full clearance ${fmt(r.eta_s)} · normal traffic ${fmt(r.normal.eta_s)}`;
    }
    f('bar').style.width = (100 * Math.min(1, amb.d / total)).toFixed(1) + '%';
  }

  function updateSummary() {
    const driving = [...ambulances.values()].filter(a => a.status === 'driving').length;
    $('amb-summary').textContent = ambulances.size
      ? `· ${driving} driving · ${corridorHolds.size} signal${corridorHolds.size === 1 ? '' : 's'} green`
      : '';
  }

  // ---------- one-click demo ----------
  // Three ambulances in 7pm traffic. The page plays the traffic police too: one route is cleared,
  // one partly cleared (road works at one junction) and one declined, so all outcomes are visible.
  const DEMO = [
    { at: [12.955, 77.585], decision: 'approved' },
    { at: [12.975, 77.600], decision: 'partial', note: 'Road works at one junction' },
    { at: [12.945, 77.610], decision: 'declined', note: 'VIP movement on this route' },
  ];

  window.runDemo = async () => {
    for (const amb of [...ambulances.values()]) removeAmbulance(amb);
    $('hour').value = 19;
    setMode('typical');
    $('amb-speed').value = 5;
    toast('Demo: three ambulances in 7pm rush-hour traffic. The control room answers in a moment.');
    const demoAmbs = DEMO.map(d => {
      const amb = addAmbulance(d.at[0], d.at[1]);
      amb.demo = d;
      return amb;
    });
    // Zoom to the demo routes once they're planned.
    const waitForRoutes = setInterval(() => {
      if (demoAmbs.some(a => a.status === 'routing')) return;
      clearInterval(waitForRoutes);
      const pts = demoAmbs.filter(a => a.route).flatMap(a => a.route.coords);
      if (pts.length) map.fitBounds(L.latLngBounds(pts).pad(0.25));
    }, 200);
  };

  function playDemoPolice(amb) {
    const d = amb.demo, e = amb.emergency;
    setTimeout(async () => {
      if (amb.emergency?.id !== e.id || amb.emergency.status !== 'active') return;
      const signals = amb.route.signals;
      const declined = d.decision === 'partial' && signals.length > 1 ? [signals[1].id] : [];
      const decision = d.decision === 'partial' && !declined.length ? 'approved' : d.decision;
      const resp = await post(`/api/emergencies/${e.id}/clearance`, {
        decision, declined_signals: declined, officer: 'Demo control room', note: d.note || null,
      });
      if (!resp.ok || amb.emergency?.id !== e.id) return;
      amb.emergency = await resp.json();
      const msg = {
        approved: `🚓 Police cleared ${amb.label}'s route: signals ahead will turn green`,
        partial: `🚓 Police cleared ${amb.label}'s route except one junction (${d.note})`,
        declined: `🚓 Police: not possible for ${amb.label} (${d.note}). It continues in normal traffic`,
      }[decision];
      toast(msg, decision === 'declined' ? 'bad' : 'good');
      refreshItem(amb);
    }, 2500 + 1200 * (amb.id % 3));
  }

  // Deep links for demos: /?demo=1 runs the demo; /?amb=12.93,77.62&amb=13.02,77.58 drops ambulances.
  const urlParams = new URLSearchParams(location.search);
  if (urlParams.get('speed')) $('amb-speed').value = urlParams.get('speed');
  for (const value of urlParams.getAll('amb')) {
    const [lat, lon] = value.split(',').map(Number);
    if (Number.isFinite(lat) && Number.isFinite(lon)) addAmbulance(lat, lon);
  }
  if (urlParams.get('demo')) {
    window.runDemo();
  } else if (!urlParams.toString()) {
    // First visit: show the short welcome guide.
    let seen = false;
    try { seen = localStorage.getItem('gc-welcome-seen') === '1'; localStorage.setItem('gc-welcome-seen', '1'); } catch (e) {}
    if (!seen) showWelcome(true);
  }
})();
