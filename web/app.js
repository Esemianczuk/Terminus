const $ = (selector) => document.querySelector(selector);
const ui = {
  habitat: $('#habitat'), field: $('#field'), nodes: $('#nodes'), creature: $('#creature'), body: $('#creature-body'), sprite: $('#sprite'),
  connection: $('#connection'), note: $('#field-note span'), utterance: $('#utterance'), drawer: $('#observatory'), settings: $('#settings'), localAccess: $('#local-only'),
};

// A fixed visual alphabet. The server owns glyph sequences; this client only draws them.
const GLYPHS = Object.freeze([
  'M12 3v18M4 8l8 5 8-5M5 19l7-4 7 4',
  'M5 7c8-7 18 3 12 10S-1 16 5 7M9 10l6 4',
  'M4 18L12 4l8 14M7 13h10M12 18v4',
  'M4 6h16M8 6v12l4 4 4-4V6M5 14h14',
  'M6 4v16M18 4v16M6 9l12 6M6 15l12-6',
  'M12 3C4 3 3 10 8 12c-5 2-4 9 4 9M12 3c8 0 9 7 4 9 5 2 4 9-4 9',
  'M4 12h16M12 4v16M6 6l12 12M18 6 6 18',
  'M4 18c1-11 6-16 8-9 2-7 7-2 8 9M8 17h8',
  'M5 4l14 8L5 20V4M11 8v8M3 12h3',
  'M4 7h16l-8 14L4 7M12 3v4M9 13h6',
  'M4 12c0-9 16-9 16 0S4 21 4 12M9 8v8M15 8v8',
  'M5 20V4l14 16V4M3 12h18',
  'M12 3v18M5 6l7 5 7-5M5 18l7-5 7 5',
  'M4 5c12 0 16 5 16 15M4 20C4 9 8 5 20 5M7 17l10-10',
  'M12 3L3 12l9 9 9-9-9-9M8 12h8M12 8v8',
  'M4 20l4-16 4 10 4-10 4 16M8 18h8',
  'M3 8h18M7 8v9l5 4 5-4V8M9 3l3 5 3-5',
  'M4 19C4 3 20 3 20 19M8 19V9M16 19V9M4 14h16',
  'M4 4l8 8-8 8M12 4l8 8-8 8M4 12h16',
  'M12 3C2 9 2 16 12 21c10-5 10-12 0-18M8 11l4 5 4-5',
]);
const NODE_GLYPHS = Object.freeze({self:0,presence:1,context:2,git:3,poke:4,time:5,familiar:6,sleep:7,curious:8,surprise:9,ease:10,focus:11,uncertain:12,absence:13,play:14,dream:15,again:16,new:17,fade:18,together:19,drag:4,activity:3});
const svgNS = 'http://www.w3.org/2000/svg';
const glyph = (id) => {
  const svg = document.createElementNS(svgNS, 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('aria-hidden', 'true');
  const path = document.createElementNS(svgNS, 'path');
  path.setAttribute('d', GLYPHS[Math.abs(Number(id) || 0) % GLYPHS.length]);
  svg.append(path);
  return svg;
};
const clamp = (value, low = 0, high = 1) => Math.min(high, Math.max(low, Number(value) || 0));
const hash = (value) => [...String(value)].reduce((acc, ch) => ((acc << 5) - acc + ch.charCodeAt(0)) | 0, 0) >>> 0;
const safeRead = (key, fallback) => { try { return JSON.parse(localStorage.getItem(key)) ?? fallback; } catch { return fallback; } };
const safeWrite = (key, value) => { try { localStorage.setItem(key, JSON.stringify(value)); return true; } catch { return false; } };
const uuid = () => crypto.randomUUID?.() || `web-${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
let deviceId = safeRead('terminus.device', null);
if (!deviceId || typeof deviceId !== 'string') { deviceId = `web-${uuid()}`.slice(0, 64); safeWrite('terminus.device', deviceId); }
let preferences = safeRead('terminus.preferences', {});
const systemMotion = matchMedia('(prefers-reduced-motion: reduce)');
const motionPreference = () => typeof preferences.reducedMotion === 'boolean' ? preferences.reducedMotion : systemMotion.matches;
let reducedMotion = motionPreference();
let state = null;
let snapshotTime = null;
let connected = false;
let authenticated = false;
// A saved, formerly authenticated view may queue explicit actions while auth is
// unknown. Only a fresh server response can authorize replay or mark us online.
let localAccessRequired = false;
let socket = null;
let retryTimer = null;
let retryCount = 0;
let lastFrameAt = 0;
let lastUtteranceId = null;
let serverOffset = 0;
let toastTimer;
let utteranceTimer;
let inspectResult = null;
let inspectRequest = null;
let dimensions = { width: 1200, height: 800, ratio: 1 };
let dragging = null;
let refineLoaded = false;
let sleepArtLoaded = false;
let flushing = false;
let lastPresenceAttempt = 0;
let bootstrapGeneration = 0;
let replayAfter = 0;
let memoryBuffer = [];
let bufferStorageFailed = false;
// v2 adds local organism scope. Older open clients must not consume this schema.
const BUFFER_KEY = 'terminus.pending-events.v2';
const BUFFER_TTL = 30 * 60 * 1000;
const BUFFER_LIMIT = 24;
const eventBuffer = () => {
  const stored = bufferStorageFailed ? memoryBuffer : safeRead(BUFFER_KEY, memoryBuffer);
  return Array.isArray(stored) ? stored.filter(item => item && typeof item.id === 'string' && Number.isFinite(item.queuedAt) && Date.now() - item.queuedAt < BUFFER_TTL).slice(-BUFFER_LIMIT) : [];
};
function writeBuffer(events) {
  memoryBuffer = events;
  bufferStorageFailed = !safeWrite(BUFFER_KEY,events);
}

function toast(message) {
  clearTimeout(toastTimer);
  $('#toast').textContent = message;
  $('#toast').classList.add('show');
  toastTimer = setTimeout(() => $('#toast').classList.remove('show'), 4300);
}
function setConnection(mode, text) {
  connected = mode === 'online';
  document.body.classList.toggle('saved-view',!connected);
  ui.connection.dataset.mode = mode;
  ui.connection.querySelector('span').textContent = text;
  ui.creature.dataset.disabled = String(!state || localAccessRequired);
  if (mode !== 'online') {
    clearTimeout(utteranceTimer);
    ui.utterance.classList.remove('visible');
    ui.note.textContent = state ? `Snapshot · ${new Date(snapshotTime || Date.now()).toLocaleString([], {month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'})} · waiting to reconnect` : navigator.onLine ? 'Waiting for the local habitat' : 'Offline · no saved habitat yet';
    $('#sync-detail').textContent = state ? 'Saved view · server state has not changed here' : 'Connecting to the organism';
  }
  updateBufferLabel();
}
function updateBufferLabel() {
  const count = eventBuffer().length;
  $('#buffer-status').textContent = count ? `${count} explicit ${count === 1 ? 'event is' : 'events are'} waiting. Expires after 30 minutes.` : 'No waiting events.';
  $('#context-help').textContent = localAccessRequired || !state ? 'Connect to the local core to offer a context.' : connected ? 'A real event, offered by you.' : 'Saved view: explicit events wait for live authentication.';
}
function epoch(value) {
  if (typeof value === 'number') return value < 1e12 ? value * 1000 : value;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : 0;
}
function age(value) {
  const duration = Math.max(0, Date.now() + serverOffset - epoch(value));
  if (!epoch(value)) return '—';
  if (duration < 60000) return 'just now';
  if (duration < 3600000) return `${Math.floor(duration / 60000)}m ago`;
  if (duration < 86400000) return `${Math.floor(duration / 3600000)}h ago`;
  return `${Math.floor(duration / 86400000)}d ago`;
}
const BEHAVIORS = { sleep:'Resting for a while', idle:'Quietly here', attend:'Something caught his attention', inspect:'A little curious', dream:'Drifting through a dream', startled:'A small surprise', settle:'Finding his rhythm' };
function applyState(incoming, fromCache = false) {
  if (!incoming || typeof incoming.organism_id !== 'string' || !Array.isArray(incoming.nodes) || !incoming.position) return;
  if (!fromCache && state && incoming.organism_id === state.organism_id && Number(incoming.revision) < Number(state.revision)) return;
  state = incoming;
  snapshotTime = fromCache ? snapshotTime : Date.now();
  if (!fromCache) {
    authenticated = true;
    localAccessRequired = false;
    lastFrameAt = Date.now();
    const time = epoch(state.server_time);
    if (time) serverOffset = time - Date.now();
    safeWrite('terminus.snapshot.v1', { state, receivedAt: snapshotTime });
    const runtime = state.runtime || {};
    setConnection('online', runtime.status === 'degraded' ? (runtime.last_tick_error || runtime.clock_error ? 'Core recovering' : 'Storage retrying') : 'In sync');
    ui.localAccess.hidden = true;
    ui.note.textContent = runtime.status === 'degraded' ? 'The core is recovering · see the inspector' : 'One organism · one local state';
    $('#sync-detail').textContent = preferences.inspector ? `Synced · revision ${state.revision ?? '—'}` : 'Your windows share one state';
  }
  ui.creature.dataset.behavior = String(state.behavior || 'idle');
  if (!dragging) placeCreature(state.position);
  $('#behavior-label').textContent = BEHAVIORS[state.behavior] || String(state.behavior || 'Quietly here');
  $('#context-count').textContent = `${state.nodes.length} ${state.nodes.length === 1 ? 'context' : 'contexts'}`;
  $('#organism-id').textContent = 'ONE CONTINUOUS LIFE';
  $('#organism-id').title = state.organism_id;
  const deviceCount = Array.isArray(state.devices) ? state.devices.length : 0;
  $('#device-count').textContent = `${deviceCount} ${deviceCount === 1 ? 'device' : 'devices'}`;
  renderNodes();
  renderEvents();
  renderInspector();
  renderUtterance(fromCache);
  if (refineLoaded) ui.sprite.src = '/assets/terminus-refined.png';
  if (!fromCache) { flushEvents(); maybePresence(); }
}
function placeCreature(position) {
  const x = clamp(position.x, .04, .96);
  const y = clamp(position.y, .06, .94);
  ui.creature.style.left = `${x * 100}%`;
  ui.creature.style.top = `${y * 100}%`;
  ui.utterance.style.left = `calc(${x * 100}% + ${dimensions.width < 700 ? 38 : 58}px)`;
  ui.utterance.style.top = `calc(${y * 100}% - ${dimensions.width < 700 ? 70 : 91}px)`;
}
function renderNodes() {
  const present = new Set();
  for (const node of state.nodes) {
    const nodeId = String(node.id);
    present.add(nodeId);
    let element = [...ui.nodes.children].find(child => child.dataset.id === nodeId);
    if (!element) {
      element = document.createElement('button');
      element.className = 'context-node';
      element.dataset.id = nodeId;
      element.type = 'button';
      element.append(glyph(NODE_GLYPHS[nodeId] ?? 2));
      const label = document.createElement('span');
      label.className = 'node-label';
      element.append(label);
      element.addEventListener('click', () => {
        openDrawer();
        $('#context-input').value = String(node.label || node.id).slice(0, 80);
        $('#context-input').focus();
      });
      ui.nodes.append(element);
    }
    element.style.left = `${clamp(node.x, .04, .96) * 100}%`;
    element.style.top = `${clamp(node.y, .06, .94) * 100}%`;
    element.style.setProperty('--a', clamp(node.activation));
    element.classList.toggle('is-attention', state.attention === node.id);
    element.classList.toggle('kind-git', node.kind === 'git');
    element.querySelector('.node-label').textContent = node.label || node.id;
    element.setAttribute('aria-label', `${node.label || node.id}. Open context input.`);
    element.title = preferences.inspector ? `${node.label || node.id} · activation ${clamp(node.activation).toFixed(2)} · familiarity ${clamp(node.familiarity).toFixed(2)}` : String(node.label || node.id);
  }
  for (const element of [...ui.nodes.children]) if (!present.has(element.dataset.id)) element.remove();
}
function renderUtterance(fromCache) {
  const utterance = state.utterance;
  if (!utterance || !utterance.id || fromCache) return;
  if (utterance.id === lastUtteranceId) return;
  lastUtteranceId = utterance.id;
  clearTimeout(utteranceTimer);
  ui.utterance.replaceChildren();
  const glyphs = Array.isArray(utterance.glyphs) ? utterance.glyphs.filter(id => Number.isInteger(id) && id >= 0 && id < 20).slice(0, 6) : [];
  if (glyphs.length) for (const id of glyphs) ui.utterance.append(glyph(id));
  else if (utterance.text) {
    const phonemes = document.createElement('span');
    phonemes.className = 'phonemes';
    phonemes.textContent = String(utterance.text).slice(0, 40);
    ui.utterance.append(phonemes);
  }
  if (!ui.utterance.childElementCount) return;
  const createdAt = epoch(utterance.created_at);
  if (createdAt && Date.now() + serverOffset - createdAt > 15000) return;
  ui.utterance.setAttribute('aria-label', 'Terminus made a small symbolic utterance');
  ui.utterance.classList.add('visible');
  utteranceTimer = setTimeout(() => ui.utterance.classList.remove('visible'), 8000);
}
function renderEvents() {
  const events = Array.isArray(state?.recent_events) ? state.recent_events.slice(-18).reverse() : [];
  $('#event-count').textContent = String(events.length);
  const list = $('#event-list');
  list.replaceChildren();
  if (!events.length) {
    const li = document.createElement('li');
    li.className = 'empty-state';
    li.textContent = 'A quiet beginning. Introduce a context or say hello.';
    list.append(li);
    return;
  }
  for (const event of events) {
    const item = document.createElement('li');
    const top = document.createElement('div');
    top.className = 'event-topline';
    const label = document.createElement('span');
    label.className = 'event-context';
    label.textContent = event.context || ({poke:'A gentle hello',drag:'A change of place',presence:'A window opened'}[event.kind]) || event.kind;
    const time = document.createElement('span');
    time.className = 'event-age';
    time.textContent = age(event.timestamp);
    top.append(label, time);
    const kind = document.createElement('span');
    kind.className = 'event-kind';
    kind.textContent = [event.kind, event.source || '', event.historical ? 'earlier observation' : '', event.device_id === deviceId ? 'this window' : ''].filter(Boolean).join(' · ');
    item.append(top, kind);
    list.append(item);
  }
}
function renderInspector() {
  $('#inspector-section').hidden = !preferences.inspector;
  if (!preferences.inspector || !state) return;
  const learning = state.learning || {};
  const metrics = [
    ['Events seen', learning.events_seen], ['Online updates', learning.updates],
    ['Loss', learning.loss], ['Prediction error', learning.prediction_error],
  ];
  const grid = $('#learning-metrics');
  grid.replaceChildren();
  for (const [label, value] of metrics) {
    const box = document.createElement('div'); box.className = 'metric';
    const figure = document.createElement('strong'); figure.textContent = value == null ? '—' : Number.isInteger(value) ? value.toLocaleString() : Number.isFinite(Number(value)) ? Number(value).toFixed(4) : String(value);
    const caption = document.createElement('span'); caption.textContent = label;
    box.append(figure, caption); grid.append(box);
  }
  const bars = $('#latent-bars'); bars.replaceChildren();
  for (const [key, value] of Object.entries(state.latent || {})) {
    const row = document.createElement('div'); row.className = 'latent-bar';
    const label = document.createElement('span'); label.textContent = key.replaceAll('_', ' ');
    const track = document.createElement('div'); track.className = 'latent-track';
    const fill = document.createElement('div'); fill.className = 'latent-fill'; fill.style.setProperty('--value', `${clamp(value) * 100}%`); track.append(fill);
    const amount = document.createElement('span'); amount.className = 'latent-value'; amount.textContent = clamp(value).toFixed(2);
    row.append(label, track, amount); bars.append(row);
  }
  const edges = state.edges || [];
  $('#state-provenance').textContent = JSON.stringify({organism_id:state.organism_id,revision:state.revision,server_time:state.server_time,model:learning.model,initialized:learning.initialized,device_id:deviceId,traits:state.traits,motives:state.motives,gesture:state.gesture,motion:state.motion,attention:state.attention_detail,runtime:state.runtime,graph:{scaffold_edges:edges.filter(edge => edge.origin === 'scaffold').length,learned_edges:edges.filter(edge => edge.origin === 'learned').length,unspecified_edges:edges.filter(edge => !edge.origin).length},...(inspectResult ? {inspect:inspectResult} : {})}, null, 2);
}
async function fetchInspection() {
  if (!preferences.inspector || !authenticated || !connected || inspectRequest) return;
  inspectRequest = fetch('/api/inspect', {cache:'no-store'}).then(async response => {
    if (response.ok) { inspectResult = await response.json(); renderInspector(); }
  }).catch(() => {}).finally(() => { inspectRequest = null; });
  await inspectRequest;
}

async function bootstrap() {
  const generation = ++bootstrapGeneration;
  clearTimeout(retryTimer);
  if (!navigator.onLine) { setConnection('offline', 'Offline · saved view'); scheduleReconnect(); return; }
  try {
    let response = await fetch('/api/state', {cache:'no-store',signal:AbortSignal.timeout(8000)});
    if (generation !== bootstrapGeneration || !navigator.onLine) return;
    if (response.status === 401) {
      const localPair = await fetch('/api/pair-local', {method:'POST',signal:AbortSignal.timeout(8000)});
      if (generation !== bootstrapGeneration || !navigator.onLine) return;
      if (localPair.ok) response = await fetch('/api/state', {cache:'no-store',signal:AbortSignal.timeout(8000)});
      else if (localPair.status !== 403 && localPair.status !== 404) throw new Error(`Local session returned ${localPair.status}`);
      if (generation !== bootstrapGeneration || !navigator.onLine) return;
      if (response.status === 401) {
        requireLocalAccess();
        return;
      }
    }
    if (!response.ok) throw new Error(`Server returned ${response.status}`);
    const incoming = await response.json();
    if (generation !== bootstrapGeneration || !navigator.onLine) return;
    applyState(incoming);
    connectSocket();
    fetchInspection();
  } catch {
    if (generation !== bootstrapGeneration) return;
    setConnection(navigator.onLine ? 'waiting' : 'offline', state ? 'Reconnecting · saved view' : 'Waiting for server');
    scheduleReconnect();
  }
}
function connectSocket() {
  if (socket && [WebSocket.CONNECTING, WebSocket.OPEN].includes(socket.readyState)) return;
  const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
  socket = new WebSocket(`${protocol}//${location.host}/ws`);
  const current = socket;
  current.addEventListener('message', event => {
    if (socket !== current || !navigator.onLine || localAccessRequired) return;
    try { applyState(JSON.parse(event.data)); retryCount = 0; } catch { /* Ignore malformed frames. */ }
  });
  current.addEventListener('close', () => {
    if (socket !== current) return;
    socket = null;
    setConnection(navigator.onLine ? 'waiting' : 'offline', 'Reconnecting · saved view');
    scheduleReconnect();
  });
  current.addEventListener('error', () => current.close());
}
function requireLocalAccess() {
  ++bootstrapGeneration;
  authenticated = false;
  localAccessRequired = true;
  const oldSocket = socket;
  socket = null;
  oldSocket?.close();
  clearTimeout(retryTimer);
  setConnection('waiting','Local access only');
  ui.localAccess.hidden = false;
}
function scheduleReconnect() {
  clearTimeout(retryTimer);
  retryTimer = setTimeout(bootstrap, Math.min(15000, 1200 * 1.6 ** Math.min(retryCount++, 8)) + Math.random() * 500);
}
async function postEvent(event) {
  const response = await fetch('/api/events', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(event),signal:AbortSignal.timeout(7000)});
  if (!response.ok) {
    const error = new Error(`Event returned ${response.status}`); error.status = response.status; throw error;
  }
  return response.json();
}
function maybePresence() {
  if (!authenticated || !connected || !navigator.onLine || document.hidden || Date.now() - lastPresenceAttempt < 5 * 60 * 1000) return;
  // Real visibility of this browser is a live observation, never a queued action.
  // Attempt at most once per five minutes, including across socket reconnects.
  lastPresenceAttempt = Date.now();
  postEvent({id:uuid(),kind:'presence',device_id:deviceId,context:'habitat window',intensity:.12,source:'live',timestamp:Date.now()/1000}).catch(() => {});
}
function bufferEvent(event) {
  const buffered = eventBuffer();
  if (buffered.length >= BUFFER_LIMIT) { toast('The waiting-event buffer is full. Reconnect before offering more.'); return false; }
  buffered.push({...event,organismId:state?.organism_id,queuedAt:Date.now()});
  writeBuffer(buffered);
  updateBufferLabel();
  toast(bufferStorageFailed ? 'Kept in this window for reconnect. Keep this window open until delivered.' : 'Saved for reconnect. The local organism has not changed yet.');
  return true;
}
async function offerEvent(kind, context, extra = {}) {
  const event = {id:uuid(),kind,device_id:deviceId,context:String(context || '').slice(0,80),intensity:kind === 'poke' ? .45 : .35,source:'manual',timestamp:Date.now()/1000,...extra};
  if (localAccessRequired || !state) { toast('Connect to the local core before offering an event.'); if(navigator.onLine) ui.localAccess.hidden = false; return false; }
  if (!authenticated || !connected || !navigator.onLine) return bufferEvent(event);
  try {
    const result = await postEvent(event);
    if (result.accepted && kind === 'context') toast('A new moment entered the habitat.');
    if (result.accepted && kind === 'poke' && !reducedMotion) {
      ui.creature.classList.remove('poked'); void ui.creature.offsetWidth; ui.creature.classList.add('poked');
      setTimeout(() => ui.creature.classList.remove('poked'), 650);
    }
    return true;
  } catch (error) {
    if (error.status === 401) { requireLocalAccess(); toast('Reconnect to the local core to continue.'); return false; }
    if (error.status && error.status < 500 && error.status !== 429) { toast('The server could not accept that event.'); return false; }
    setConnection('waiting','Reconnecting · saved view');
    scheduleReconnect();
    return bufferEvent(event);
  }
}
async function flushEvents() {
  if (flushing || localAccessRequired || !connected || !authenticated || !navigator.onLine || Date.now() < replayAfter) return;
  const queue = eventBuffer();
  if (!queue.length) return;
  flushing = true;
  let delivered = 0;
  try {
    for (const item of queue) {
      if (!connected) break;
      if (item.organismId && item.organismId !== state?.organism_id) {
        writeBuffer(eventBuffer().filter(pending => pending.id !== item.id));
        continue;
      }
      const {queuedAt, organismId, ...event} = item;
      if (!Number.isFinite(event.timestamp)) event.timestamp = queuedAt / 1000;
      try {
        await postEvent(event);
        writeBuffer(eventBuffer().filter(pending => pending.id !== item.id));
        delivered++;
      } catch (error) {
        if (error.status === 401) { requireLocalAccess(); break; }
        if ([400,403,422].includes(error.status)) writeBuffer(eventBuffer().filter(pending => pending.id !== item.id));
        else { replayAfter = Date.now() + (error.status === 429 ? 65000 : 5000); break; }
      }
    }
  } finally {
    flushing = false;
    updateBufferLabel();
    if (delivered) toast(`${delivered} waiting ${delivered === 1 ? 'moment reached' : 'moments reached'} the habitat.`);
  }
}

function openDrawer() {
  ui.drawer.inert = false;
  ui.drawer.classList.add('open');
  $('#drawer-backdrop').hidden = false;
  $('#observatory-button').setAttribute('aria-expanded','true');
  closeSettings();
  fetchInspection();
}
function closeDrawer() {
  ui.drawer.classList.remove('open');
  ui.drawer.inert = true;
  $('#drawer-backdrop').hidden = true;
  $('#observatory-button').setAttribute('aria-expanded','false');
}
function closeSettings() { ui.settings.hidden = true; $('#settings-button').setAttribute('aria-expanded','false'); }
function applyPreferences() {
  document.body.classList.toggle('less-motion',reducedMotion);
  document.body.classList.toggle('more-motion',preferences.reducedMotion === false);
  $('#motion-toggle').checked = reducedMotion;
  $('#inspector-toggle').checked = !!preferences.inspector;
  renderInspector();
  if(state) $('#sync-detail').textContent = preferences.inspector && connected ? `Synced · revision ${state.revision ?? '—'}` : connected ? 'Your local windows show one state' : 'Saved view · server state has not changed here';
  safeWrite('terminus.preferences',preferences);
}
$('#observatory-button').addEventListener('click',() => ui.drawer.classList.contains('open') ? closeDrawer() : openDrawer());
$('#close-observatory').addEventListener('click',() => { closeDrawer(); $('#observatory-button').focus(); });
$('#drawer-backdrop').addEventListener('click',closeDrawer);
$('#context-shortcut').addEventListener('click',() => { openDrawer(); $('#context-input').focus(); });
$('#settings-button').addEventListener('click',() => { const open = ui.settings.hidden; ui.settings.hidden = !open; $('#settings-button').setAttribute('aria-expanded',String(open)); if(open) closeDrawer(); });
$('#close-settings').addEventListener('click',() => { closeSettings(); $('#settings-button').focus(); });
$('#inspector-toggle').addEventListener('change',event => { preferences.inspector = event.target.checked; applyPreferences(); if(preferences.inspector){openDrawer();fetchInspection();} });
$('#motion-toggle').addEventListener('change',event => { preferences.reducedMotion = event.target.checked; reducedMotion = event.target.checked; applyPreferences(); });
document.addEventListener('keydown',event => { if(event.key === 'Escape'){closeDrawer();closeSettings();} });
document.addEventListener('pointerdown',event => { if(!ui.settings.hidden && !ui.settings.contains(event.target) && !$('#settings-button').contains(event.target)) closeSettings(); });
$('#context-form').addEventListener('submit',async event => {
  event.preventDefault();
  const input = $('#context-input');
  const context = input.value.trim();
  if (!context) return;
  const button = event.currentTarget.querySelector('button');
  button.disabled = true;
  if (await offerEvent('context',context)) input.value = '';
  button.disabled = false;
});
$('#retry-local').addEventListener('click',bootstrap);

ui.creature.addEventListener('pointerdown',event => {
  if (!state || localAccessRequired || event.button !== 0 || dragging) return;
  dragging = {id:event.pointerId,startX:event.clientX,startY:event.clientY,startPosition:{...state.position},active:false};
  ui.creature.setPointerCapture(event.pointerId);
});
ui.creature.addEventListener('pointermove',event => {
  if (!dragging || dragging.id !== event.pointerId) return;
  const distance = Math.hypot(event.clientX - dragging.startX,event.clientY - dragging.startY);
  if (!dragging.active && distance < 7) return;
  dragging.active = true;
  ui.creature.classList.add('dragging');
  const rect = ui.habitat.getBoundingClientRect();
  dragging.position = {x:clamp((event.clientX - rect.left) / rect.width,.06,.94),y:clamp((event.clientY - rect.top) / rect.height,.10,.87)};
  placeCreature(dragging.position);
});
async function releasePointer(event, cancelled = false) {
  if (!dragging || dragging.id !== event.pointerId) return;
  const gesture = dragging;
  dragging = null;
  ui.creature.classList.remove('dragging');
  if (ui.creature.hasPointerCapture(event.pointerId)) ui.creature.releasePointerCapture(event.pointerId);
  if (cancelled) { if(state) placeCreature(state.position); return; }
  if (gesture.active && gesture.position) {
    await offerEvent('drag','A change of place',gesture.position);
    if (state) placeCreature(state.position);
  } else await offerEvent('poke','A gentle hello');
}
ui.creature.addEventListener('pointerup',event => releasePointer(event));
ui.creature.addEventListener('pointercancel',event => releasePointer(event,true));
ui.creature.addEventListener('lostpointercapture',event => { if(dragging?.id === event.pointerId) releasePointer(event,true); });
ui.creature.addEventListener('keydown',event => {
  if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); offerEvent('poke','A gentle hello'); }
  if (!state || localAccessRequired || !['ArrowUp','ArrowDown','ArrowLeft','ArrowRight'].includes(event.key)) return;
  event.preventDefault();
  const position = {...state.position};
  position.x = clamp(position.x + (event.key === 'ArrowLeft' ? -.035 : event.key === 'ArrowRight' ? .035 : 0),.06,.94);
  position.y = clamp(position.y + (event.key === 'ArrowUp' ? -.035 : event.key === 'ArrowDown' ? .035 : 0),.1,.87);
  offerEvent('drag','A change of place',position);
});
window.addEventListener('offline',() => { ++bootstrapGeneration; setConnection('offline','Offline · saved view'); socket?.close(); });
window.addEventListener('online',bootstrap);
window.addEventListener('pageshow',event => { if(event.persisted) bootstrap(); });
document.addEventListener('visibilitychange',() => { if(!document.hidden && authenticated) bootstrap(); });
window.addEventListener('storage',event => {
  if (event.key === BUFFER_KEY) updateBufferLabel();
  if (event.key === 'terminus.preferences') { preferences = safeRead('terminus.preferences',{}); reducedMotion = motionPreference(); applyPreferences(); }
});
systemMotion.addEventListener('change',() => { reducedMotion = motionPreference(); applyPreferences(); });

