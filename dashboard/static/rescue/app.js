// Mission-control UI: drives the deterministic simulation through /api/rescue and renders its state.
import { RescueScene, toV } from './scene.js';

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const scene = new RescueScene($('c'));
let running = false, speed = 5, msgCount = 0, state = null, stat = null, busy = false, lastWall = performance.now(), lastTicks = 0, tickRate = 0;
let reportPending = false;
const STEP_MS = 100;
const TIMELINE = [['START', 'Drone search'], ['SURVIVOR', 'Survivor observation'], ['MAP', 'Shared map update'], ['ASSIGN', 'Rover assignment'],
  ['ROUTE', 'Route planning'], ['OBSTACLE', 'Obstacle encounter'], ['REROUTE', 'Replanning'], ['REACHED', 'Rescue approach']];
let reached = new Set();
const WHO = { 'AIR-1': 'var(--air)', 'GND-1': 'var(--gnd)', COORD: '#c9d3de', SIM: 'var(--amber)', OPERATOR: 'var(--green)' };

async function api(path, body) {
  const r = await fetch(path, body === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  if (!r.ok) throw new Error(`${path}: ${r.status}`);
  return r.json();
}

async function loadScenarios() {
  const list = await api('/api/rescue/scenarios');
  $('scenario').innerHTML = list.map(s => `<option value="${s.key}" data-sum="${esc(s.summary)}">${esc(s.title)}  ·  ${esc(s.env.replace('_', ' '))}</option>`).join('');
  const want = new URLSearchParams(location.search).get('scenario');
  if (want) $('scenario').value = want.toUpperCase();
}

async function reset() {
  running = false; setRunBtn();
  const body = { scenario: $('scenario').value, mode: $('mode').value, planner: $('planner').value };
  const r = await api('/api/rescue/reset', body);
  stat = r.static; msgCount = 0; reached = new Set(); $('log').innerHTML = ''; $('toast').innerHTML = '';
  scene.buildEnvironment(stat); scene.curr = null; applyState(r.state, true);
  $('summary').textContent = stat.scenario.summary + (stat.scenario.judge_notes?.length ? '  —  ' + stat.scenario.judge_notes.join(' · ') : '');
  $('title').textContent = `${stat.scenario.title} · ${stat.environment.label} · seed ${stat.scenario.seed} · ${stat.scenario.mode}`;
  $('qText').textContent = ''; $('dText').textContent = ''; $('qStatus').textContent = 'No report yet.';
}

function setRunBtn() { $('bStart').classList.toggle('on', running); $('bPause').classList.toggle('on', !running); }

async function stepLoop() {
  if (running && !busy) {
    busy = true;
    try {
      const st = await api('/api/rescue/step', { sim_s: speed * STEP_MS / 1000, truth: scene.layers.truth, since: msgCount });
      applyState(st, false);
      if (st.done) { running = false; setRunBtn(); onDone(); }
    } catch (e) { console.error(e); running = false; setRunBtn(); }
    busy = false;
  }
  setTimeout(stepLoop, STEP_MS);
}

function onDone() {
  toast(`Mission ended: ${state.phase.replaceAll('_', ' ')}`, 'var(--green)');
  if (!reportPending) requestReport();
}

function applyState(st, fresh) {
  const now = performance.now();
  if (st.ticks !== undefined) { const dw = (now - lastWall) / 1000; if (dw > 0.5) { tickRate = (st.ticks - lastTicks) / dw; lastTicks = st.ticks; lastWall = now; } }
  state = st; scene.setState(st, now);
  const newMsgs = (st.messages || []);
  msgCount = st.messages_total;
  for (const m of newMsgs) { logMsg(m); react(m, st); }
  renderPanels(st);
}

function logMsg(m) {
  const d = document.createElement('div'); d.className = 'msg';
  d.innerHTML = `<span class="t">${m.t.toFixed(1)}</span><span class="who"><span style="color:${WHO[m.from] || '#ccc'}">${esc(m.from)}</span> → <span style="color:${WHO[m.to] || '#ccc'}">${esc(m.to)}</span></span><span><b>${esc(m.type)}</b> ${esc(m.text)}${m.refs?.length ? ` <span style="color:var(--dim)">[${m.refs.map(esc).join(', ')}]</span>` : ''}</span>`;
  const log = $('log'); log.prepend(d); while (log.children.length > 300) log.lastChild.remove();
}

function react(m, st) {
  const tl = { START: 'START', SURVIVOR: 'SURVIVOR', CORRIDOR: 'MAP', DEBRIS: 'MAP', ASSIGN: 'ASSIGN', OBSTACLE: 'OBSTACLE', REROUTE: 'REROUTE', REACHED: 'REACHED' }[m.type];
  if (tl) { reached.add(tl); if (tl === 'ASSIGN') reached.add('ROUTE'); }
  const cand = (st.candidates || []).find(c => m.text.includes(c.cand_id));
  const rover = [st.rover.x, st.rover.y];
  const big = { SURVIVOR: ['var(--air)', cand?.xy], ASSIGN: ['var(--gnd)', rover], OBSTACLE: ['var(--red)', rover], REROUTE: ['var(--gnd)', rover],
    REACHED: ['var(--green)', rover], FAULT: ['var(--red)', rover], INSUFFICIENT_INFORMATION: ['var(--amber)', rover], UNREACHABLE: ['var(--red)', rover],
    NO_PERSON: ['var(--amber)', rover], REQUEST_SENSING: ['var(--amber)', rover], AGENT_TIMEOUT: ['var(--red)', [st.drone.x, st.drone.y]], EVENT: ['var(--amber)', null], LINK: ['var(--red)', rover] }[m.type];
  if (big) {
    if (m.type !== 'SURVIVOR' || m.text.startsWith('LIKELY') || m.text.startsWith('POSSIBLE')) toast(`${m.from}: ${m.text}`.slice(0, 150), big[0]);
    if (big[1]) scene.cinematic(big[1], m.type);
  }
}

function toast(text, color) {
  const d = document.createElement('div'); d.textContent = text; d.style.borderColor = color; d.style.color = color;
  const t = $('toast'); t.appendChild(d); while (t.children.length > 3) t.firstChild.remove(); setTimeout(() => d.remove(), 6200);
}

const kv = (rows) => rows.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${v}</dd>`).join('');
const pill = (s) => { const c = /BLOCK|FAULT|SAFE_STOP|UNREACH|LOST/.test(s) ? 't-red' : /UNKNOWN|INSUFF|HOLD|STAGE|WAIT|OPERATOR|OBSTRUCT/.test(s) ? 't-amb' : /STANDOFF|COMPLETE|ARRIVED/.test(s) ? 't-real' : 't-gnd'; return `<span class="tag ${c}">${esc(s)}</span>`; };

function renderPanels(st) {
  $('clock').textContent = `T+${st.t.toFixed(1)} s`;
  $('phase').innerHTML = esc(st.phase.replaceAll('_', ' ')); $('ovPhase').textContent = st.phase.replaceAll('_', ' ');
  $('ovDetail').textContent = st.phase_detail;
  const L = st.links;
  $('links').innerHTML = `<i style="background:${L['AIR-1'] ? 'var(--air)' : 'var(--red)'}"></i>AIR-1 link <i style="background:${L['GND-1'] ? 'var(--gnd)' : 'var(--red)'};margin-left:.6em"></i>GND-1 link`;
  const d = st.drone, r = st.rover;
  $('air').innerHTML = kv([['Mode', pill(d.mode)], ['Planner', esc(d.planner)], ['Position', `(${d.x.toFixed(1)}, ${d.y.toFixed(1)}) m · ${d.alt_m} m alt`],
    ['Sensor', `${d.sensor} · ${d.footprint_m} m footprint · PoD ${d.pod}`], ['Sector PoS', `${(d.sector_pos * 100).toFixed(0)} %`], ['Looks · path', `${d.looks} · ${d.distance_m} m`],
    ['Candidates', d.candidates.length], ['Task', d.task ? esc(d.task.task_id || d.task.type) : '—']]);
  $('airWhy').textContent = 'Why: ' + d.why;
  const route = r.route && r.route.status === 'OK' ? `${r.route.path.join('-')} (${r.route.length_m} m)` : (r.route ? r.route.status : '—');
  $('gnd').innerHTML = kv([['State', pill(r.state)], ['Destination', esc(r.destination || '—')], ['Route', esc(route)], ['Replans', r.reroutes.length],
    ['Odometer', `${r.odometer_m} m (sim)`], ['Range', r.latest_range ? `${r.latest_range.status} ${r.latest_range.range_m ?? ''} (sim ultrasonic)` : '—'],
    ['Safety', r.latched ? pill(r.latched) : 'supervisor OK'], ['Collisions', r.collision ? pill('COLLISION ' + r.collision) : '0']]);
  $('gndWhy').textContent = r.detail ? 'Navigator: ' + r.detail : '';
  // targets & ranking
  const rk = (st.ranking || []).map(x => `<div>${pill('RANK ' + x.rank)} ${esc(x.why)} <span style="color:var(--dim)">[${esc(x.obs_ids.slice(-1)[0])}]</span></div>`);
  const tg = (st.targets || []).map(x => `<div><b>${esc(x.cand_id)}</b> → ${esc(x.dest)} ${pill(x.status)} ${x.route_m ? `${x.route_m} m` : ''} ${x.reason ? `<span class="why">${esc(x.reason)}</span>` : ''}</div>`);
  const cd = (st.candidates || []).filter(c => !(st.targets || []).some(t => t.cand_id === c.cand_id)).map(c => `<div>${esc(c.cand_id)} ${pill(c.status)} conf ${c.confidence.toFixed(2)} · motion ${esc(c.motion)} · ${esc(c.room || 'no room')}</div>`);
  $('targets').innerHTML = (tg.join('') + rk.join('') + cd.join('')) || '<div class="why">No survivor candidate yet. The drone reports a candidate only when one falls inside its footprint.</div>';
  // operator request
  const op = (st.operator_requests || []).find(q => q.state === 'PENDING');
  $('opCard').style.display = op ? '' : 'none'; if (op) { $('opText').textContent = op.text; $('bProbe').dataset.req = op.id; }
  // observations
  $('obs').innerHTML = (st.observations || []).slice(-30).reverse().map(o => {
    const air = o.agent === 'AIR-1'; const what = o.kind === 'survivor_candidate' ? `${o.status} survivor ${o.cand_id} conf ${o.confidence}` :
      o.kind === 'corridor_state' ? `corridor ${o.edge} ${o.status}` : o.kind === 'debris' ? `debris ${o.edge}` : `${o.kind} ${o.edge || ''} ${o.status || ''}`;
    return `<div><span class="tag ${air ? 't-air' : 't-gnd'}">${air ? 'SIM AIR' : 'SIM GND'}</span> <span style="color:var(--dim)">${esc(o.obs_id)} t=${Number(o.t).toFixed(1)}</span> ${esc(what)}</div>`;
  }).join('');
  // timeline
  const order = TIMELINE.map(([k]) => k); let last = -1; order.forEach((k, i) => { if (reached.has(k)) last = i; });
  $('timeline').innerHTML = TIMELINE.map(([k, label], i) => `<div class="step ${reached.has(k) ? 'done' : ''} ${i === last + 1 && running ? 'now' : ''}">${label}</div>`).join('');
  // map
  const counts = {}; for (const e of st.edges) counts[e.status] = (counts[e.status] || 0) + 1;
  $('mapkv').innerHTML = kv([['Corridors', st.edges.length], ['Routable (fresh)', st.routable.length], ['Clear (aerial)', counts.CLEAR || 0], ['Traversed', counts.TRAVERSED || 0],
    ['Blocked', `${(st.blocked || []).join(', ') || 0}`], ['Unknown', counts.UNKNOWN || 0], ['Occluded', counts.OCCLUDED || 0], ['Stale', (st.stale || []).length],
    ['Observations', st.observations_total], ['Rejected inputs', (st.rejected || []).length], ['Drone obs buffered', L.drone_buffered_obs]]);
  $('scouts').innerHTML = (st.scouts || []).slice().reverse().map(s => `<div>${pill(s.done ? 'DONE' : 'ACTIVE')} ${esc(s.task_id)} ${esc(s.reason)} ${s.result ? `<span class="why">${esc(typeof s.result === 'string' ? s.result : Object.entries(s.result).map(([k, v]) => k + ' ' + v).join(', '))}</span>` : ''}</div>`).join('') || '<div class="why">none</div>';
  if (st.report) showReport(st.report);
}

function showReport(rep) {
  $('qStatus').innerHTML = `${esc(rep.qwen_status)} <span class="tag t-ai">authority: NONE</span>`;
  const q = rep.qwen;
  $('qText').innerHTML = q ? `<b style="color:var(--ai)">Qwen (${esc(q.model_id || '')}, ${esc(q.config || '')}):</b> ${esc(q.explanation)}\n<b>Suggested next observation:</b> ${esc(q.suggested_next_observation)}` +
    `\n<span style="color:var(--dim)">cited ids: ${esc((q.provenance?.cited_ids || []).join(', ') || 'none')}${q.provenance?.unknown_ids?.length ? ' · UNKNOWN ids: ' + esc(q.provenance.unknown_ids.join(', ')) : ''} · ${q.inference_latency_ms ?? ''} ms</span>` : '';
  $('dText').innerHTML = `<b>${rep.qwen ? 'Deterministic summary' : 'DETERMINISTIC REPORT (fallback)'}:</b> ${esc(rep.deterministic.text)}`;
  reportPending = String(rep.qwen_status).startsWith('PENDING');
}

async function requestReport() {
  reportPending = true; $('qStatus').textContent = 'Building report…';
  const rep = await api('/api/rescue/report', { qwen: true }); showReport(rep);
  for (let i = 0; i < 40 && reportPending; i++) { await new Promise(r => setTimeout(r, 1500)); showReport(await api('/api/rescue/report')); }
}

async function loadEvidence() {
  try {
    const ev = await api('/api/rescue/evidence'); $('evLabel').textContent = ev.label;
    $('evFrames').innerHTML = ev.frames.length ? ev.frames.slice(0, 3).map(f => `<div style="margin-top:.4em"><img loading="lazy" src="${f.url}" alt="recorded frame"><div class="why">${esc(f.name)}</div></div>`).join('')
      : `<div class="why">${ev.dir_configured ? 'No recorded frames found.' : 'Not configured (start with --rescue-evidence-dir).'}</div>`;
  } catch { $('evLabel').textContent = 'evidence endpoint unavailable'; }
}

// labels projected from the 3D scene
function updateLabels() {
  const host = $('labels'); if (!scene.layers.labels || !state) { host.innerHTML = ''; return; }
  const items = [];
  if (scene.dronePos) items.push([scene.dronePos.clone().setY(scene.dronePos.y + 1.6), `AIR-1 · ${state.drone.mode}`, 'var(--air)']);
  if (scene.roverPos) items.push([scene.roverPos.clone().setY(2.4), `GND-1 · ${state.rover.state.replaceAll('_', ' ')}`, state.rover.latched ? 'var(--red)' : 'var(--gnd)']);
  for (const m of scene.candMeshes.values()) if (m.visible) items.push([m.position.clone().setY(7.6), m.userData.label, '#' + m.userData.col.toString(16).padStart(6, '0')]);
  for (const m of scene.debrisMeshes.values()) items.push([m.position.clone().setY(2.2), m.userData.label, m.userData.src === 'truth' ? '#8a96a3' : 'var(--red)']);
  let html = '';
  for (const [v, text, col] of items) { const p = scene.project(v); if (!p.on) continue; html += `<div class="lbl" style="left:${p.x}px;top:${p.y}px;color:${col};border-color:${col}55">${esc(text)}</div>`; }
  host.innerHTML = html;
}

let perfT = 0;
function frame() {
  scene.frame(); updateLabels();
  const now = performance.now();
  if (now - perfT > 500) {
    perfT = now; const p = scene.perf();
    if (p) $('perf').innerHTML = `<div><b>${p.fps.toFixed(0)}</b> FPS · avg <b>${p.avg.toFixed(1)}</b> ms · p95 <b>${p.p95.toFixed(1)}</b> ms</div>
      <div>draw calls <b>${p.calls}</b> · triangles <b>${(p.tris / 1000).toFixed(0)}k</b></div>
      <div>render <b>${p.res[0]}×${p.res[1]}</b> · scale ${p.scale.toFixed(2)} · preset ${p.preset}</div>
      <div>sim tick rate <b>${tickRate.toFixed(0)}</b> ticks/s (dt 0.05 s, ×${speed})</div>
      <div style="color:var(--dim)">GPU: ${esc(p.gpu)}</div>
      <div style="color:var(--dim);margin-top:.4em">All robot motion is SIMULATED. Distances are synthetic metres.</div>`;
    window.__perf = p;
  }
  requestAnimationFrame(frame);
}

// controls
$('bStart').onclick = () => { if (state?.done) return toast('Mission finished — press Reset', 'var(--amber)'); running = true; setRunBtn(); };
$('bPause').onclick = () => { running = false; setRunBtn(); };
$('bReset').onclick = () => reset();
$('scenario').onchange = () => reset(); $('mode').onchange = () => reset(); $('planner').onchange = () => reset();
$('speed').onchange = (e) => speed = Number(e.target.value);
$('bObstacle').onclick = async () => { const r = await api('/api/rescue/obstacle', {}); toast(r.ok ? `Debris ${r.debris} dropped on ${r.edge} (agents not told)` : r.reason, r.ok ? 'var(--amber)' : 'var(--red)'); };
$('bReport').onclick = () => requestReport();
$('bProbe').onclick = async (e) => { const r = await api('/api/rescue/approve_probe', { req_id: e.target.dataset.req, operator: 'demo-operator' }); toast(`Probe approved: ${r.edges.join(', ')}`, 'var(--amber)'); };
$('quality').onchange = (e) => scene.setQuality(e.target.value);
$('auto').onchange = (e) => { scene.autoScale = e.target.checked; if (!e.target.checked) { scene.renderScale = 1; scene.resize(); } };
for (const cb of document.querySelectorAll('[data-l]')) cb.onchange = () => { scene.layers[cb.dataset.l] = cb.checked; if (state) { scene._updateKnowledge(state); } if (cb.dataset.l === 'truth') api(`/api/rescue/state?truth=${cb.checked ? 1 : 0}`).then(s => { state = s; scene.curr = s; scene._updateKnowledge(s); }); };
for (const b of document.querySelectorAll('[data-cam]')) b.onclick = () => { document.querySelectorAll('[data-cam]').forEach(x => x.classList.remove('on')); b.classList.add('on'); scene.setCamera(b.dataset.cam); };
const app = $('app');
const relayout = () => setTimeout(() => scene.resize(), 30);
$('bLeft').onclick = () => { app.classList.toggle('noleft'); relayout(); };
$('bRight').onclick = () => { app.classList.toggle('noright'); relayout(); };
$('bBottom').onclick = () => { app.classList.toggle('nobottom'); relayout(); };
function present() { const on = !document.body.classList.contains('present'); document.body.classList.toggle('present', on);
  app.classList.toggle('noleft', on); app.classList.toggle('noright', on); app.classList.toggle('nobottom', on);
  scene.setCamera(on ? 'cinematic' : 'tactical'); document.querySelectorAll('[data-cam]').forEach(x => x.classList.toggle('on', x.dataset.cam === (on ? 'cinematic' : 'tactical'))); relayout(); }
$('bPresent').onclick = present;
$('bFull').onclick = () => document.fullscreenElement ? document.exitFullscreen() : document.documentElement.requestFullscreen();
document.addEventListener('fullscreenchange', relayout);
document.addEventListener('keydown', (e) => {
  if (e.target.tagName === 'SELECT') return;
  if (e.key === ' ') { e.preventDefault(); running ? $('bPause').click() : $('bStart').click(); }
  if (e.key === 'p' || e.key === 'P') present(); if (e.key === 'f' || e.key === 'F') $('bFull').click(); if (e.key === 'r' || e.key === 'R') reset();
  const cams = ['tactical', 'cinematic', 'aerial', 'ground', 'onboard', 'topdown', 'free']; const i = Number(e.key) - 1;
  if (i >= 0 && i < cams.length) document.querySelector(`[data-cam="${cams[i]}"]`).click();
});

(async () => {
  const q = new URLSearchParams(location.search);
  scene.setQuality(q.get('quality') || 'high');
  if (q.get('quality')) $('quality').value = q.get('quality');
  if (q.get('speed')) { speed = Number(q.get('speed')); $('speed').value = q.get('speed'); }
  await loadScenarios(); await reset(); loadEvidence();
  if (q.get('cam')) document.querySelector(`[data-cam="${q.get('cam')}"]`)?.click();
  if (q.get('present')) present();
  if (q.get('autostart')) { running = true; setRunBtn(); }
  requestAnimationFrame(frame); stepLoop();
  window.__rescue = { scene, get state() { return state; }, get running() { return running; } };
})();
