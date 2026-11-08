// TEAM-15 rescue digital twin — Three.js renderer.
// Draws ONLY what the simulation state says. Motion between two simulation snapshots is interpolated for
// smoothness; nothing here decides routes, discoveries, collisions or safety events.
import * as THREE from 'three';
import { OrbitControls } from './vendor/three/OrbitControls.js';

const C = {
  air: 0x35d0e0, gnd: 0x4c8dff, amber: 0xf2b33d, red: 0xef5350, green: 0x4cc38a, ai: 0xa48bd8,
  grey: 0x5a6675, white: 0xe8edf3,
};
const SITE = 48, HALF = 24;
export const toV = (x, y, h = 0) => new THREE.Vector3(x - HALF, h, HALF - y);

// ---------------------------------------------------------------- deterministic RNG (decor only)
function mulberry(seed) { let a = seed >>> 0; return () => { a |= 0; a = a + 0x6D2B79F5 | 0; let t = Math.imul(a ^ a >>> 15, 1 | a); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; }; }

// ---------------------------------------------------------------- themes
const THEMES = {
  urban: { name: 'Urban earthquake', sky: 0x1a222c, fog: 0x2a2f33, fogD: 0.010, sun: 0xffe2b8, sunI: 2.6, hemiS: 0x9fb4c8, hemiG: 0x3a3127, hemiI: 0.75,
    ground: ['#55575a', '#626467', '#4a4b4d'], corridor: '#8a847c', wall: 0x9b9184, wallH: [1.3, 3.0], fill: false, rubble: 0x7f756a },
  warehouse: { name: 'Industrial warehouse', sky: 0x161b22, fog: 0x1f252c, fogD: 0.012, sun: 0xdfe8ff, sunI: 1.6, hemiS: 0xcad6e6, hemiG: 0x2a2d31, hemiI: 1.0,
    ground: ['#6a6d70', '#75787a', '#5f6264'], corridor: '#8d9093', wall: 0x2f6db5, wallH: [2.6, 3.0], fill: true, rack: true, rubble: 0x8a6a3a },
  corridors: { name: 'Collapsed indoor corridors', sky: 0x12161c, fog: 0x1a1e24, fogD: 0.018, sun: 0xe6ecff, sunI: 1.2, hemiS: 0xb8c4d4, hemiG: 0x24272b, hemiI: 0.8,
    ground: ['#6d7176', '#777b80', '#63676c'], corridor: '#9aa0a6', wall: 0xc9ccc8, wallH: [2.2, 2.4], fill: false, rubble: 0x9a958c },
  outdoor: { name: 'Outdoor search field', sky: 0x2a3a4a, fog: 0x4a5a60, fogD: 0.007, sun: 0xfff1d6, sunI: 3.0, hemiS: 0xbcd6ee, hemiG: 0x3d4a2a, hemiI: 0.9,
    ground: ['#3f5a2c', '#4a6a33', '#35502a'], corridor: '#7d6a4f', wall: 0x5d6b3a, wallH: [0, 0], fill: false, trees: true, rubble: 0x77736a },
  maze: { name: 'Maze-like ruins', sky: 0x1b2027, fog: 0x2a2d30, fogD: 0.012, sun: 0xffd9a8, sunI: 2.2, hemiS: 0xaab8c6, hemiG: 0x352f28, hemiI: 0.8,
    ground: ['#5c5750', '#666058', '#524e48'], corridor: '#857d72', wall: 0x8a8174, wallH: [1.8, 2.4], fill: false, rubble: 0x7a7066 },
};

function noiseTexture(colors, seed, opts = {}) {
  const S = opts.size || 512, cv = document.createElement('canvas'); cv.width = cv.height = S;
  const g = cv.getContext('2d'), r = mulberry(seed);
  g.fillStyle = colors[0]; g.fillRect(0, 0, S, S);
  for (let i = 0; i < (opts.blobs || 900); i++) {
    g.fillStyle = colors[1 + (i % (colors.length - 1))]; g.globalAlpha = 0.08 + r() * 0.18;
    const s = 2 + r() * (opts.blob || 22); g.fillRect(r() * S, r() * S, s, s * (0.4 + r()));
  }
  g.globalAlpha = 1;
  if (opts.cracks) { g.strokeStyle = 'rgba(15,15,15,0.55)'; g.lineWidth = 1.4;
    for (let i = 0; i < opts.cracks; i++) { let x = r() * S, y = r() * S; g.beginPath(); g.moveTo(x, y);
      for (let k = 0; k < 7; k++) { x += (r() - 0.5) * 40; y += (r() - 0.5) * 40; g.lineTo(x, y); } g.stroke(); } }
  if (opts.tiles) { g.strokeStyle = 'rgba(0,0,0,0.18)'; g.lineWidth = 1; const n = opts.tiles;
    for (let i = 0; i <= n; i++) { g.beginPath(); g.moveTo(i * S / n, 0); g.lineTo(i * S / n, S); g.stroke(); g.beginPath(); g.moveTo(0, i * S / n); g.lineTo(S, i * S / n); g.stroke(); } }
  const t = new THREE.CanvasTexture(cv); t.colorSpace = THREE.SRGBColorSpace; t.wrapS = t.wrapT = THREE.RepeatWrapping;
  t.anisotropy = 8; return t;
}

function hatchTexture(hex, alpha = 0.55) {
  const S = 64, cv = document.createElement('canvas'); cv.width = cv.height = S; const g = cv.getContext('2d');
  g.strokeStyle = hex; g.globalAlpha = alpha; g.lineWidth = 9;
  for (let i = -S; i < 2 * S; i += 22) { g.beginPath(); g.moveTo(i, 0); g.lineTo(i + S, S); g.stroke(); }
  const t = new THREE.CanvasTexture(cv); t.wrapS = t.wrapT = THREE.RepeatWrapping; t.colorSpace = THREE.SRGBColorSpace; return t;
}

function segDist(px, py, ax, ay, bx, by) {
  const dx = bx - ax, dy = by - ay, L2 = dx * dx + dy * dy || 1e-9;
  const f = Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / L2));
  return Math.hypot(px - (ax + f * dx), py - (ay + f * dy));
}