// Ambient motion is a rendering of server state, never a local behavior model.
const context = ui.field.getContext('2d');
function resize() {
  const rect = ui.habitat.getBoundingClientRect();
  dimensions = {width:rect.width,height:rect.height,ratio:Math.min(window.devicePixelRatio || 1,2)};
  ui.field.width = dimensions.width * dimensions.ratio;
  ui.field.height = dimensions.height * dimensions.ratio;
  context.setTransform(dimensions.ratio,0,0,dimensions.ratio,0,0);
  if (state && !dragging) placeCreature(state.position);
}
new ResizeObserver(resize).observe(ui.habitat);
function drawField(milliseconds) {
  const {width,height} = dimensions;
  context.clearRect(0,0,width,height);
  const seconds = reducedMotion || !connected ? 0 : milliseconds / 1000;
  if (state) {
    const nodeMap = new Map(state.nodes.map(node => [node.id,node]));
    for (const edge of (state.edges || [])) {
      const from = nodeMap.get(edge.source), to = nodeMap.get(edge.target);
      if (!from || !to) continue;
      const ax = clamp(from.x,.04,.96)*width, ay = clamp(from.y,.06,.94)*height;
      const bx = clamp(to.x,.04,.96)*width, by = clamp(to.y,.06,.94)*height;
      const bend = (hash(`${edge.source}:${edge.target}`) % 2 ? 1 : -1) * Math.min(38,Math.hypot(ax-bx,ay-by)*.12);
      const cx = (ax+bx)/2 + (by-ay)/Math.max(1,Math.hypot(ax-bx,ay-by))*bend;
      const cy = (ay+by)/2 - (bx-ax)/Math.max(1,Math.hypot(ax-bx,ay-by))*bend;
      const activation = (clamp(from.activation)+clamp(to.activation))/2;
      const weight = clamp(edge.weight);
      const scaffold = edge.origin === 'scaffold';
      context.beginPath();context.moveTo(ax,ay);context.quadraticCurveTo(cx,cy,bx,by);
      context.strokeStyle = `rgba(125,165,149,${(scaffold ? .20 : .28)+weight*.26+activation*.20})`;
      context.lineWidth = (scaffold ? .45 : .6)+weight*.65;context.stroke();
      if (activation > .08) {
        const progress = reducedMotion || !connected ? .5 : (seconds*(.035+activation*.055)+(hash(edge.source)%101)/101)%1;
        const px = (1-progress)**2*ax+2*(1-progress)*progress*cx+progress**2*bx;
        const py = (1-progress)**2*ay+2*(1-progress)*progress*cy+progress**2*by;
        context.beginPath();context.arc(px,py,1+activation,0,Math.PI*2);context.fillStyle=`rgba(177,203,165,${.2+activation*.5})`;context.shadowColor='#a2c8ab';context.shadowBlur=7;context.fill();context.shadowBlur=0;
      }
    }
    const attention = nodeMap.get(state.attention);
    if (attention) {
      const x = clamp(attention.x)*width,y=clamp(attention.y)*height;
      const p = state.position;
      context.beginPath();context.moveTo(p.x*width,p.y*height);context.quadraticCurveTo((p.x*width+x)/2,(p.y*height+y)/2-25,x,y);context.setLineDash([2,8]);context.strokeStyle=`rgba(154,187,158,${.14+clamp(attention.activation)*.20})`;context.lineWidth=.6;context.stroke();context.setLineDash([]);
    }
    // Tendril poses reflect the current latent state and actual attention target.
    const curiosity = clamp(state.latent?.curiosity), agitation = clamp(state.latent?.agitation);
    const wave = Math.sin(seconds*(.5+agitation))*3;
    const direction = attention ? clamp(attention.x)-clamp(state.position.x) : 0;
    $('#tendril-left').setAttribute('d',`M112 162 C${65+direction*20} ${170-wave-curiosity*10} ${79-wave} ${211-curiosity*13} 39 ${212+wave}`);
    $('#tendril-right').setAttribute('d',`M190 166 C${229+wave} ${162+curiosity*9} ${217+direction*20} ${213+wave} 260 ${207-wave}`);
    $('#tendril-upper').setAttribute('d',`M172 91 C${213+direction*10} ${56-wave} 223 ${88-curiosity*15} 246 ${61+wave}`);
    ui.creature.style.setProperty('--attention-x',`${direction*5}px`);
  }
  requestAnimationFrame(drawField);
}
const refined = new Image();
refined.addEventListener('load',() => { refineLoaded = true; ui.sprite.src = '/assets/terminus-refined.png'; ui.creature.classList.add('refined-art'); ui.creature.classList.toggle('sleep-art-ready',sleepArtLoaded); });
refined.src = '/assets/terminus-refined.png';
const sleepArt = new Image();
sleepArt.addEventListener('load',() => {
  sleepArtLoaded = true;
  $('#sleep-sprite').src = '/assets/terminus-sleep.png';
  ui.creature.classList.toggle('sleep-art-ready',refineLoaded);
});
sleepArt.src = '/assets/terminus-sleep.png';
ui.sprite.addEventListener('error',() => { if(ui.sprite.getAttribute('src') !== '/assets/idle.gif') ui.sprite.src = '/assets/idle.gif'; });
applyPreferences();
const snapshot = safeRead('terminus.snapshot.v1',null);
if (snapshot?.state && snapshot.receivedAt) { snapshotTime = snapshot.receivedAt; applyState(snapshot.state,true); setConnection('waiting','Reconnecting · saved view'); }
resize();
requestAnimationFrame(drawField);
bootstrap();
setInterval(() => {
  if (state) renderEvents();
  if (connected && Date.now()-lastFrameAt > 20000) { socket?.close(); setConnection('waiting','Checking connection'); bootstrap(); }
  if (preferences.inspector && ui.drawer.classList.contains('open')) fetchInspection();
  updateBufferLabel();
  maybePresence();
},10000);
if ('serviceWorker' in navigator) navigator.serviceWorker.register('/service-worker.js').catch(() => {});
