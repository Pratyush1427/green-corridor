// Simulated ambulances: drop one on the map, it drives to a hospital along the route from
// /api/route, and the traffic signals ahead of it are held green (a "green corridor").
// Loaded after the main script in index.html and uses its globals (map, $, css, signals, ...).

(() => {
  const LEAD_S = 45;      // turn a signal green this many (simulated) seconds before arrival
  const RELEASE_S = 3;    // release it this long after the ambulance passes
  const TICK_MS = 100;

  const ambulances = new Map();  // id -> ambulance
  let nextId = 1;
  let dropping = false;

  const fmt = (s) => {
    s = Math.max(0, Math.round(s));
    return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
  };
  const speedFactor = () => Number($('amb-speed').value);

  // ---------- dropping ----------
  function setDropping(on) {
    dropping = on;
    $('amb-drop').classList.toggle('armed', on);
    $('amb-drop').textContent = on ? 'Click on the map… (Esc to cancel)' : '＋ Drop ambulance';
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
    const amb = {
      id, label: 'A' + id, hospital, route: null, simT: 0, status: 'routing', error: null,
      layer: L.layerGroup().addTo(map),
      held: new Set(),
    };
    amb.marker = L.marker([lat, lon], { icon: ambIcon(amb), draggable: true, zIndexOffset: 3000 })
      .addTo(amb.layer)
      .on('dragstart', () => { amb.status = 'dragging'; releaseAll(amb); })
      .on('dragend', () => { const p = amb.marker.getLatLng(); planRoute(amb, p.lat, p.lng); });
    amb.marker.bindTooltip(() => tooltip(amb), { direction: 'top', offset: [0, -16] });
    ambulances.set(id, amb);
    renderList();
    planRoute(amb, lat, lon);
    return amb;
  }

  function removeAmbulance(amb) {
    releaseAll(amb);
    amb.layer.remove();
    ambulances.delete(amb.id);
    renderList();
  }

  async function planRoute(amb, lat, lon) {
    amb.status = 'routing';
    amb.error = null;
    releaseAll(amb);
    refreshItem(amb);
    const body = { start: [lat, lon], hospital: amb.hospital };
    if (mode === 'typical') body.hour = Number($('hour').value);
    try {
      const resp = await fetch('/api/route', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
      });
      const data = await resp.json();
      if (!resp.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Could not plan a route');
      if (!ambulances.has(amb.id)) return;  // removed while waiting
      amb.route = data;
      amb.simT = 0;
      amb.status = 'driving';
      drawRoute(amb);
    } catch (e) {
      amb.status = 'error';
      amb.error = e.message;
      amb.route = null;
      amb.layer.eachLayer(l => { if (l !== amb.marker) amb.layer.removeLayer(l); });
    }
    amb.marker.setIcon(ambIcon(amb));
    renderList();
  }

  // ---------- drawing ----------
  function ambIcon(amb) {
    const cls = amb.status === 'error' ? 'amb err' : amb.status === 'arrived' ? 'amb done' : 'amb';
    return L.divIcon({ className: '', iconSize: [30, 30], html: `<div class="${cls}">🚑<span>${amb.label}</span></div>` });
  }

  function drawRoute(amb) {
    const r = amb.route;
    amb.layer.eachLayer(l => { if (l !== amb.marker) amb.layer.removeLayer(l); });
    // The route an ordinary driver would take, for comparison (only if it differs).
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
      L.circleMarker([s.lat, s.lon], { radius: 6, weight: 2, color: '#fff', fillColor: css('--red'), fillOpacity: 1 })
        .bindTooltip(() => signalTip(amb, s)).addTo(amb.layer));
    amb.marker.setLatLng(r.coords[0]);
  }

  function signalTip(amb, s) {
    const dt = s.eta_s - amb.simT;
    const name = s.name ? escapeHtml(s.name) : 'Signal';
    if (dt < -RELEASE_S) return `<b>${name}</b><br>${amb.label} has passed`;
    if (amb.held.has(s.id)) return `<b>${name}</b><br>Held green · ${amb.label} arrives in ${fmt(dt)}`;
    return `<b>${name}</b><br>${amb.label} arrives in ${fmt(dt)} · turns green ${LEAD_S}s before`;
  }

  function tooltip(amb) {
    if (amb.status === 'error') return `${amb.label}: ${escapeHtml(amb.error)}`;
    if (!amb.route) return `${amb.label}: planning route…`;
    const dest = escapeHtml(amb.route.hospital.name);
    if (amb.status === 'arrived') return `${amb.label} arrived at ${dest}`;
    return `${amb.label} → ${dest}<br>ETA ${fmt(amb.route.eta_s - amb.simT)}`;
  }

  // ---------- simulation ----------
  function positionAt(r, t) {
    const times = r.times;
    let lo = 0, hi = times.length - 1;
    if (t >= times[hi]) return { k: hi, point: r.coords[hi] };
    while (hi - lo > 1) {  // binary search for the segment containing t
      const mid = (lo + hi) >> 1;
      if (times[mid] <= t) lo = mid; else hi = mid;
    }
    const f = times[hi] === times[lo] ? 0 : (t - times[lo]) / (times[hi] - times[lo]);
    const [a, b] = [r.coords[lo], r.coords[hi]];
    return { k: lo, point: [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f] };
  }

  function hold(amb, sigId) {
    if (amb.held.has(sigId)) return;
    amb.held.add(sigId);
    if (!corridorHolds.has(sigId)) corridorHolds.set(sigId, new Set());
    corridorHolds.get(sigId).add(amb.id);
  }

  function release(amb, sigId) {
    if (!amb.held.delete(sigId)) return;
    const holders = corridorHolds.get(sigId);
    if (holders) { holders.delete(amb.id); if (!holders.size) corridorHolds.delete(sigId); }
  }

  function releaseAll(amb) {
    for (const id of [...amb.held]) release(amb, id);
    updateSignals();
  }

  function tick() {
    const dt = TICK_MS / 1000 * speedFactor();
    let changed = false;
    for (const amb of ambulances.values()) {
      if (amb.status !== 'driving') continue;
      const r = amb.route;
      amb.simT = Math.min(amb.simT + dt, r.eta_s);
      const { k, point } = positionAt(r, amb.simT);
      amb.marker.setLatLng(point);
      amb.done.setLatLngs([...r.coords.slice(0, k + 1), point]);
      amb.ahead.setLatLngs([point, ...r.coords.slice(k + 1)]);

      r.signals.forEach((s, i) => {
        const until = s.eta_s - amb.simT;
        const shouldHold = until <= LEAD_S && until >= -RELEASE_S;
        if (shouldHold && !amb.held.has(s.id)) { hold(amb, s.id); changed = true; }
        if (!shouldHold && amb.held.has(s.id)) { release(amb, s.id); changed = true; }
        const passed = until < -RELEASE_S;
        amb.signalMarkers[i].setStyle({
          fillColor: css(passed ? '--grey' : amb.held.has(s.id) ? '--green' : '--red'),
          radius: amb.held.has(s.id) ? 8 : 6,
          opacity: passed ? 0.4 : 1, fillOpacity: passed ? 0.4 : 1,
        }).bringToFront();  // draw above the city-wide signal layer
      });

      if (amb.simT >= r.eta_s) {
        amb.status = 'arrived';
        releaseAll(amb);
        amb.marker.setIcon(ambIcon(amb));
        renderList();
      }
      refreshItem(amb);
    }
    if (changed) updateSignals();
    updateSummary();
  }
  setInterval(tick, TICK_MS);

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
        planRoute(amb, p.lat, p.lng);
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
      f('stats').innerHTML = `<span class="amb-err">${escapeHtml(amb.error)}</span> Drag the ambulance to try another spot.`;
      f('saved').textContent = '';
      f('bar').style.width = '0';
      return;
    }
    if (!r || amb.status === 'routing' || amb.status === 'dragging') {
      f('dest').textContent = amb.status === 'dragging' ? 'Moving…' : 'Planning route…';
      f('stats').textContent = '';
      f('saved').textContent = '';
      return;
    }
    f('dest').textContent = '→ ' + r.hospital.name;
    const passed = r.signals.filter(s => s.eta_s - amb.simT < -RELEASE_S).length;
    const traffic = `traffic at ${String(r.hour).padStart(2, '0')}:00`;
    if (amb.status === 'arrived') {
      f('stats').textContent = `Arrived in ${fmt(r.eta_s)} · ${(r.distance_m / 1000).toFixed(1)} km · ${r.signals.length} signals cleared · ${traffic}`;
    } else {
      const left = r.distance_m * (1 - amb.simT / r.eta_s);
      f('stats').textContent = `ETA ${fmt(r.eta_s - amb.simT)} · ${(left / 1000).toFixed(1)} km left · ` +
        `signals ${passed}/${r.signals.length} · ${amb.held.size} held green · ${traffic}`;
    }
    f('saved').textContent = r.saved_s > 0
      ? `Corridor trip ${fmt(r.eta_s)} vs ${fmt(r.normal.eta_s)} in normal traffic: saves ~${fmt(r.saved_s)}`
      : `Corridor trip ${fmt(r.eta_s)} (normal traffic ${fmt(r.normal.eta_s)})`;
    f('bar').style.width = (100 * amb.simT / r.eta_s).toFixed(1) + '%';
  }

  function updateSummary() {
    const driving = [...ambulances.values()].filter(a => a.status === 'driving').length;
    $('amb-summary').textContent = ambulances.size
      ? `· ${driving} driving · ${corridorHolds.size} signal${corridorHolds.size === 1 ? '' : 's'} green`
      : '';
  }

  // Deep link for demos: /?amb=12.93,77.62&amb=13.02,77.58 drops ambulances on load.
  const urlParams = new URLSearchParams(location.search);
  if (urlParams.get('speed')) $('amb-speed').value = urlParams.get('speed');
  for (const value of urlParams.getAll('amb')) {
    const [lat, lon] = value.split(',').map(Number);
    if (Number.isFinite(lat) && Number.isFinite(lon)) addAmbulance(lat, lon);
  }
})();