// ---------------------------------------------------------------- robot models (not to scale: x2.2)
export const MODEL_SCALE = 2.2;
function droneModel() {
  const g = new THREE.Group();
  const dark = new THREE.MeshStandardMaterial({ color: 0x1d232b, metalness: 0.55, roughness: 0.38 });
  const shell = new THREE.MeshStandardMaterial({ color: 0xd9dee5, metalness: 0.25, roughness: 0.42 });
  const accent = new THREE.MeshStandardMaterial({ color: C.air, emissive: C.air, emissiveIntensity: 0.6 });
  const body = new THREE.Mesh(new THREE.BoxGeometry(0.34, 0.11, 0.22), shell); body.castShadow = true; g.add(body);
  const top = new THREE.Mesh(new THREE.BoxGeometry(0.22, 0.05, 0.16), dark); top.position.y = 0.08; g.add(top);
  const strip = new THREE.Mesh(new THREE.BoxGeometry(0.02, 0.02, 0.18), accent); strip.position.set(0.172, 0.0, 0); g.add(strip);
  g.userData.props = [];
  for (let k = 0; k < 4; k++) {
    const a = Math.PI / 4 + k * Math.PI / 2, ax = Math.cos(a) * 0.26, az = Math.sin(a) * 0.26;
    const arm = new THREE.Mesh(new THREE.BoxGeometry(0.30, 0.025, 0.035), dark);
    arm.position.set(ax / 2, 0.02, az / 2); arm.rotation.y = -a; arm.castShadow = true; g.add(arm);
    const motor = new THREE.Mesh(new THREE.CylinderGeometry(0.035, 0.04, 0.06, 16), dark); motor.position.set(ax, 0.045, az); g.add(motor);
    const prop = new THREE.Group(); prop.position.set(ax, 0.085, az);
    const blade = new THREE.Mesh(new THREE.BoxGeometry(0.24, 0.004, 0.025), new THREE.MeshStandardMaterial({ color: 0x0f1216, roughness: 0.6 }));
    prop.add(blade); const b2 = blade.clone(); b2.rotation.y = Math.PI / 2; prop.add(b2);
    const disc = new THREE.Mesh(new THREE.CircleGeometry(0.125, 28), new THREE.MeshBasicMaterial({ color: 0x9aa7b5, transparent: true, opacity: 0.16, depthWrite: false }));
    disc.rotation.x = -Math.PI / 2; disc.position.y = 0.002; prop.add(disc); g.add(prop); g.userData.props.push(prop);
    const led = new THREE.Mesh(new THREE.SphereGeometry(0.013, 8, 8), new THREE.MeshBasicMaterial({ color: k < 2 ? 0x34e07a : 0xff3b3b }));
    led.position.set(ax, 0.02, az); g.add(led);
    const leg = new THREE.Mesh(new THREE.CylinderGeometry(0.006, 0.006, 0.13, 6), dark); leg.position.set(Math.cos(a) * 0.12, -0.11, Math.sin(a) * 0.09); g.add(leg);
  }
  const gimbal = new THREE.Mesh(new THREE.SphereGeometry(0.045, 16, 12), dark); gimbal.position.set(0.11, -0.08, 0); g.add(gimbal);
  const lens = new THREE.Mesh(new THREE.CylinderGeometry(0.02, 0.02, 0.02, 12), new THREE.MeshStandardMaterial({ color: 0x0b2a3a, emissive: C.air, emissiveIntensity: 0.4 }));
  lens.rotation.z = Math.PI / 2; lens.position.set(0.155, -0.085, 0); g.add(lens);
  const strobe = new THREE.Mesh(new THREE.SphereGeometry(0.016, 8, 8), new THREE.MeshBasicMaterial({ color: 0xffffff }));
  strobe.position.set(-0.1, 0.11, 0); g.add(strobe); g.userData.strobe = strobe;
  g.scale.setScalar(MODEL_SCALE * 1.4);
  return g;
}

function mecanumTexture() {
  const cv = document.createElement('canvas'); cv.width = 128; cv.height = 32; const g = cv.getContext('2d');
  g.fillStyle = '#1b1f24'; g.fillRect(0, 0, 128, 32); g.strokeStyle = '#7b848f'; g.lineWidth = 5;
  for (let i = -32; i < 160; i += 16) { g.beginPath(); g.moveTo(i, 0); g.lineTo(i + 24, 32); g.stroke(); }
  const t = new THREE.CanvasTexture(cv); t.wrapS = t.wrapT = THREE.RepeatWrapping; t.colorSpace = THREE.SRGBColorSpace; return t;
}

function labelTexture(text, fg = '#e8edf3', bg = '#111821') {
  const cv = document.createElement('canvas'); cv.width = 256; cv.height = 64; const g = cv.getContext('2d');
  g.fillStyle = bg; g.fillRect(0, 0, 256, 64); g.fillStyle = fg; g.font = '600 34px Inter, system-ui, sans-serif';
  g.textAlign = 'center'; g.textBaseline = 'middle'; g.fillText(text, 128, 34);
  const t = new THREE.CanvasTexture(cv); t.colorSpace = THREE.SRGBColorSpace; return t;
}

function roverModel() {
  const g = new THREE.Group();
  const chassisM = new THREE.MeshStandardMaterial({ color: 0x2b3440, metalness: 0.4, roughness: 0.45 });
  const plate = new THREE.MeshStandardMaterial({ color: 0xe3e7ec, metalness: 0.15, roughness: 0.5 });
  const blue = new THREE.MeshStandardMaterial({ color: C.gnd, emissive: C.gnd, emissiveIntensity: 0.7 });
  const red = new THREE.MeshStandardMaterial({ color: C.red, emissive: C.red, emissiveIntensity: 0.6 });
  const ch = new THREE.Mesh(new THREE.BoxGeometry(0.42, 0.08, 0.26), chassisM); ch.position.y = 0.09; ch.castShadow = true; g.add(ch);
  const top = new THREE.Mesh(new THREE.BoxGeometry(0.30, 0.012, 0.22), new THREE.MeshStandardMaterial({ map: labelTexture('GND-1', '#0b0f14', '#e3e7ec') }));
  top.position.set(-0.02, 0.137, 0); g.add(top);
  const box = new THREE.Mesh(new THREE.BoxGeometry(0.16, 0.06, 0.16), plate); box.position.set(-0.06, 0.16, 0); box.castShadow = true; g.add(box);
  const mast = new THREE.Mesh(new THREE.CylinderGeometry(0.008, 0.008, 0.12, 8), chassisM); mast.position.set(0.14, 0.19, 0); g.add(mast);
  const cam = new THREE.Mesh(new THREE.BoxGeometry(0.035, 0.03, 0.05), chassisM); cam.position.set(0.155, 0.25, 0); g.add(cam);
  const lens = new THREE.Mesh(new THREE.CylinderGeometry(0.011, 0.011, 0.01, 12), new THREE.MeshStandardMaterial({ color: 0x0a1a2a, emissive: C.gnd, emissiveIntensity: 0.5 }));
  lens.rotation.z = Math.PI / 2; lens.position.set(0.175, 0.25, 0); g.add(lens);
  const front = new THREE.Mesh(new THREE.BoxGeometry(0.01, 0.02, 0.2), blue); front.position.set(0.212, 0.1, 0); g.add(front);
  const rear = new THREE.Mesh(new THREE.BoxGeometry(0.01, 0.02, 0.2), red); rear.position.set(-0.212, 0.1, 0); g.add(rear);
  const wheelM = new THREE.MeshStandardMaterial({ map: mecanumTexture(), roughness: 0.8, metalness: 0.2 });
  g.userData.wheels = [];
  for (const [x, z] of [[0.14, 0.16], [0.14, -0.16], [-0.14, 0.16], [-0.14, -0.16]]) {
    const w = new THREE.Mesh(new THREE.CylinderGeometry(0.06, 0.06, 0.05, 20), wheelM);
    w.rotation.x = Math.PI / 2; w.position.set(x, 0.06, z); w.castShadow = true; g.add(w); g.userData.wheels.push({ mesh: w, side: z > 0 ? 1 : -1 });
  }
  const halo = new THREE.Mesh(new THREE.RingGeometry(0.42, 0.5, 40), new THREE.MeshBasicMaterial({ color: C.red, transparent: true, opacity: 0, side: THREE.DoubleSide, depthWrite: false }));
  halo.rotation.x = -Math.PI / 2; halo.position.y = 0.02; g.add(halo); g.userData.halo = halo;
  g.scale.setScalar(MODEL_SCALE * 1.6);
  return g;
}

