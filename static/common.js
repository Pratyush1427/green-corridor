// Shared helpers for all Green Corridor screens (loaded before each page's own script).

const $ = (id) => document.getElementById(id);
const css = (name) => getComputedStyle(document.body).getPropertyValue(name).trim();
const escapeHtml = (s) => String(s ?? '').replace(/[&<>"']/g, (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));
const fmt = (s) => { s = Math.max(0, Math.round(s || 0)); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`; };
const fmtKm = (m) => (m / 1000).toFixed(m < 10000 ? 1 : 0) + ' km';
const fmtDist = (m) => m >= 1000 ? (m / 1000).toFixed(1) + ' km' : Math.max(10, Math.round(m / 10) * 10) + ' m';
const fmtMin = (s) => Math.max(1, Math.ceil((s || 0) / 60));  // "3 min" reads easier than "2:41"
const istTime = (ts) => new Date(ts.replace(' ', 'T') + 'Z')
  .toLocaleTimeString('en-IN', { timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit' });
const istHourNow = () => Number(new Date().toLocaleString('en-US', { timeZone: 'Asia/Kolkata', hour: 'numeric', hourCycle: 'h23' }));
const params = new URLSearchParams(location.search);
const EMBED = !!params.get('embed');  // shown inside the /pitch presenter view

async function api(path, body) {
  const opts = body === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) };
  const resp = await fetch(path, opts);
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `Something went wrong (${resp.status})`);
  return data;
}

function toast(message, kind = '') {
  let box = $('toasts');
  if (!box) { box = document.createElement('div'); box.id = 'toasts'; box.setAttribute('aria-live', 'polite'); document.body.appendChild(box); }
  const el = document.createElement('div');
  el.className = 'toast ' + kind;
  el.textContent = message;
  box.appendChild(el);
  setTimeout(() => el.remove(), 5000);
}

// Small "remember once" helper (browser storage can be unavailable; then it just doesn't remember).
const remember = {
  get: (k) => { try { return localStorage.getItem(k); } catch (e) { return null; } },
  set: (k, v) => { try { localStorage.setItem(k, v); } catch (e) {} },
};

// First-time tips: shown until the user closes them once.
function tip(container, key, html) {
  if (EMBED || remember.get('tip-' + key)) return;
  const el = document.createElement('div');
  el.className = 'tip';
  el.innerHTML = `<span class="tip-icon">💡</span><div>${html}</div><button class="tip-close" aria-label="Got it">×</button>`;
  el.querySelector('.tip-close').addEventListener('click', () => { remember.set('tip-' + key, '1'); el.remove(); });
  container.prepend(el);
}

// Maps: a green-and-blue topographic map by day; a navy night map for the driver after dark.
// Both are free Esri tiles (no API key). Tiles exist up to zoom 16; above that they're enlarged.
function addBaseMap(map, { night = false } = {}) {
  const ATTR = 'Tiles &copy; Esri &mdash; Esri, HERE, Garmin, &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';
  if (night) {
    const C = 'https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/';
    L.tileLayer(C + 'World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}', { maxZoom: 19, maxNativeZoom: 16, className: 'night-tiles', attribution: ATTR }).addTo(map);
    L.tileLayer(C + 'World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}', { maxZoom: 19, maxNativeZoom: 16, className: 'night-tiles' }).addTo(map);
  } else {
    // Esri topographic: blue water, soft green land and parks, calm grey roads, so the blue route
    // and green/red signals stand out.
    L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}',
      { maxZoom: 19, maxNativeZoom: 18, className: 'day-tiles', attribution: ATTR }).addTo(map);
  }
}

function ambIcon(callsign, idle = false) {
  return L.divIcon({ className: '', iconSize: [34, 34],
    html: `<div class="amb ${idle ? 'idle' : ''}">🚑<span>${escapeHtml(callsign)}</span></div>` });
}
const sceneIcon = () => L.divIcon({ className: '', iconSize: [36, 36], html: '<div class="scene">⚠️</div>' });
const destIcon = () => L.divIcon({ className: '', iconSize: [26, 26], html: '<div class="dest"></div>' });

// Moves a marker smoothly to a new position over `ms`, instead of jumping once per poll.
function glide(marker, to, ms = 900) {
  const from = marker.getLatLng();
  if (marker._glide) cancelAnimationFrame(marker._glide);
  if (from.distanceTo(to) > 3000) { marker.setLatLng(to); return; }  // teleport on big jumps
  const start = performance.now();
  const step = (now) => {
    const f = Math.min(1, (now - start) / ms);
    marker.setLatLng([from.lat + (to[0] - from.lat) * f, from.lng + (to[1] - from.lng) * f]);
    if (f < 1) marker._glide = requestAnimationFrame(step);
  };
  marker._glide = requestAnimationFrame(step);
}

// ---------- plain words (no jargon on any screen) ----------
const PHASE = {
  to_scene: 'Going to the accident', at_scene: 'At the accident', to_hospital: 'Taking patient to hospital',
  at_hospital: 'At the hospital', done: 'Finished',
};
const PHASE_ICON = { to_scene: '🚨', at_scene: '📍', to_hospital: '🏥', at_hospital: '🏥', done: '✅' };
// The police answer, in words and in the one colour that means it.
const POLICE = {
  pending: { text: 'Waiting for police', kind: 'wait' },
  approved: { text: 'Police cleared the road', kind: 'ok' },
  partial: { text: 'Police cleared most signals', kind: 'ok' },
  declined: { text: 'Police could not clear it', kind: 'bad' },
  expired: { text: 'No answer from police', kind: 'bad' },
};
// One signal on a route, for the person looking at it.
const SIGNAL = {
  held: { text: 'Green now', kind: 'ok' }, cleared: { text: 'Will be green', kind: 'ok' },
  pending: { text: 'Waiting for police', kind: 'wait' }, cant: { text: "Officer can't clear", kind: 'bad' },
  not_cleared: { text: 'Not cleared', kind: 'bad' }, passed: { text: 'Passed', kind: 'info' },
};
const KIND_COLOR = { ok: '--green-strong', wait: '--amber-strong', bad: '--red-strong', info: '--grey' };
const signalColor = (state) => css(KIND_COLOR[SIGNAL[state]?.kind || 'info']);
const CLEARANCE = Object.fromEntries(Object.entries(POLICE).map(([k, v]) => [k, v.text]));  // older name, same words
const TURN_ARROW = { left: '↰', right: '↱', straight: '↑', 'u-turn': '↶' };
const junctionName = (s) => s.name || [s.from_road, s.to_road].filter((x, i, a) => x && a.indexOf(x) === i).join(' / ') || 'Traffic signal';

// Colour of a route line from the police answer.
function routeStyle(clearance) {
  const kind = POLICE[clearance]?.kind || 'info';
  return { color: kind === 'ok' ? css('--corridor') : css(KIND_COLOR[kind]), dashArray: kind === 'bad' ? '8 8' : null };
}

// ---------- languages (driver & junction screens) ----------
// English, Kannada and Hindi. Road names stay as they are on the map.
// NOTE: translations should be checked by native speakers before real use.
const LANGS = { en: 'English', kn: 'ಕನ್ನಡ', hi: 'हिन्दी' };
const VOICE_LANG = { en: 'en-IN', kn: 'kn-IN', hi: 'hi-IN' };
const WORDS = {
  choose_ambulance: { en: 'Which ambulance are you driving?', kn: 'ನೀವು ಯಾವ ಆಂಬ್ಯುಲೆನ್ಸ್ ಓಡಿಸುತ್ತಿದ್ದೀರಿ?', hi: 'आप कौन-सी एम्बुलेंस चला रहे हैं?' },
  free: { en: 'Free', kn: 'ಲಭ್ಯವಿದೆ', hi: 'खाली' },
  on_call: { en: 'On a call', kn: 'ಕರೆಯಲ್ಲಿದೆ', hi: 'कॉल पर' },
  waiting_call: { en: 'Waiting for a call', kn: 'ಕರೆಗಾಗಿ ಕಾಯಲಾಗುತ್ತಿದೆ', hi: 'कॉल का इंतज़ार' },
  waiting_call_sub: { en: 'A new emergency will appear here by itself, with sound.', kn: 'ಹೊಸ ತುರ್ತು ಕರೆ ತಾನಾಗಿಯೇ ಇಲ್ಲಿ ಶಬ್ದದೊಂದಿಗೆ ಬರುತ್ತದೆ.', hi: 'नई इमरजेंसी अपने-आप यहाँ आवाज़ के साथ आएगी।' },
  go_accident: { en: 'Go to the accident', kn: 'ಅಪಘಾತದ ಸ್ಥಳಕ್ಕೆ ಹೋಗಿ', hi: 'दुर्घटना स्थल पर जाएँ' },
  go_hospital: { en: 'Take the patient to', kn: 'ರೋಗಿಯನ್ನು ಇಲ್ಲಿಗೆ ಕರೆದೊಯ್ಯಿರಿ', hi: 'मरीज़ को यहाँ ले जाएँ' },
  minutes: { en: 'min', kn: 'ನಿಮಿಷ', hi: 'मिनट' },
  left_to_go: { en: 'to go', kn: 'ಬಾಕಿ', hi: 'बाकी' },
  next_signal: { en: 'Next signal', kn: 'ಮುಂದಿನ ಸಿಗ್ನಲ್', hi: 'अगला सिग्नल' },
  green_for_you: { en: 'GREEN for you', kn: 'ನಿಮಗೆ ಹಸಿರು', hi: 'आपके लिए हरा' },
  will_be_green: { en: 'Will turn green for you', kn: 'ನಿಮಗಾಗಿ ಹಸಿರಾಗುತ್ತದೆ', hi: 'आपके लिए हरा होगा' },
  waiting_police: { en: 'Waiting for police', kn: 'ಪೊಲೀಸರಿಗಾಗಿ ಕಾಯಲಾಗುತ್ತಿದೆ', hi: 'पुलिस का इंतज़ार' },
  not_cleared: { en: 'Not cleared: go carefully', kn: 'ತೆರವು ಆಗಿಲ್ಲ: ಎಚ್ಚರಿಕೆಯಿಂದ ಹೋಗಿ', hi: 'रास्ता खुला नहीं: सावधानी से चलें' },
  no_more_signals: { en: 'No more signals', kn: 'ಇನ್ನು ಸಿಗ್ನಲ್ ಇಲ್ಲ', hi: 'आगे कोई सिग्नल नहीं' },
  stopped_red: { en: 'Stopped at a red signal', kn: 'ಕೆಂಪು ಸಿಗ್ನಲ್‌ನಲ್ಲಿ ನಿಂತಿದೆ', hi: 'लाल सिग्नल पर रुके हैं' },
  police_cleared: { en: 'Police cleared your road', kn: 'ಪೊಲೀಸರು ನಿಮ್ಮ ರಸ್ತೆ ತೆರವುಗೊಳಿಸಿದ್ದಾರೆ', hi: 'पुलिस ने आपका रास्ता खुलवाया' },
  police_waiting: { en: 'Police informed, waiting for answer', kn: 'ಪೊಲೀಸರಿಗೆ ತಿಳಿಸಲಾಗಿದೆ, ಉತ್ತರಕ್ಕಾಗಿ ಕಾಯಲಾಗುತ್ತಿದೆ', hi: 'पुलिस को बताया, जवाब का इंतज़ार' },
  police_no: { en: 'Police could not clear: drive carefully', kn: 'ಪೊಲೀಸರು ತೆರವುಗೊಳಿಸಲಾಗಲಿಲ್ಲ: ಎಚ್ಚರಿಕೆಯಿಂದ ಓಡಿಸಿ', hi: 'पुलिस रास्ता नहीं खुलवा सकी: सावधानी से चलाएँ' },
  turn_left: { en: 'Turn left', kn: 'ಎಡಕ್ಕೆ ತಿರುಗಿ', hi: 'बाएँ मुड़ें' },
  turn_right: { en: 'Turn right', kn: 'ಬಲಕ್ಕೆ ತಿರುಗಿ', hi: 'दाएँ मुड़ें' },
  go_straight: { en: 'Go straight', kn: 'ನೇರವಾಗಿ ಹೋಗಿ', hi: 'सीधे चलें' },
  u_turn: { en: 'Make a U-turn', kn: 'ಯು-ಟರ್ನ್ ಮಾಡಿ', hi: 'यू-टर्न लें' },
  onto: { en: 'onto', kn: '→', hi: '→' },
  at_accident: { en: 'You are at the accident', kn: 'ನೀವು ಅಪಘಾತದ ಸ್ಥಳದಲ್ಲಿದ್ದೀರಿ', hi: 'आप दुर्घटना स्थल पर हैं' },
  at_hospital: { en: 'You are at the hospital', kn: 'ನೀವು ಆಸ್ಪತ್ರೆಯಲ್ಲಿದ್ದೀರಿ', hi: 'आप अस्पताल पहुँच गए' },
  btn_patient_in: { en: 'Patient is in the ambulance', kn: 'ರೋಗಿ ಆಂಬ್ಯುಲೆನ್ಸ್‌ನಲ್ಲಿದ್ದಾರೆ', hi: 'मरीज़ एम्बुलेंस में है' },
  btn_patient_in_sub: { en: 'We will find the nearest hospital and tell the police', kn: 'ಹತ್ತಿರದ ಆಸ್ಪತ್ರೆ ಹುಡುಕಿ ಪೊಲೀಸರಿಗೆ ತಿಳಿಸುತ್ತೇವೆ', hi: 'हम नज़दीकी अस्पताल ढूँढकर पुलिस को बताएँगे' },
  btn_handed_over: { en: 'Patient handed over', kn: 'ರೋಗಿಯನ್ನು ಹಸ್ತಾಂತರಿಸಲಾಗಿದೆ', hi: 'मरीज़ सौंप दिया' },
  btn_handed_over_sub: { en: 'You will be free for the next call', kn: 'ಮುಂದಿನ ಕರೆಗೆ ನೀವು ಲಭ್ಯರಾಗುತ್ತೀರಿ', hi: 'आप अगली कॉल के लिए खाली हो जाएँगे' },
  voice_on: { en: 'Voice on', kn: 'ಧ್ವನಿ ಆನ್', hi: 'आवाज़ चालू' },
  voice_off: { en: 'Voice off', kn: 'ಧ್ವನಿ ಆಫ್', hi: 'आवाज़ बंद' },
  change: { en: 'Change', kn: 'ಬದಲಿಸಿ', hi: 'बदलें' },
  next: { en: 'Next', kn: 'ಮುಂದೆ', hi: 'आगे' },
  signals_ahead: { en: 'Signals ahead', kn: 'ಮುಂದಿನ ಸಿಗ್ನಲ್‌ಗಳು', hi: 'आगे के सिग्नल' },
  settings: { en: 'Settings', kn: 'ಸೆಟ್ಟಿಂಗ್‌ಗಳು', hi: 'सेटिंग्स' },
  all_clear: { en: 'All clear', kn: 'ಎಲ್ಲವೂ ಸರಿಯಾಗಿದೆ', hi: 'सब ठीक है' },
  alarm_off: { en: 'Alarm is off. Tap to turn on', kn: 'ಎಚ್ಚರಿಕೆ ಆಫ್ ಆಗಿದೆ. ಆನ್ ಮಾಡಲು ಒತ್ತಿ', hi: 'अलार्म बंद है। चालू करने के लिए दबाएँ' },
  word_from: { en: 'From', kn: 'ಇಂದ', hi: 'से' },
  word_to: { en: 'to', kn: 'ಕಡೆಗೆ', hi: 'की ओर' },
  back: { en: 'Back', kn: 'ಹಿಂದೆ', hi: 'वापस' },
  change_answer: { en: 'Change answer', kn: 'ಉತ್ತರ ಬದಲಿಸಿ', hi: 'जवाब बदलें' },
  close: { en: 'Close', kn: 'ಮುಚ್ಚಿ', hi: 'बंद करें' },
  // junction officer
  officer_title: { en: 'Signal officer', kn: 'ಸಿಗ್ನಲ್ ಅಧಿಕಾರಿ', hi: 'सिग्नल अधिकारी' },
  your_name: { en: 'Your name', kn: 'ನಿಮ್ಮ ಹೆಸರು', hi: 'आपका नाम' },
  choose_signal: { en: 'Which signal are you at?', kn: 'ನೀವು ಯಾವ ಸಿಗ್ನಲ್‌ನಲ್ಲಿದ್ದೀರಿ?', hi: 'आप किस सिग्नल पर हैं?' },
  use_location: { en: 'Find my signal (use my location)', kn: 'ನನ್ನ ಸಿಗ್ನಲ್ ಹುಡುಕಿ (ನನ್ನ ಸ್ಥಳ ಬಳಸಿ)', hi: 'मेरा सिग्नल ढूँढें (मेरी लोकेशन से)' },
  or_pick: { en: 'Or tap a signal on the map. Orange ones have an ambulance coming.', kn: 'ಅಥವಾ ನಕ್ಷೆಯಲ್ಲಿ ಸಿಗ್ನಲ್ ಒತ್ತಿ. ಕಿತ್ತಳೆ ಬಣ್ಣದವುಗಳಿಗೆ ಆಂಬ್ಯುಲೆನ್ಸ್ ಬರುತ್ತಿದೆ.', hi: 'या नक्शे पर सिग्नल दबाएँ। नारंगी वालों पर एम्बुलेंस आ रही है।' },
  ambulance_coming_list: { en: 'Ambulances coming to these signals', kn: 'ಈ ಸಿಗ್ನಲ್‌ಗಳಿಗೆ ಆಂಬ್ಯುಲೆನ್ಸ್ ಬರುತ್ತಿದೆ', hi: 'इन सिग्नलों पर एम्बुलेंस आ रही है' },
  sound_title: { en: 'Turn on the alarm sound', kn: 'ಎಚ್ಚರಿಕೆ ಶಬ್ದ ಆನ್ ಮಾಡಿ', hi: 'अलार्म की आवाज़ चालू करें' },
  sound_sub: { en: 'Your phone will ring loudly when an ambulance is coming.', kn: 'ಆಂಬ್ಯುಲೆನ್ಸ್ ಬರುವಾಗ ನಿಮ್ಮ ಫೋನ್ ಜೋರಾಗಿ ಶಬ್ದ ಮಾಡುತ್ತದೆ.', hi: 'एम्बुलेंस आने पर आपका फ़ोन ज़ोर से बजेगा।' },
  sound_btn: { en: 'Turn on sound and test it', kn: 'ಶಬ್ದ ಆನ್ ಮಾಡಿ ಪರೀಕ್ಷಿಸಿ', hi: 'आवाज़ चालू करें और जाँचें' },
  calm_title: { en: 'No ambulance coming', kn: 'ಯಾವುದೇ ಆಂಬ್ಯುಲೆನ್ಸ್ ಬರುತ್ತಿಲ್ಲ', hi: 'कोई एम्बुलेंस नहीं आ रही' },
  calm_sub: { en: 'Keep this screen open. Your phone will ring when one is coming.', kn: 'ಈ ಪರದೆ ತೆರೆದಿಡಿ. ಆಂಬ್ಯುಲೆನ್ಸ್ ಬರುವಾಗ ಫೋನ್ ಶಬ್ದ ಮಾಡುತ್ತದೆ.', hi: 'यह स्क्रीन खुली रखें। एम्बुलेंस आने पर फ़ोन बजेगा।' },
  ambulance_coming: { en: 'AMBULANCE COMING', kn: 'ಆಂಬ್ಯುಲೆನ್ಸ್ ಬರುತ್ತಿದೆ', hi: 'एम्बुलेंस आ रही है' },
  arrives_in: { en: 'Reaches you in', kn: 'ನಿಮ್ಮನ್ನು ತಲುಪಲು', hi: 'आप तक पहुँचेगी' },
  comes_from: { en: 'Comes from', kn: 'ಇಲ್ಲಿಂದ ಬರುತ್ತದೆ', hi: 'यहाँ से आएगी' },
  goes_to: { en: 'Goes to', kn: 'ಇಲ್ಲಿಗೆ ಹೋಗುತ್ತದೆ', hi: 'यहाँ जाएगी' },
  turns_left: { en: 'turns LEFT', kn: 'ಎಡಕ್ಕೆ ತಿರುಗುತ್ತದೆ', hi: 'बाएँ मुड़ेगी' },
  turns_right: { en: 'turns RIGHT', kn: 'ಬಲಕ್ಕೆ ತಿರುಗುತ್ತದೆ', hi: 'दाएँ मुड़ेगी' },
  goes_straight: { en: 'goes STRAIGHT', kn: 'ನೇರವಾಗಿ ಹೋಗುತ್ತದೆ', hi: 'सीधे जाएगी' },
  btn_clearing: { en: 'I will clear the road', kn: 'ನಾನು ರಸ್ತೆ ತೆರವುಗೊಳಿಸುತ್ತೇನೆ', hi: 'मैं रास्ता खाली कराऊँगा' },
  btn_cant: { en: 'Not possible', kn: 'ಸಾಧ್ಯವಿಲ್ಲ', hi: 'संभव नहीं' },
  why_cant: { en: 'Why? Tap one:', kn: 'ಏಕೆ? ಒಂದನ್ನು ಒತ್ತಿ:', hi: 'क्यों? एक दबाएँ:' },
  r_jam: { en: 'Traffic jam', kn: 'ಟ್ರಾಫಿಕ್ ಜಾಮ್', hi: 'ट्रैफ़िक जाम' },
  r_vip: { en: 'VIP movement', kn: 'ವಿಐಪಿ ಸಂಚಾರ', hi: 'वीआईपी मूवमेंट' },
  r_blocked: { en: 'Road blocked', kn: 'ರಸ್ತೆ ಬಂದ್', hi: 'सड़क बंद' },
  r_staff: { en: 'Not enough staff', kn: 'ಸಿಬ್ಬಂದಿ ಕೊರತೆ', hi: 'स्टाफ़ कम है' },
  you_clearing: { en: 'You are clearing the road. The signal turns green for the ambulance.', kn: 'ನೀವು ರಸ್ತೆ ತೆರವುಗೊಳಿಸುತ್ತಿದ್ದೀರಿ. ಆಂಬ್ಯುಲೆನ್ಸ್‌ಗೆ ಸಿಗ್ನಲ್ ಹಸಿರಾಗುತ್ತದೆ.', hi: 'आप रास्ता खाली करा रहे हैं। एम्बुलेंस के लिए सिग्नल हरा होगा।' },
  you_cant: { en: 'You said it is not possible. The driver has been told.', kn: 'ಸಾಧ್ಯವಿಲ್ಲ ಎಂದು ನೀವು ಹೇಳಿದ್ದೀರಿ. ಚಾಲಕರಿಗೆ ತಿಳಿಸಲಾಗಿದೆ.', hi: 'आपने कहा संभव नहीं। ड्राइवर को बता दिया गया है।' },
  more_coming: { en: 'more coming', kn: 'ಇನ್ನಷ್ಟು ಬರುತ್ತಿವೆ', hi: 'और आ रही हैं' },
  seconds: { en: 'sec', kn: 'ಸೆಕೆಂಡು', hi: 'सेकंड' },
};
let LANG = remember.get('gc-lang') || 'en';
const t = (key) => WORDS[key]?.[LANG] || WORDS[key]?.en || key;
function langSwitch(container, onChange) {
  container.innerHTML = Object.entries(LANGS).map(([k, name]) => `<button data-lang="${k}" class="${k === LANG ? 'on' : ''}">${name}</button>`).join('');
  container.querySelectorAll('button').forEach(b => b.addEventListener('click', () => {
    LANG = b.dataset.lang; remember.set('gc-lang', LANG);
    container.querySelectorAll('button').forEach(x => x.classList.toggle('on', x === b));
    onChange?.();
  }));
}
// Speak in the chosen language if this phone has that voice; otherwise in English.
// Voices load asynchronously in most browsers, so keep the list fresh.
let VOICES = [];
if ('speechSynthesis' in window) {
  const load = () => { VOICES = speechSynthesis.getVoices(); };
  load();
  speechSynthesis.addEventListener?.('voiceschanged', load);
}
// Indian voices, preferring a natural-sounding FEMALE voice. Names are how browsers and phones
// label their voices (Microsoft Edge, Apple, Google); names not listed count as unknown.
const FEMALE = /neerja|isha|veena|tara|heera|kajal|swara|lekha|soumya|sapna|aditi|raveena|kalpana|female/i;
const MALE = /rishi|aman|prabhat|hemant|ravi|madhur|kumar|male\b/i;
const norm = (l) => l.replace('_', '-').toLowerCase();
function voiceScore(v) {
  const n = v.name.toLowerCase();
  let s = 0;
  if (FEMALE.test(n)) s += 10;
  if (MALE.test(n)) s -= 10;
  if (/natural|neural|online|premium|enhanced/.test(n)) s += 4;
  if (n.includes('google')) s += 3;   // Google's Indian voices are female by default
  if (v.localService) s += 1;         // works offline
  return s;
}
const voicesFor = (lang) => VOICES.filter(v => norm(v.lang) === lang.toLowerCase()).sort((a, b) => voiceScore(b) - voiceScore(a));
const indianVoices = () => voicesFor('en-IN');

// The voice to use. Everything is spoken in Indian English, so only Indian English (en-IN) voices
// are used, never a Hindi or Kannada voice (they read numbers in Hindi or Kannada) and never a
// US/UK one. A voice picked by the user wins; otherwise a female voice if the device has one.
function pickVoice() {
  const own = voicesFor('en-IN');
  const chosen = remember.get('gc-voice');
  return own.find(v => v.name === chosen) || own[0] || null;
}
const indianVoice = pickVoice;  // older name

// Speak in Indian English (the English text, whatever language the screen shows).
function speak(textByLang) {
  if (!('speechSynthesis' in window)) return;
  if (!VOICES.length) VOICES = speechSynthesis.getVoices();
  const text = typeof textByLang === 'string' ? textByLang : textByLang.en;
  const voice = pickVoice();
  const u = new SpeechSynthesisUtterance(text);
  u.lang = 'en-IN';
  if (voice) u.voice = voice;
  u.rate = 1;   // normal speed: slowing it down stretches the gaps between words
  speechSynthesis.cancel();  // never queue up behind an old message
  speechSynthesis.speak(u);
}

// A small "Voice" chooser with a test button, for phones whose default voice sounds poor.
function voicePicker(container) {
  if (!container || !('speechSynthesis' in window)) return;
  const draw = () => {
    const list = indianVoices().sort((a, b) => voiceScore(b) - voiceScore(a));
    const chosen = remember.get('gc-voice') || '';
    container.innerHTML = `<div class="row" style="gap:8px;margin-top:10px">
      <label class="small muted" for="voice-pick">🗣️ Voice</label>
      <select id="voice-pick" style="flex:1;min-height:44px">
        <option value="">Automatic (Indian English, female if available)</option>
        ${list.map(v => `<option value="${escapeHtml(v.name)}" ${v.name === chosen ? 'selected' : ''}>${escapeHtml(v.name)} · ${FEMALE.test(v.name) ? 'female' : MALE.test(v.name) ? 'male' : 'Indian English'}</option>`).join('')}
      </select>
      <button class="btn small" id="voice-test">▶ Test</button></div>`;
    container.querySelector('#voice-pick').addEventListener('change', (e) => remember.set('gc-voice', e.target.value));
    container.querySelector('#voice-test').addEventListener('click', () => speak({
      en: 'Ambulance coming from Outer Ring Road. It turns left. Reaches you in thirty seconds.',
      kn: 'ಆಂಬ್ಯುಲೆನ್ಸ್ ಬರುತ್ತಿದೆ. ಮೂವತ್ತು ಸೆಕೆಂಡುಗಳಲ್ಲಿ ತಲುಪುತ್ತದೆ.',
      hi: 'एम्बुलेंस आ रही है। तीस सेकंड में पहुँचेगी।' }));
  };
  draw();
  if (!VOICES.length) speechSynthesis.addEventListener?.('voiceschanged', draw, { once: true });
}

// Route geometry never changes once planned, so fetch each incident's full routes once.
const geometryCache = new Map();  // leg id -> {coords, normal_coords}
async function legGeometry(incidentId, legId) {
  if (!geometryCache.has(legId)) {
    const inc = await api(`/api/incidents/${incidentId}`);
    for (const l of inc.legs) geometryCache.set(l.id, l.route);
  }
  return geometryCache.get(legId);
}

// ---------- navigation helpers (driver & junction screens) ----------

function bearing(a, b) {  // compass bearing from a to b, degrees
  const r = Math.PI / 180, lat1 = a[0] * r, lat2 = b[0] * r, dLon = (b[1] - a[1]) * r;
  const x = Math.sin(dLon) * Math.cos(lat2);
  const y = Math.cos(lat1) * Math.sin(lat2) - Math.sin(lat1) * Math.cos(lat2) * Math.cos(dLon);
  return (Math.atan2(x, y) / r + 360) % 360;
}

// Index of the route point nearest to p, searching forward from `from` (vehicles don't go back).
function nearestIndex(coords, p, from = 0) {
  let best = from, bestD = Infinity;
  for (let i = Math.max(0, from - 3); i < coords.length; i++) {
    const d = (coords[i][0] - p[0]) ** 2 + ((coords[i][1] - p[1]) * Math.cos(p[0] * Math.PI / 180)) ** 2;
    if (d < bestD) { bestD = d; best = i; }
  }
  return best;
}

// Which route segment [k, k+1] a point lies on (searching forward from `from`, since vehicles
// don't go back). Unlike the nearest route point, this can't be behind the vehicle.
function nearestSegment(coords, p, from = 0) {
  const kx = Math.cos(p[0] * Math.PI / 180);
  let best = from, bestD = Infinity;
  for (let k = Math.max(0, from - 2); k < coords.length - 1; k++) {
    const [a, b] = [coords[k], coords[k + 1]];
    const ax = (b[1] - a[1]) * kx, ay = b[0] - a[0], px = (p[1] - a[1]) * kx, py = p[0] - a[0];
    const tt = Math.max(0, Math.min(1, (px * ax + py * ay) / (ax * ax + ay * ay || 1)));
    const d = (px - tt * ax) ** 2 + (py - tt * ay) ** 2;
    if (d < bestD) { bestD = d; best = k; }
  }
  return best;
}

// Direction of travel from the route itself: towards the first route point ~15 m ahead of the
// segment the vehicle is on. Steadier than comparing two GPS fixes, which jitters around bends.
function routeHeading(coords, seg, p) {
  for (let i = seg + 1; i < coords.length; i++) {
    const dy = (coords[i][0] - p[0]) * 111320, dx = (coords[i][1] - p[1]) * 111320 * Math.cos(p[0] * Math.PI / 180);
    if (Math.hypot(dx, dy) > 15) return bearing(p, coords[i]);
  }
  return bearing(coords[Math.max(0, coords.length - 2)], coords[coords.length - 1]);
}

// Navigation arrow (like phone map apps) that rotates with the heading.
function navIcon(heading, label) {
  return L.divIcon({ className: '', iconSize: [48, 48], iconAnchor: [24, 24], html:
    `<div class="nav-arrow" style="transform:rotate(${heading}deg)"><svg viewBox="0 0 44 44" width="48" height="48">
      <circle cx="22" cy="22" r="20" fill="rgba(8,145,178,.22)"/><circle cx="22" cy="22" r="16" fill="#fff"/>
      <path d="M22 7 L32 32 L22 24 L12 32 Z" fill="#0e7490" stroke="#083344" stroke-width="1.2" stroke-linejoin="round"/></svg></div>` +
    (label ? `<span class="nav-label">${escapeHtml(label)}</span>` : '') });
}

// Bottom sheet like phone map apps. Markup:
//   <div class="sheet"><div class="sheet-grab"><div class="sheet-handle"></div><div class="sheet-head"></div></div><div class="sheet-body"></div></div>
// Collapsed, it shows exactly the handle + head (measured, so nothing is ever cut off). Drag or tap
// the head to open it; the body scrolls on its own. onChange(height) lets the map keep things in view.
function makeSheet(sheet, { mid = 0.5, max = 0.88, start = 'peek', onChange = () => {} } = {}) {
  const grab = sheet.querySelector('.sheet-grab');
  const peekH = () => Math.ceil(grab.getBoundingClientRect().height) + 8;
  const stops = () => [peekH(), Math.max(peekH() + 60, Math.round(innerHeight * mid)), Math.round(innerHeight * max)];
  let level = start === 'peek' ? 0 : start === 'max' ? 2 : 1, height = 0;
  const set = (h, animate) => {
    const [lo, , hi] = stops();
    height = Math.max(lo, Math.min(hi, h));
    sheet.style.transition = animate ? 'height .25s ease' : 'none';
    sheet.style.height = height + 'px';
    sheet.classList.toggle('open', height > lo + 20);
    document.documentElement.style.setProperty('--sheet-h', height + 'px');
    onChange(height);
  };
  const snapTo = (lv, animate = true) => { level = lv; set(stops()[lv], animate); };
  let startY = null, startH = 0, moved = false;
  grab.addEventListener('pointerdown', (e) => {
    if (e.target.closest('button, a, select, input')) return;  // let buttons in the head work normally
    startY = e.clientY; startH = height; moved = false; grab.setPointerCapture(e.pointerId);
  });
  grab.addEventListener('pointermove', (e) => {
    if (startY === null) return;
    if (Math.abs(e.clientY - startY) > 6) moved = true;
    if (moved) set(startH + (startY - e.clientY), false);
  });
  const release = () => {
    if (startY === null) return;
    startY = null;
    if (!moved) { snapTo(level === 0 ? 1 : 0); return; }  // a tap opens / closes
    const st = stops();
    snapTo(st.reduce((best, h, i) => Math.abs(h - height) < Math.abs(st[best] - height) ? i : best, 0));
  };
  grab.addEventListener('pointerup', release);
  grab.addEventListener('pointercancel', release);
  addEventListener('resize', () => snapTo(level, false));
  // the head changes size as its content changes: keep the collapsed sheet hugging it
  new ResizeObserver(() => { if (level === 0) snapTo(0, false); }).observe(grab);
  requestAnimationFrame(() => snapTo(level, false));
  return { open: () => snapTo(1), expand: () => snapTo(2), peek: () => snapTo(0), height: () => height, isOpen: () => level > 0 };
}

// Lets the user drag the side panel's edge to resize it; the width is remembered.
// side: 'right' (panel on the right, the default) or 'left'.
function makeResizableSidebar(layout, aside, map, key, { min = 320, max = 760, side = 'right' } = {}) {
  const bar = document.createElement('div');
  bar.title = 'Drag to resize';
  Object.assign(bar.style, { position: 'absolute', top: 0, bottom: 0, [side === 'right' ? 'left' : 'right']: '-4px', width: '8px', cursor: 'col-resize', zIndex: 1000 });
  bar.className = 'sidebar-resizer';
  aside.style.position = 'relative';
  aside.prepend(bar);
  const apply = (w) => {
    if (matchMedia('(max-width: 900px)').matches) { layout.style.gridTemplateColumns = ''; return; }
    w = Math.max(min, Math.min(max, w));
    layout.style.gridTemplateColumns = side === 'right' ? `1fr ${w}px` : `${w}px 1fr`;
    map.invalidateSize();
  };
  const saved = Number(remember.get(key));
  if (saved) apply(saved);
  let dragging = false;
  bar.addEventListener('pointerdown', (e) => { dragging = true; bar.setPointerCapture(e.pointerId); document.body.style.userSelect = 'none'; });
  bar.addEventListener('pointermove', (e) => { if (dragging) apply(side === 'right' ? innerWidth - e.clientX : e.clientX); });
  bar.addEventListener('pointerup', () => {
    dragging = false; document.body.style.userSelect = '';
    remember.set(key, String(aside.getBoundingClientRect().width));
  });
  bar.addEventListener('dblclick', () => { layout.style.gridTemplateColumns = ''; map.invalidateSize(); remember.set(key, ''); });
}

// A shared top bar: logo, screen name, and a way back to the start.
function topbar(el, roleName, extraHtml = '') {
  if (EMBED) { el.remove(); return; }
  el.className = 'topbar';
  el.innerHTML = `<a class="brand" href="/" title="Back to the start"><span class="logo">🚑</span>Green Corridor</a>
    <span class="who">· ${escapeHtml(roleName)}</span><span class="grow"></span>${extraHtml}`;
}