function personModel(lying) {
  const g = new THREE.Group(); const m = new THREE.MeshStandardMaterial({ color: 0xd98c5f, roughness: 0.7 });
  const cloth = new THREE.MeshStandardMaterial({ color: 0x3d5a80, roughness: 0.8 });
  const torso = new THREE.Mesh(new THREE.CapsuleGeometry(0.16, 0.5, 4, 10), cloth); torso.position.y = 0.95; g.add(torso);
  const head = new THREE.Mesh(new THREE.SphereGeometry(0.12, 14, 12), m); head.position.y = 1.42; g.add(head);
  for (const s of [-1, 1]) { const leg = new THREE.Mesh(new THREE.CapsuleGeometry(0.07, 0.55, 4, 8), cloth); leg.position.set(0, 0.38, s * 0.09); g.add(leg); }
  if (lying) { g.rotation.z = Math.PI / 2; g.position.y = 0.18; }
  g.traverse(o => { if (o.isMesh) o.castShadow = true; });
  return g;
}

// ---------------------------------------------------------------- scene
export class RescueScene {
  constructor(canvas, hud) {
    this.canvas = canvas; this.hud = hud;
    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true, powerPreference: 'high-performance' });
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping; this.renderer.toneMappingExposure = 1.25;
    this.renderer.shadowMap.enabled = true; this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(42, 1, 0.1, 600);
    this.camera.position.set(-38, 52, 52);
    this.controls = new OrbitControls(this.camera, canvas); this.controls.enableDamping = true; this.controls.maxPolarAngle = Math.PI * 0.49;
    this.controls.target.set(0, 0, 0); this.controls.enabled = false;
    this.camMode = 'tactical'; this.camGoal = { pos: new THREE.Vector3(-38, 52, 52), look: new THREE.Vector3() };
    this.lookNow = new THREE.Vector3(); this.cine = null;
    this.layers = { routes: true, coverage: true, uncertainty: false, aerial: true, ground: true, shared: true, truth: false, labels: true };
    this.quality = 'high'; this.renderScale = 1; this.autoScale = true;
    this.frameTimes = []; this.lastFrame = performance.now(); this.t0 = performance.now();
    this.world = new THREE.Group(); this.dyn = new THREE.Group(); this.scene.add(this.world, this.dyn);
    this.drone = droneModel(); this.rover = roverModel(); this.scene.add(this.drone, this.rover);
    this.prev = null; this.curr = null; this.recvT = 0; this.interval = 100;
    this._buildLights(); this.labels = new Map();
    this.debrisMeshes = new Map(); this.candMeshes = new Map(); this.truthMeshes = [];
    this.wheelPhase = 0; this.lastRover = null; this.lastDroneV = new THREE.Vector3();
    window.addEventListener('resize', () => this.resize()); this.resize();
  }

  _buildLights() {
    this.hemi = new THREE.HemisphereLight(0xffffff, 0x333333, 0.8); this.scene.add(this.hemi);
    this.sun = new THREE.DirectionalLight(0xffffff, 2.5); this.sun.position.set(-30, 60, 25); this.sun.castShadow = true;
    const sc = this.sun.shadow.camera; sc.left = -40; sc.right = 40; sc.top = 40; sc.bottom = -40; sc.near = 1; sc.far = 160;
    this.sun.shadow.bias = -0.0004; this.sun.shadow.normalBias = 0.02; this.scene.add(this.sun, this.sun.target);
  }

  setQuality(q) {
    this.quality = q;
    const pr = window.devicePixelRatio || 1;
    const base = { low: 0.75, medium: 1.0, high: Math.min(pr, 1.5), ultra: Math.min(pr, 2.0) }[q] || 1;
    this.basePR = base; this.renderer.shadowMap.enabled = q !== 'low';
    const sz = { low: 512, medium: 1024, high: 2048, ultra: 4096 }[q];
    this.sun.shadow.mapSize.set(sz, sz); if (this.sun.shadow.map) { this.sun.shadow.map.dispose(); this.sun.shadow.map = null; }
    this.scene.fog = (q === 'low' || !this.theme) ? null : new THREE.FogExp2(this.theme.fog, this.theme.fogD);
    this.resize();
    if (this.static) this.buildEnvironment(this.static);
  }

  resize() {
    const r = this.canvas.parentElement.getBoundingClientRect();
    const pr = (this.basePR || 1) * this.renderScale;
    this.renderer.setPixelRatio(pr); this.renderer.setSize(r.width, r.height, false);
    this.camera.aspect = r.width / Math.max(1, r.height); this.camera.updateProjectionMatrix();
    this.resolution = [Math.round(r.width * pr), Math.round(r.height * pr)];
  }

  // ------------------------------------------------------------ environment from the layout
  buildEnvironment(st) {
    this.static = st;
    const th = this.theme = THEMES[st.environment.theme] || THEMES.urban;
    const rnd = mulberry(1234 + (st.scenario.seed || 0));
    for (const grp of [this.world]) { while (grp.children.length) { const o = grp.children.pop(); o.traverse?.(n => { n.geometry?.dispose?.(); }); } }
    this.scene.background = new THREE.Color(th.sky);
    this.scene.fog = this.quality === 'low' ? null : new THREE.FogExp2(th.fog, th.fogD);
    this.hemi.color.setHex(th.hemiS); this.hemi.groundColor.setHex(th.hemiG); this.hemi.intensity = th.hemiI;
    this.sun.color.setHex(th.sun); this.sun.intensity = th.sunI;
    const q = this.quality, dense = { low: 0.35, medium: 0.6, high: 1, ultra: 1.4 }[q];
    // ground
    const gtex = noiseTexture(th.ground, 7, { cracks: th === THEMES.urban ? 60 : 0, tiles: th === THEMES.corridors ? 32 : 0, blob: th === THEMES.outdoor ? 30 : 14 });
    gtex.repeat.set(6, 6);
    const ground = new THREE.Mesh(new THREE.PlaneGeometry(160, 160), new THREE.MeshStandardMaterial({ map: gtex, roughness: 0.95, metalness: 0.02 }));
    ground.rotation.x = -Math.PI / 2; ground.receiveShadow = true; this.world.add(ground);
    // site outline and grid (2 m cells, 10 m major)
    const grid = new THREE.GridHelper(SITE, 24, 0x445566, 0x2a3440); grid.position.y = 0.012;
    grid.material.transparent = true; grid.material.opacity = 0.22; this.world.add(grid);
    const outline = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.BoxGeometry(SITE, 0.01, SITE)), new THREE.LineBasicMaterial({ color: 0x8aa0b8, transparent: true, opacity: 0.5 }));
    outline.position.y = 0.02; this.world.add(outline);
    // corridor floors
    const half = st.environment.corridor_half_m, ctex = noiseTexture([th.corridor, '#00000020', '#ffffff18'], 3, { blobs: 500, blob: 8 });
    const cmat = new THREE.MeshStandardMaterial({ map: ctex, roughness: 0.9 });
    const segs = [];
    for (const e of st.edges) {
      const [ax, ay] = st.nodes[e.a], [bx, by] = st.nodes[e.b]; segs.push([ax, ay, bx, by]);
      const L = Math.hypot(bx - ax, by - ay), w = e.spur ? Math.max(1.0, half * 1.2) : Math.max(1.2, half * 2);
      const m = new THREE.Mesh(new THREE.PlaneGeometry(L + w, w), cmat); m.rotation.x = -Math.PI / 2;
      m.rotation.z = Math.atan2(by - ay, bx - ax); m.position.copy(toV((ax + bx) / 2, (ay + by) / 2, 0.006)); m.receiveShadow = true; this.world.add(m);
    }
    // occupancy at 1 m: free = near a corridor, a junction or a room pocket
    const free = (x, y) => {
      for (const [ax, ay, bx, by] of segs) if (segDist(x, y, ax, ay, bx, by) <= Math.max(0.9, half) + 0.45) return true;
      for (const r of st.rooms) if (Math.hypot(x - r.xy[0], y - r.xy[1]) <= 2.2) return true;
      return false;
    };
    const occ = []; for (let i = 0; i < SITE; i++) { occ.push([]); for (let j = 0; j < SITE; j++) occ[i].push(!free(j + 0.5, i + 0.5)); }
    const isOcc = (i, j) => i >= 0 && j >= 0 && i < SITE && j < SITE && occ[i][j];
    const cells = [];
    for (let i = 0; i < SITE; i++) for (let j = 0; j < SITE; j++) {
      if (!occ[i][j]) continue;
      const boundary = !isOcc(i + 1, j) || !isOcc(i - 1, j) || !isOcc(i, j + 1) || !isOcc(i, j - 1);
      if (th.fill || boundary) cells.push([i, j, boundary]);
    }
    const dummy = new THREE.Object3D();
    if (th === THEMES.outdoor) {
      this._trees(st, occ, rnd, dense);
    } else if (cells.length) {
      const wallTex = noiseTexture(['#' + th.wall.toString(16).padStart(6, '0'), '#00000030', '#ffffff20'], 11, { blobs: 700, blob: 10 });
      const mat = new THREE.MeshStandardMaterial({ map: wallTex, roughness: 0.85, metalness: th.rack ? 0.35 : 0.05 });
      const inst = new THREE.InstancedMesh(new THREE.BoxGeometry(1, 1, 1), mat, cells.length);
      let n = 0; const rubbleSpots = [];
      for (const [i, j, boundary] of cells) {
        let h;
        if (th === THEMES.urban) {
          const ci = Math.floor(i / 4), cj = Math.floor(j / 4), hv = mulberry(ci * 131 + cj * 17 + 5)();
          if (hv < 0.22) { if (boundary && rnd() < 0.35) rubbleSpots.push([j + 0.5, i + 0.5]); continue; }   // collapsed block
          h = th.wallH[0] + hv * (th.wallH[1] - th.wallH[0]) - (rnd() < 0.08 ? 1.2 : 0);
        } else if (th.rack) {
          h = (j % 3 === 1) ? 0.15 : th.wallH[0] + rnd() * 0.3;     // rack rows with gaps
        } else {
          h = th.wallH[0] + rnd() * (th.wallH[1] - th.wallH[0]);
          if (th === THEMES.maze && rnd() < 0.12) h *= 0.55;          // broken wall tops
        }
        dummy.position.copy(toV(j + 0.5, i + 0.5, h / 2)); dummy.scale.set(1, Math.max(0.1, h), 1); dummy.rotation.set(0, 0, 0);
        dummy.updateMatrix(); inst.setMatrixAt(n++, dummy.matrix);
      }
      inst.count = n; inst.castShadow = true; inst.receiveShadow = true; this.world.add(inst);
      this._rubble(rubbleSpots, th.rubble, rnd, 4, 0.45);
      if (th.rack) this._racksDetail(cells, rnd);
    }
    // room pockets
    for (const r of st.rooms) {
      const pad = new THREE.Mesh(new THREE.CircleGeometry(2.0, 36), new THREE.MeshStandardMaterial({ color: 0x3b4450, roughness: 0.9, transparent: true, opacity: 0.6 }));
      pad.rotation.x = -Math.PI / 2; pad.position.copy(toV(r.xy[0], r.xy[1], 0.009)); this.world.add(pad);
    }
    // base / staging zone
    const [bx, by] = st.base;
    const pad = new THREE.Mesh(new THREE.RingGeometry(1.6, 2.1, 48), new THREE.MeshBasicMaterial({ color: C.green, transparent: true, opacity: 0.8, side: THREE.DoubleSide }));
    pad.rotation.x = -Math.PI / 2; pad.position.copy(toV(bx, by, 0.03)); this.world.add(pad);
    const hpad = new THREE.Mesh(new THREE.PlaneGeometry(3.2, 0.8), new THREE.MeshBasicMaterial({ map: labelTexture('STAGING / BASE', '#4cc38a', '#0b0f14'), transparent: true }));
    hpad.rotation.x = -Math.PI / 2; hpad.position.copy(toV(bx, by - 2.8 < 0.5 ? by + 2.8 : by - 2.8, 0.035)); this.world.add(hpad);
    // search sector
    const [sx0, sy0, sx1, sy1] = st.sector;
    const sect = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.PlaneGeometry(sx1 - sx0, sy1 - sy0)), new THREE.LineDashedMaterial({ color: C.air, dashSize: 1.2, gapSize: 0.8, transparent: true, opacity: 0.55 }));
    sect.computeLineDistances(); sect.rotation.x = -Math.PI / 2; sect.position.copy(toV((sx0 + sx1) / 2, (sy0 + sy1) / 2, 0.05)); this.world.add(sect);
    // zones: roof / smoke / canopy / mezzanine
    for (const z of st.zones) {
      const w = z.x1 - z.x0, d = z.y1 - z.y0; if (w <= 0 || d <= 0) continue;
      if (z.vis >= 0.5) { // a hole or open area: outline only
        const o = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.PlaneGeometry(w, d)), new THREE.LineBasicMaterial({ color: C.air, transparent: true, opacity: 0.8 }));
        o.rotation.x = -Math.PI / 2; o.position.copy(toV(z.x0 + w / 2, z.y0 + d / 2, 4.05)); this.world.add(o); continue;
      }
      if (z.label.includes('canopy')) continue;   // drawn as trees
      const smoke = z.label.includes('smoke');
      const slab = new THREE.Mesh(new THREE.BoxGeometry(w, smoke ? 2.6 : 0.18, d), new THREE.MeshStandardMaterial({
        color: smoke ? 0x9aa0a6 : 0x2d3440, transparent: true, opacity: smoke ? 0.22 : 0.55, roughness: 0.9, depthWrite: false }));
      slab.position.copy(toV(z.x0 + w / 2, z.y0 + d / 2, smoke ? 1.4 : (z.label.includes('mezzanine') ? 3.4 : 4.0))); this.world.add(slab);
      const e = new THREE.LineSegments(new THREE.EdgesGeometry(slab.geometry), new THREE.LineBasicMaterial({ color: C.amber, transparent: true, opacity: 0.7 }));
      e.position.copy(slab.position); this.world.add(e);
    }
    // corridor knowledge overlay (shared map) — one strip per edge, recoloured from state
    this.edgeStrips = new Map(); this.hatch = hatchTexture('#f2b33d', 0.6);
    for (const e of st.edges) {
      const [ax, ay] = st.nodes[e.a], [bx2, by2] = st.nodes[e.b]; const L = Math.hypot(bx2 - ax, by2 - ay);
      const m = new THREE.Mesh(new THREE.PlaneGeometry(L, 0.55), new THREE.MeshBasicMaterial({ color: C.amber, transparent: true, opacity: 0.5, depthWrite: false, map: this.hatch }));
      m.material.map.repeat.set(L / 2, 1); m.rotation.x = -Math.PI / 2; m.rotation.z = Math.atan2(by2 - ay, bx2 - ax);
      m.position.copy(toV((ax + bx2) / 2, (ay + by2) / 2, 0.06)); m.renderOrder = 2; this.world.add(m); this.edgeStrips.set(e.edge, m);
    }
    // coverage + uncertainty textures (24 x 24 cells)
    const mkGridTex = () => { const d = new Uint8Array(24 * 24 * 4); const t = new THREE.DataTexture(d, 24, 24, THREE.RGBAFormat); t.magFilter = THREE.NearestFilter; t.needsUpdate = true; return t; };
    this.covTex = mkGridTex(); this.belTex = mkGridTex();
    const plane = (tex, h) => { const m = new THREE.Mesh(new THREE.PlaneGeometry(SITE, SITE), new THREE.MeshBasicMaterial({ map: tex, transparent: true, depthWrite: false }));
      m.rotation.x = -Math.PI / 2; m.position.y = h; m.renderOrder = 1; this.world.add(m); return m; };
    this.covPlane = plane(this.covTex, 0.04); this.belPlane = plane(this.belTex, 0.045);
    this._buildDynamic();
    this.frameCamera(true);
  }

  _trees(st, occ, rnd, dense) {
    const spots = [];
    const inCanopy = (x, y) => st.zones.some(z => z.label.includes('canopy') && x >= z.x0 && x <= z.x1 && y >= z.y0 && y <= z.y1);
    for (let i = 0; i < SITE; i += 1) for (let j = 0; j < SITE; j += 1) {
      if (!occ[i][j]) continue; const x = j + 0.5, y = i + 0.5, p = inCanopy(x, y) ? 0.55 : 0.035;
      if (rnd() < p * dense) spots.push([x + (rnd() - 0.5) * 0.6, y + (rnd() - 0.5) * 0.6, 0.7 + rnd() * 0.6]);
    }
    for (let k = 0; k < 90 * dense; k++) { const x = -40 + rnd() * 128, y = -40 + rnd() * 128; if (x > -2 && x < 50 && y > -2 && y < 50) continue; spots.push([x, y, 0.8 + rnd() * 0.7]); }
    const trunk = new THREE.InstancedMesh(new THREE.CylinderGeometry(0.12, 0.18, 1.6, 7), new THREE.MeshStandardMaterial({ color: 0x4a3a2a, roughness: 0.9 }), spots.length);
    const crown = new THREE.InstancedMesh(new THREE.IcosahedronGeometry(1.3, 1), new THREE.MeshStandardMaterial({ color: 0x3f6b35, roughness: 0.85, flatShading: true }), spots.length);
    const d = new THREE.Object3D(); const col = new THREE.Color();
    spots.forEach(([x, y, s], n) => {
      d.position.copy(toV(x, y, 0.8 * s)); d.scale.setScalar(s); d.rotation.set(0, rnd() * 6, 0); d.updateMatrix(); trunk.setMatrixAt(n, d.matrix);
      d.position.copy(toV(x, y, 2.3 * s)); d.scale.set(s, s * (1.1 + rnd() * 0.4), s); d.updateMatrix(); crown.setMatrixAt(n, d.matrix);
      crown.setColorAt(n, col.setHSL(0.27 + rnd() * 0.06, 0.35 + rnd() * 0.15, 0.24 + rnd() * 0.1));
    });
    trunk.castShadow = crown.castShadow = true; this.world.add(trunk, crown);
    const rocks = []; for (let k = 0; k < 60 * dense; k++) { const x = rnd() * SITE, y = rnd() * SITE; const i = Math.floor(y), j = Math.floor(x); if (occ[i]?.[j]) rocks.push([x, y]); }
    this._rubble(rocks, 0x77736a, rnd, 1, 0.5);
  }

  _racksDetail(cells, rnd) {
    const n = cells.length; const boxes = new THREE.InstancedMesh(new THREE.BoxGeometry(0.7, 0.6, 0.7), new THREE.MeshStandardMaterial({ color: 0xb98b4e, roughness: 0.9 }), n * 2);
    const d = new THREE.Object3D(); let k = 0;
    for (const [i, j] of cells) { if (j % 3 === 1) continue; for (const h of [1.2, 2.9]) { if (rnd() < 0.55) { d.position.copy(toV(j + 0.5, i + 0.5, h)); d.rotation.set(0, rnd() * 0.3, 0); d.scale.setScalar(0.8 + rnd() * 0.3); d.updateMatrix(); boxes.setMatrixAt(k++, d.matrix); } } }
    boxes.count = k; boxes.castShadow = true; this.world.add(boxes);
  }

  _rubble(spots, color, rnd, per, size) {
    if (!spots.length) return;
    const inst = new THREE.InstancedMesh(new THREE.DodecahedronGeometry(1, 0), new THREE.MeshStandardMaterial({ color, roughness: 0.95, flatShading: true }), spots.length * per);
    const d = new THREE.Object3D(); let k = 0;
    for (const [x, y] of spots) for (let p = 0; p < per; p++) {
      const s = size * (0.4 + rnd()); d.position.copy(toV(x + (rnd() - 0.5) * 1.4, y + (rnd() - 0.5) * 1.4, s * 0.45));
      d.rotation.set(rnd() * 3, rnd() * 3, rnd() * 3); d.scale.set(s, s * (0.5 + rnd() * 0.5), s); d.updateMatrix(); inst.setMatrixAt(k++, d.matrix);
    }
    inst.castShadow = true; inst.receiveShadow = true; this.world.add(inst);
  }

  _buildDynamic() {
    while (this.dyn.children.length) this.dyn.remove(this.dyn.children[0]);
    this.debrisMeshes.clear(); this.candMeshes.clear(); this.truthMeshes = [];
    // drone sensor footprint (actual footprint: (2 fov + 1) cells) + frustum
    this.foot = new THREE.Mesh(new THREE.PlaneGeometry(1, 1), new THREE.MeshBasicMaterial({ color: C.air, transparent: true, opacity: 0.13, depthWrite: false }));
    this.foot.rotation.x = -Math.PI / 2; this.foot.renderOrder = 3; this.dyn.add(this.foot);
    this.footEdge = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.PlaneGeometry(1, 1)), new THREE.LineBasicMaterial({ color: C.air, transparent: true, opacity: 0.9 }));
    this.footEdge.rotation.x = -Math.PI / 2; this.dyn.add(this.footEdge);
    this.frustum = new THREE.LineSegments(new THREE.BufferGeometry().setAttribute('position', new THREE.Float32BufferAttribute(new Float32Array(24), 3)),
      new THREE.LineBasicMaterial({ color: C.air, transparent: true, opacity: 0.35 })); this.dyn.add(this.frustum);
    const line = (color, op, w) => { const l = new THREE.Line(new THREE.BufferGeometry(), new THREE.LineBasicMaterial({ color, transparent: true, opacity: op, linewidth: w })); this.dyn.add(l); return l; };
    this.dronePath = line(C.air, 0.7, 1); this.roverPath = line(C.gnd, 0.95, 2);
    // planned route: chevrons along the path
    this.chev = new THREE.InstancedMesh(new THREE.ConeGeometry(0.28, 0.75, 3), new THREE.MeshBasicMaterial({ color: C.gnd, transparent: true, opacity: 0.95 }), 260);
    this.chev.count = 0; this.chev.renderOrder = 4; this.dyn.add(this.chev);
    this.routeLine = line(C.gnd, 0.55, 1);
    this.waypoint = new THREE.Mesh(new THREE.RingGeometry(0.9, 1.15, 40), new THREE.MeshBasicMaterial({ color: C.gnd, transparent: true, opacity: 0.9, side: THREE.DoubleSide }));
    this.waypoint.rotation.x = -Math.PI / 2; this.dyn.add(this.waypoint);
    this.droneTarget = new THREE.Mesh(new THREE.OctahedronGeometry(0.35), new THREE.MeshBasicMaterial({ color: C.air, wireframe: true })); this.dyn.add(this.droneTarget);
    this.droneShadow = new THREE.Mesh(new THREE.CircleGeometry(1.1, 24), new THREE.MeshBasicMaterial({ color: 0x000000, transparent: true, opacity: 0.25, depthWrite: false }));
    this.droneShadow.rotation.x = -Math.PI / 2; this.dyn.add(this.droneShadow);
  }

  // ------------------------------------------------------------ state updates
  setState(st, now) {
    this.prev = this.curr || st; this.curr = st;
    this.interval = Math.max(40, Math.min(400, now - (this.recvT || now - 100))); this.recvT = now;
    this._updateKnowledge(st);
  }

  _edgeColor(e) {
    if (e.status === 'BLOCKED') return [C.red, 0.85, null];
    if (e.status === 'TRAVERSED') return [C.gnd, 0.75, null];
    if (e.status === 'CLEAR') return [C.air, 0.45, null];
    if (e.status === 'PROBE_APPROVED') return [C.amber, 0.8, null];
    if (e.status === 'OCCLUDED') return [0x7a6a4a, 0.55, this.hatch];
    return [C.amber, 0.38, this.hatch];          // UNKNOWN: hatched amber, never drawn as clear
  }

  _updateKnowledge(st) {
    if (!this.static) return;
    const stale = new Set(st.stale || []);
    for (const e of st.edges) {
      const m = this.edgeStrips.get(e.edge); if (!m) continue;
      let [col, op, map] = this._edgeColor(e);
      if (stale.has(e.edge)) { col = C.amber; op = 0.5; map = this.hatch; }
      m.material.color.setHex(col); m.material.opacity = op; if (m.material.map !== map) { m.material.map = map; m.material.needsUpdate = true; }
      m.visible = this.layers.shared;
    }
    // coverage (cyan) + remaining search belief (amber = still uncertain)
    if (st.coverage) {
      const d = this.covTex.image.data, b = this.belTex.image.data;
      for (let i = 0; i < 24; i++) for (let j = 0; j < 24; j++) {
        const k = ((23 - i) * 24 + j) * 4, v = st.coverage[i][j], u = st.belief[i][j];
        d[k] = 53; d[k + 1] = 208; d[k + 2] = 224; d[k + 3] = v ? 34 : 0;
        b[k] = 242; b[k + 1] = 179; b[k + 2] = 61; b[k + 3] = Math.round(Math.min(1, u) * 120);
      }
      this.covTex.needsUpdate = this.belTex.needsUpdate = true;
    }
    this.covPlane.visible = this.layers.coverage; this.belPlane.visible = this.layers.uncertainty;
    // observed debris: aerial (xy) or rover ultrasonic (edge + distance from node)
    const seen = new Map();
    if (this.layers.aerial) for (const o of st.observations || []) if (o.kind === 'debris' && o.xy) seen.set('a:' + o.edge, { xy: o.xy, src: 'air' });
    if (this.layers.ground) for (const o of st.observations || []) if (o.agent === 'GND-1' && o.kind === 'ultrasonic_obstacle' && o.status === 'CONFIRMED' && o.detail?.at_m != null) {
      const [a, b] = o.edge.split('-'); const from = o.detail.at_m_from, to = from === a ? b : a;
      const [x0, y0] = this.static.nodes[from], [x1, y1] = this.static.nodes[to], L = Math.hypot(x1 - x0, y1 - y0), f = Math.min(1, o.detail.at_m / L);
      seen.set('g:' + o.edge, { xy: [x0 + f * (x1 - x0), y0 + f * (y1 - y0)], src: 'gnd' });
    }
    if (this.layers.truth && st.truth) for (const d of st.truth.debris) if (d.present && d.xy) seen.set('t:' + d.id, { xy: d.xy, src: 'truth' });
    for (const [k, v] of seen) if (!this.debrisMeshes.has(k)) this.debrisMeshes.set(k, this._debris(v, k));
    for (const [k, m] of this.debrisMeshes) if (!seen.has(k)) { this.dyn.remove(m); this.debrisMeshes.delete(k); }
    // survivor candidates (shared map) + target state
    const tstat = {}; for (const t of st.targets || []) tstat[t.cand_id] = t.status;
    const cids = new Set();
    for (const c of st.candidates || []) {
      cids.add(c.cand_id); let m = this.candMeshes.get(c.cand_id);
      if (!m) { m = this._candidate(); this.candMeshes.set(c.cand_id, m); }
      m.position.copy(toV(c.xy[0], c.xy[1], 0.08));
      const reached = tstat[c.cand_id] === 'AT_STANDOFF', col = reached ? C.green : c.status === 'LIKELY' ? C.air : C.amber;
      m.children.forEach(ch => ch.material.color.setHex(col)); m.userData.label = `${c.cand_id} ${reached ? 'REACHED (standoff)' : c.status} ${c.confidence.toFixed(2)}`;
      m.userData.col = col; m.visible = this.layers.aerial;
    }
    for (const [k, m] of this.candMeshes) if (!cids.has(k)) { this.dyn.remove(m); this.candMeshes.delete(k); }
    // ground truth (viewer toggle only)
    for (const m of this.truthMeshes) this.dyn.remove(m); this.truthMeshes = [];
    if (this.layers.truth && st.truth) {
      for (const s of st.truth.survivors) { const p = personModel(s.condition !== 'MOVING'); p.position.add(toV(s.xy[0], s.xy[1], 0)); p.scale.setScalar(1.1);
        p.traverse(o => { if (o.isMesh) { o.material = o.material.clone(); o.material.transparent = true; o.material.opacity = 0.75; } }); this.dyn.add(p); this.truthMeshes.push(p); }
      for (const d of st.truth.decoys || []) { const h = new THREE.Mesh(new THREE.SphereGeometry(0.5, 12, 10), new THREE.MeshBasicMaterial({ color: 0xff7a2a, transparent: true, opacity: 0.6 }));
        h.position.copy(toV(d.xy[0], d.xy[1], 0.5)); this.dyn.add(h); this.truthMeshes.push(h); }
    }
    // planned route chevrons (only a route the Navigator actually holds)
    const r = st.rover, pts = [];
    if (this.layers.routes && r.planned && r.planned.length > 1) {
      const path = r.planned; let n = 0; const d = new THREE.Object3D();
      for (let i = 0; i + 1 < path.length; i++) {
        const [ax, ay] = path[i], [bx, by] = path[i + 1], L = Math.hypot(bx - ax, by - ay), ang = Math.atan2(by - ay, bx - ax);
        for (let s = 0.8; s < L && n < 260; s += 1.6) {
          d.position.copy(toV(ax + (bx - ax) * s / L, ay + (by - ay) * s / L, 0.12)); d.rotation.set(-Math.PI / 2, 0, -Math.PI / 2 + ang);
          d.updateMatrix(); this.chev.setMatrixAt(n++, d.matrix);
        }
        pts.push(toV(ax, ay, 0.1)); if (i + 2 === path.length) pts.push(toV(bx, by, 0.1));
      }
      this.chev.count = n; this.chev.instanceMatrix.needsUpdate = true;
      const leg = Math.min(path.length - 1, (r.route_leg || 0) + 1); this.waypoint.position.copy(toV(path[leg][0], path[leg][1], 0.09)); this.waypoint.visible = r.running;
    } else { this.chev.count = 0; this.waypoint.visible = false; }
    this.routeLine.geometry.setFromPoints(pts); this.routeLine.visible = this.layers.routes;
    this.roverPath.geometry.setFromPoints((r.path || []).map(p => toV(p[0], p[1], 0.08))); this.roverPath.visible = this.layers.routes;
    this.dronePath.geometry.setFromPoints((st.drone.path || []).map(p => toV(p[0], p[1], 0.07))); this.dronePath.visible = this.layers.aerial;
  }

  _debris(v, key) {
    const g = new THREE.Group(); const rnd = mulberry(key.length * 977 + Math.round(v.xy[0] * 13 + v.xy[1] * 7));
    const mat = new THREE.MeshStandardMaterial({ color: v.src === 'truth' ? 0x7d7b78 : (this.theme?.rubble || 0x7a7066), roughness: 0.95, flatShading: true,
      transparent: v.src === 'truth', opacity: v.src === 'truth' ? 0.55 : 1 });
    for (let k = 0; k < 7; k++) { const s = 0.25 + rnd() * 0.45; const m = new THREE.Mesh(new THREE.DodecahedronGeometry(s, 0), mat);
      m.position.set((rnd() - 0.5) * 1.6, s * 0.5, (rnd() - 0.5) * 1.6); m.rotation.set(rnd() * 3, rnd() * 3, rnd() * 3); m.castShadow = true; g.add(m); }
    const slab = new THREE.Mesh(new THREE.BoxGeometry(1.8, 0.14, 0.7), mat); slab.position.y = 0.45; slab.rotation.set(0.3, rnd() * 3, 0.2); g.add(slab);
    const ring = new THREE.Mesh(new THREE.RingGeometry(1.3, 1.55, 40), new THREE.MeshBasicMaterial({ color: v.src === 'truth' ? C.grey : C.red, transparent: true, opacity: 0.9, side: THREE.DoubleSide }));
    ring.rotation.x = -Math.PI / 2; ring.position.y = 0.07; g.add(ring);
    g.position.copy(toV(v.xy[0], v.xy[1], 0)); g.userData.born = performance.now(); g.userData.src = v.src; g.userData.label = v.src === 'truth' ? 'GROUND TRUTH debris' : `${v.src === 'air' ? 'AIR-1' : 'GND-1'} debris`;
    this.dyn.add(g); return g;
  }

  _candidate() {
    const g = new THREE.Group();
    const ring = new THREE.Mesh(new THREE.RingGeometry(1.0, 1.25, 48), new THREE.MeshBasicMaterial({ color: C.amber, transparent: true, opacity: 0.95, side: THREE.DoubleSide, depthWrite: false }));
    ring.rotation.x = -Math.PI / 2; g.add(ring);
    const pulse = new THREE.Mesh(new THREE.RingGeometry(1.25, 1.35, 48), new THREE.MeshBasicMaterial({ color: C.amber, transparent: true, opacity: 0.5, side: THREE.DoubleSide, depthWrite: false }));
    pulse.rotation.x = -Math.PI / 2; g.add(pulse); g.userData.pulse = pulse;
    const beam = new THREE.Mesh(new THREE.CylinderGeometry(0.04, 0.04, 7, 8), new THREE.MeshBasicMaterial({ color: C.amber, transparent: true, opacity: 0.35 }));
    beam.position.y = 3.5; g.add(beam);
    this.dyn.add(g); return g;
  }

  // ------------------------------------------------------------ cameras
  setCamera(mode) { this.camMode = mode; this.controls.enabled = mode === 'free'; this.cine = null; if (mode !== 'free') this.frameCamera(false); }
  frameCamera(snap) {
    const goal = this._camGoal();
    if (snap) { this.camera.position.copy(goal.pos); this.lookNow.copy(goal.look); this.camera.lookAt(goal.look); this.controls.target.copy(goal.look); }
  }
  cinematic(xy, label) { if (this.camMode !== 'cinematic') return; this.cine = { xy, until: performance.now() + 5500, label }; }

  _camGoal() {
    const dp = this.dronePos || toV(24, 24, 15), rp = this.roverPos || toV(6, 1, 0);
    switch (this.camMode) {
      case 'topdown': return { pos: new THREE.Vector3(0.01, 78, 0.01), look: new THREE.Vector3(0, 0, 0) };
      case 'aerial': { const h = this.droneHeading || 0, back = new THREE.Vector3(-Math.cos(h) * 13, 9, Math.sin(h) * 13);
        return { pos: dp.clone().add(back), look: dp.clone().add(new THREE.Vector3(Math.cos(h) * 6, -8, -Math.sin(h) * 6)) }; }
      case 'ground': { const h = this.roverHeading || 0, back = new THREE.Vector3(-Math.cos(h) * 7.5, 4.2, Math.sin(h) * 7.5);
        return { pos: rp.clone().add(back), look: rp.clone().add(new THREE.Vector3(Math.cos(h) * 5, 0.6, -Math.sin(h) * 5)) }; }
      case 'onboard': { const h = this.droneHeading || 0;
        return { pos: dp.clone().add(new THREE.Vector3(Math.cos(h) * 0.6, -0.6, -Math.sin(h) * 0.6)), look: dp.clone().add(new THREE.Vector3(Math.cos(h) * 9, -14, -Math.sin(h) * 9)) }; }
      case 'cinematic': {
        if (this.cine && performance.now() < this.cine.until) { const p = toV(this.cine.xy[0], this.cine.xy[1], 0); const a = (performance.now() - this.t0) / 9000;
          return { pos: p.clone().add(new THREE.Vector3(Math.cos(a) * 16, 11, Math.sin(a) * 16)), look: p }; }
        const mid = dp.clone().lerp(rp, 0.5); mid.y = 0;
        return { pos: mid.clone().add(new THREE.Vector3(-26, 34, 30)), look: mid };
      }
      default: return { pos: new THREE.Vector3(-36, 50, 50), look: new THREE.Vector3(0, 0, -2) };
    }
  }

  // ------------------------------------------------------------ frame
  frame() {
    const now = performance.now(), dt = Math.min(0.1, (now - this.lastFrame) / 1000); this.lastFrame = now;
    this.frameTimes.push(dt * 1000); if (this.frameTimes.length > 240) this.frameTimes.shift();
    if (this.curr) this._animateAgents(now, dt);
    // pulses
    const ph = (now - this.t0) / 1000;
    for (const m of this.candMeshes.values()) { const p = m.userData.pulse; const s = 1 + (ph % 1.6) / 1.6 * 0.8; p.scale.setScalar(s); p.material.opacity = 0.55 * (1 - (ph % 1.6) / 1.6); }
    for (const m of this.debrisMeshes.values()) { const a = Math.min(1, (now - m.userData.born) / 600); m.scale.setScalar(0.3 + 0.7 * a); }
    if (this.camMode !== 'free') {
      const g = this._camGoal(), k = 1 - Math.pow(0.04, dt * (this.camMode === 'onboard' ? 6 : 1.6));
      this.camera.position.lerp(g.pos, k); this.lookNow.lerp(g.look, k); this.camera.lookAt(this.lookNow);
    } else this.controls.update();
    this.renderer.render(this.scene, this.camera);
    this._adapt();
  }

  _lerpAngle(a, b, f) { let d = ((b - a + 540) % 360) - 180; return a + d * f; }

  _animateAgents(now, dt) {
    const f = Math.min(1, (now - this.recvT) / this.interval), P = this.prev, Q = this.curr;
    // drone: interpolated simulated position, constant simulated altitude (display), bank/pitch from motion
    const dx = P.drone.x + (Q.drone.x - P.drone.x) * f, dy = P.drone.y + (Q.drone.y - P.drone.y) * f;
    const dh = this._lerpAngle(P.drone.heading_deg, Q.drone.heading_deg, f);
    const pos = toV(dx, dy, Q.drone.alt_m); const vel = this.dronePos ? pos.clone().sub(this.dronePos).divideScalar(Math.max(dt, 1e-3)) : new THREE.Vector3();
    const acc = vel.clone().sub(this.lastDroneV); this.lastDroneV.lerp(vel, 0.2);
    this.dronePos = pos; this.droneHeading = THREE.MathUtils.degToRad(dh);
    this.drone.position.copy(pos); this.drone.visible = !(this.camMode === 'onboard');
    const speed = Math.hypot(vel.x, vel.z); const pitch = -Math.min(0.22, speed * 0.05);
    const lateral = (acc.x * Math.sin(this.droneHeading) + acc.z * Math.cos(this.droneHeading));
    this.drone.rotation.set(0, this.droneHeading, 0); this.drone.rotateZ(pitch); this.drone.rotateX(THREE.MathUtils.clamp(lateral * 0.02, -0.25, 0.25));
    const failed = Q.drone.failed;
    for (const p of this.drone.userData.props) p.rotation.y += failed ? 0 : dt * 90;
    this.drone.userData.strobe.visible = ((now / 1000) % 1.2) < 0.08;
    this.droneShadow.position.set(pos.x, 0.03, pos.z);
    // footprint = the cell window the sim actually looked at
    const fm = Q.drone.footprint_m, cx = (Math.floor(dx / 2) + 0.5) * 2, cy = (Math.floor(dy / 2) + 0.5) * 2;
    this.foot.scale.set(fm, fm, 1); this.foot.position.copy(toV(cx, cy, 0.09)); this.footEdge.scale.set(fm, fm, 1); this.footEdge.position.copy(toV(cx, cy, 0.1));
    this.foot.visible = this.footEdge.visible = this.frustum.visible = this.layers.aerial && !failed;
    const cam = pos.clone().add(new THREE.Vector3(0, -0.4, 0)), h = fm / 2, arr = this.frustum.geometry.attributes.position.array;
    const corners = [[-h, -h], [h, -h], [h, h], [-h, h]]; let k = 0;
    for (let i = 0; i < 4; i++) { const [ox, oy] = corners[i], c = toV(cx + ox, cy + oy, 0.1); arr.set([cam.x, cam.y, cam.z, c.x, c.y, c.z], k); k += 6; }
    this.frustum.geometry.attributes.position.needsUpdate = true;
    if (Q.drone.target) { this.droneTarget.position.copy(toV(Q.drone.target[0], Q.drone.target[1], 0.6)); this.droneTarget.rotation.y += dt * 2; this.droneTarget.visible = this.layers.aerial; }
    // rover: interpolated simulated pose; wheels turn with the simulated motion
    const R = Q.rover, Rp = P.rover;
    const rx = Rp.x + (R.x - Rp.x) * f, ry = Rp.y + (R.y - Rp.y) * f, rh = this._lerpAngle(Rp.heading_deg, R.heading_deg, f);
    const rpos = toV(rx, ry, 0); const moved = this.roverPos ? rpos.distanceTo(this.roverPos) : 0;
    const prevH = this.roverHeading ?? THREE.MathUtils.degToRad(rh);
    this.roverPos = rpos; this.roverHeading = THREE.MathUtils.degToRad(rh);
    this.rover.position.copy(rpos); this.rover.rotation.set(0, this.roverHeading, 0);
    const yaw = this.roverHeading - prevH, wr = 0.06 * MODEL_SCALE * 1.6;
    for (const w of this.rover.userData.wheels) w.mesh.rotation.y -= (moved / wr) + w.side * yaw * 4;   // spin about the axle
    const halo = this.rover.userData.halo; const alarm = !!R.latched || R.state === 'SAFE_STOP';
    halo.material.opacity = alarm ? 0.5 + 0.4 * Math.sin(now / 160) : 0; halo.material.color.setHex(alarm ? C.red : C.gnd);
  }

  _adapt() {
    const ft = this.frameTimes; if (!this.autoScale || ft.length < 120) return;
    const s = [...ft].sort((a, b) => a - b), p95 = s[Math.floor(s.length * 0.95)];
    const now = performance.now(); if (this._lastAdapt && now - this._lastAdapt < 2500) return;
    if (p95 > 40 && this.renderScale > 0.5) { this.renderScale = Math.max(0.5, this.renderScale - 0.15); this._lastAdapt = now; this.resize(); }
    else if (p95 < 18 && this.renderScale < 1) { this.renderScale = Math.min(1, this.renderScale + 0.1); this._lastAdapt = now; this.resize(); }
  }

  perf() {
    const ft = this.frameTimes; if (!ft.length) return null;
    const s = [...ft].sort((a, b) => a - b), avg = ft.reduce((a, b) => a + b, 0) / ft.length;
    const info = this.renderer.info.render;
    return { fps: 1000 / avg, avg, p95: s[Math.floor(s.length * 0.95)], calls: info.calls, tris: info.triangles,
      res: this.resolution, scale: this.renderScale, preset: this.quality, gpu: this._gpu() };
  }

  _gpu() {
    if (this._gpuName) return this._gpuName;
    try { const gl = this.renderer.getContext(); const ext = gl.getExtension('WEBGL_debug_renderer_info');
      this._gpuName = ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER); } catch { this._gpuName = 'unknown'; }
    return this._gpuName;
  }

  project(v) { const p = v.clone().project(this.camera); const r = this.canvas.getBoundingClientRect();
    return { x: (p.x + 1) / 2 * r.width, y: (1 - p.y) / 2 * r.height, on: p.z < 1 && Math.abs(p.x) < 1.1 && Math.abs(p.y) < 1.1 }; }
}
