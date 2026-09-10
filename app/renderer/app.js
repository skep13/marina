import { THREE, GLTFLoader, VRMLoaderPlugin, VRMUtils } from './vendor/vrm-bundle.js';

const BRIDGE = 'http://127.0.0.1:8765';

const el = (id) => document.getElementById(id);
const canvas     = el('stage');
const bubble     = el('bubble');
const bubbleText = el('bubble-text');
const notice     = el('notice');
const input      = el('input');
const btnSend    = el('btn-send');
const btnMic     = el('btn-mic');
const dot        = el('dot');
const statusText = el('status-text');

const renderer = new THREE.WebGLRenderer({
  canvas,
  alpha: true,
  antialias: true,

  preserveDrawingBuffer: true,
});
renderer.setClearColor(0x000000, 0);
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.outputColorSpace = THREE.SRGBColorSpace;

const scene = new THREE.Scene();

const camera = new THREE.PerspectiveCamera(21, 1, 0.1, 20);

const key = new THREE.DirectionalLight(0xffffff, 2.0);
key.position.set(1, 1.6, 2.2);
scene.add(key);
scene.add(new THREE.AmbientLight(0xffffff, 1.2));

const lookTarget = new THREE.Object3D();
lookTarget.position.set(0, 0, -1);
camera.add(lookTarget);
scene.add(camera);

function resize() {
  const w = window.innerWidth;
  const h = window.innerHeight;
  renderer.setSize(w, h, false);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
}
window.addEventListener('resize', resize);
resize();

let vrm = null;
let bones = {};
let basePose = {};
let springs = [];
let mouthCloseTargets = [];

const loader = new GLTFLoader();
loader.register((parser) => new VRMLoaderPlugin(parser));

function frameUpperBody(v) {

  const head = v.humanoid?.getNormalizedBoneNode('head');
  const target = new THREE.Vector3();
  if (head) {
    v.scene.updateWorldMatrix(true, true);
    head.getWorldPosition(target);
  } else {
    new THREE.Box3().setFromObject(v.scene).getCenter(target);
  }

  const VIEW_HEIGHT = 0.67;
  const DROP = 0.06;
  const fovRad = (camera.fov * Math.PI) / 180;
  const dist = VIEW_HEIGHT / (2 * Math.tan(fovRad / 2));

  camera.position.set(target.x, target.y - DROP, target.z + dist);
  camera.lookAt(target.x, target.y - DROP, target.z);
  camera.updateMatrixWorld(true);
}

async function mountVRM(arrayBuffer, label) {
  const gltf = await loader.parseAsync(arrayBuffer, '');
  const next = gltf.userData.vrm;
  if (!next) throw new Error('That file loaded, but it has no VRM data in it.');

  if (vrm) {
    scene.remove(vrm.scene);
    VRMUtils.deepDispose?.(vrm.scene);
    vrm = null;
  }

  VRMUtils.rotateVRM0(next);
  VRMUtils.removeUnnecessaryVertices?.(next.scene);
  VRMUtils.combineSkeletons?.(next.scene);

  next.scene.traverse((o) => { o.frustumCulled = false; });

  buildRestPose(next);

  collectSprings(next);
  collectMouthClose(next);
  collectBrows(next);
  restyleFace(next);

  if (next.lookAt) {
    next.lookAt.target = lookTarget;
    next.lookAt.autoUpdate = true;
  }

  scene.add(next.scene);
  vrm = next;
  frameUpperBody(next);

  const version = next.meta?.metaVersion === '1' ? 'VRM 1.0' : 'VRM 0.x';
  setStatus('ok', `${label ?? 'model'} · ${version}`);
  hideNotice('model');
}

const IDLE_BONES = [
  'hips', 'spine', 'chest', 'upperChest', 'neck', 'head',
  'leftShoulder', 'rightShoulder',
  'leftUpperArm', 'rightUpperArm',
  'leftLowerArm', 'rightLowerArm',
  'leftHand', 'rightHand',
];

const REST_POSE = {
  leftShoulder:  [0, 0, 0.05],
  rightShoulder: [0, 0, -0.06],
  leftUpperArm:  [0.06, 0, -1.24],
  rightUpperArm: [0.04, 0, 1.20],
  leftLowerArm:  [0, 0.24, -0.10],
  rightLowerArm: [0, -0.20, 0.09],
  leftHand:      [0, 0, -0.07],
  rightHand:     [0, 0, 0.05],
  spine:         [0.02, 0, 0],
  chest:         [0.01, 0, 0],
};

function buildRestPose(v) {
  const h = v.humanoid;
  bones = {};
  basePose = {};
  if (!h) return;

  for (const name of IDLE_BONES) {
    const node = h.getNormalizedBoneNode(name);
    if (!node) continue;
    const pose = REST_POSE[name];
    if (pose) node.rotation.set(pose[0], pose[1], pose[2]);
    bones[name] = node;
    basePose[name] = { x: node.rotation.x, y: node.rotation.y, z: node.rotation.z };
  }
}

function poseBone(name, dx, dy, dz) {
  const node = bones[name];
  const base = basePose[name];
  if (!node || !base) return;
  node.rotation.set(base.x + dx, base.y + (dy || 0), base.z + (dz || 0));
}

const LIPS = {

  region: { u0: 0.40, v0: 0.72, u1: 0.62, v1: 0.80 },
  minSaturation: 0.18,
  saturation: 0.42,
  lighten: 1.06,
  hueShift: -0.012,
};

const INNER_MOUTH = { saturation: 0.62, lighten: 0.98 };

function rgbToHsv(r, g, b) {
  const max = Math.max(r, g, b), min = Math.min(r, g, b), d = max - min;
  let h = 0;
  if (d !== 0) {
    if (max === r) h = ((g - b) / d) % 6;
    else if (max === g) h = (b - r) / d + 2;
    else h = (r - g) / d + 4;
    h /= 6;
    if (h < 0) h += 1;
  }
  return [h, max === 0 ? 0 : d / max, max];
}

function hsvToRgb(h, s, v) {
  const i = Math.floor(h * 6), f = h * 6 - i;
  const p = v * (1 - s), q = v * (1 - f * s), t = v * (1 - (1 - f) * s);
  switch (i % 6) {
    case 0: return [v, t, p];
    case 1: return [q, v, p];
    case 2: return [p, v, t];
    case 3: return [p, q, v];
    case 4: return [t, p, v];
    default: return [v, p, q];
  }
}

function recolourTexture(tex, box, opts) {
  const src = tex?.image;
  if (!src || !src.width) return false;

  const canvas = document.createElement('canvas');
  canvas.width = src.width;
  canvas.height = src.height;
  const ctx = canvas.getContext('2d', { willReadFrequently: true });
  ctx.drawImage(src, 0, 0);

  const x0 = box ? Math.floor(box.u0 * canvas.width) : 0;
  const x1 = box ? Math.ceil(box.u1 * canvas.width) : canvas.width;
  const y0 = box ? Math.floor(box.v0 * canvas.height) : 0;
  const y1 = box ? Math.ceil(box.v1 * canvas.height) : canvas.height;

  const img = ctx.getImageData(x0, y0, x1 - x0, y1 - y0);
  const d = img.data;
  let touched = 0;

  for (let i = 0; i < d.length; i += 4) {
    if (d[i + 3] < 8) continue;
    const [h, sat, val] = rgbToHsv(d[i] / 255, d[i + 1] / 255, d[i + 2] / 255);
    if (sat < (opts.minSaturation ?? 0)) continue;

    let nh = h + (opts.hueShift || 0);
    if (nh < 0) nh += 1; else if (nh > 1) nh -= 1;
    const ns = Math.max(0, Math.min(1, sat * opts.saturation));
    const nv = Math.max(0, Math.min(1, val * (opts.lighten ?? 1)));

    const [r, g, b] = hsvToRgb(nh, ns, nv);
    d[i] = Math.round(r * 255);
    d[i + 1] = Math.round(g * 255);
    d[i + 2] = Math.round(b * 255);
    touched++;
  }

  ctx.putImageData(img, x0, y0);

  tex.image = canvas;
  tex.needsUpdate = true;
  return touched;
}

function restyleFace(v) {
  let lips = 0;
  let mouth = 0;

  v.scene.traverse((obj) => {
    const mats = Array.isArray(obj.material) ? obj.material : obj.material ? [obj.material] : [];
    for (const m of mats) {
      const name = m.name || '';
      if (/Face_00_SKIN/i.test(name)) {
        lips += recolourTexture(m.map, LIPS.region, LIPS) || 0;
      } else if (/FaceMouth/i.test(name)) {
        mouth += recolourTexture(m.map, null, { ...INNER_MOUTH, minSaturation: 0.15 }) || 0;
      }
    }
  });

  if (!lips) console.warn('Lip recolour: no matching pixels — check LIPS.region.');
  return { lips, mouth };
}

const MOUTH_CLOSE_MORPH = 'Fcl_MTH_Close';

const BROW_MORPHS = ['Fcl_BRW_Fun', 'Fcl_BRW_Surprised', 'Fcl_BRW_Sorrow'];
let browTargets = {};

function collectBrows(v) {
  browTargets = {};
  for (const name of BROW_MORPHS) browTargets[name] = [];
  v.scene.traverse((o) => {
    const dict = o.morphTargetDictionary;
    if (!o.isSkinnedMesh || !dict) return;
    for (const name of BROW_MORPHS) {
      if (name in dict) browTargets[name].push({ mesh: o, index: dict[name] });
    }
  });
}

function applyIdleBrow(t) {
  const emoting = Math.max(
    cueOut.expr.happy || 0, cueOut.expr.sad || 0, cueOut.expr.angry || 0,
    cueOut.expr.surprised || 0, cueOut.expr.relaxed || 0,
  );
  const room = Math.max(0, 1 - emoting * 2);

  const values = {

    Fcl_BRW_Fun: room * (0.06 + 0.05 * noise1(t * 0.19 + 7) + browFlash * 0.22),

    Fcl_BRW_Surprised: room * Math.max(0, mouthOpen * 0.14 + 0.03 * noise1(t * 0.23 + 19)),

    Fcl_BRW_Sorrow: room * Math.max(0, 0.05 * noise1(t * 0.14 + 55)),
  };

  for (const name of BROW_MORPHS) {
    const list = browTargets[name];
    if (!list) continue;
    const v = Math.max(0, Math.min(1, values[name] || 0));
    for (let i = 0; i < list.length; i++) {
      const tgt = list[i];
      tgt.mesh.morphTargetInfluences[tgt.index] = v;
    }
  }
}

function collectMouthClose(v) {
  mouthCloseTargets = [];
  v.scene.traverse((o) => {
    const dict = o.morphTargetDictionary;
    if (o.isSkinnedMesh && dict && MOUTH_CLOSE_MORPH in dict) {
      mouthCloseTargets.push({ mesh: o, index: dict[MOUTH_CLOSE_MORPH] });
    }
  });
}

function applyRestingMouth() {
  if (!mouthCloseTargets.length) return;

  const emoting = Math.max(
    cueOut.expr.happy || 0, cueOut.expr.sad || 0,
    cueOut.expr.angry || 0, cueOut.expr.surprised || 0,
  );
  const close = Math.max(0, 1 - mouthOpen * 2.2 - emoting * 1.2);

  for (let i = 0; i < mouthCloseTargets.length; i++) {
    const t = mouthCloseTargets[i];
    t.mesh.morphTargetInfluences[t.index] = close;
  }
}

function collectSprings(v) {
  springs = [];
  const mgr = v.springBoneManager;
  if (!mgr || !mgr.joints) return;
  for (const joint of mgr.joints) {
    springs.push({
      joint,
      dir: joint.settings.gravityDir.clone(),
      power: joint.settings.gravityPower,
    });
  }
}

async function loadFromDisk() {
  const res = await window.marina.loadVRM();
  if (res.error) {
    setStatus('bad', 'no model');
    showNotice(`${res.error}\n\nIn VRoid Studio: Export → VRM, then use the model button in the top-right to pick the file.`, 'model');
    return;
  }
  try {
    await mountVRM(res.buffer, res.name);
  } catch (e) {
    setStatus('bad', 'model failed');
    showNotice(`Could not load ${res.name}: ${e.message}`, 'model');
  }
}

const pointer = { x: 0, y: 0 };
window.addEventListener('mousemove', (e) => {
  pointer.x = (e.clientX / window.innerWidth) * 2 - 1;
  pointer.y = (e.clientY / window.innerHeight) * 2 - 1;
});

let blinkTimer = 1 + Math.random() * 3;
let blinkPending = 0;
let blinkT = 999;
let blinkDur = 0.14;

let moodTimer = 0;
let mood = 0;
let moodTarget = 0;

const AVERSIONS = [
  { x: -0.38, y:  0.27, hold: [1.1, 2.4] },
  { x:  0.36, y:  0.25, hold: [1.1, 2.4] },
  { x: -0.27, y: -0.23, hold: [1.4, 3.0] },
  { x:  0.25, y: -0.21, hold: [1.4, 3.0] },
  { x: -0.48, y:  0.04, hold: [1.6, 3.4] },
  { x:  0.46, y: -0.02, hold: [1.6, 3.4] },
];

const speaking = () => mouthOpen > 0.02 || playing > 0;

let gazeTimer = 0;
let gazeAway = false;
const gaze = { x: 0, y: 0 };
const gazeTarget = { x: 0, y: 0 };

const gazeHead = { x: 0, y: 0 };
const gazeHeadV = { x: 0, y: 0 };

const headS = { x: 0, y: 0, z: 0 };
const headV = { x: 0, y: 0, z: 0 };

const torsoS = { x: 0, y: 0 };
const torsoV = { x: 0, y: 0 };

let envFast = 0, envSlow = 0;
let browFlash = 0;

const _hash = (i) => {
  const s = Math.sin(i * 127.1) * 43758.5453;
  return (s - Math.floor(s)) * 2 - 1;
};
function noise1(x) {
  const i = Math.floor(x), f = x - i;

  const u = f * f * f * (f * (f * 6 - 15) + 10);
  return _hash(i) * (1 - u) + _hash(i + 1) * u;
}

function fbm(x) {
  return noise1(x) * 0.72 + noise1(x * 2.7 + 13.7) * 0.28;
}

let audioCtx = null;
let analyser = null;
let freqData = null;
let timeData = null;
let mouthOpen = 0;

function ensureAudio() {
  if (!audioCtx) {
    audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    analyser = audioCtx.createAnalyser();
    analyser.fftSize = 1024;
    analyser.smoothingTimeConstant = 0.35;
    freqData = new Uint8Array(analyser.frequencyBinCount);
    timeData = new Uint8Array(analyser.fftSize);
    analyser.connect(audioCtx.destination);
  }
  if (audioCtx.state === 'suspended') audioCtx.resume();
  return audioCtx;
}

function decodeBase64Wav(base64) {
  const bin = atob(base64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return ensureAudio().decodeAudioData(bytes.buffer);
}

const utterance = {
  epoch: -1,
  nextStart: 0,
  chunks: [],
  ended: false,
};

let playing = 0;

function chunksSpoken() {
  if (utterance.epoch < 0) return 0;
  const now = audioCtx.currentTime;
  let n = 0;
  for (const c of utterance.chunks) if (c.end <= now) n = Math.max(n, c.index + 1);
  return n;
}

async function enqueueChunk(base64, cues) {
  const ctx = ensureAudio();
  const buffer = await decodeBase64Wav(base64);

  const LEAD = 0.06;
  if (utterance.epoch < 0) {
    utterance.epoch = ctx.currentTime + LEAD;
    utterance.nextStart = utterance.epoch;
    cueEpoch = utterance.epoch;
    pendingCues = [];
  } else if (utterance.nextStart < ctx.currentTime) {
    utterance.nextStart = ctx.currentTime;
  }

  const start = utterance.nextStart;
  const index = utterance.chunks.length;

  const src = ctx.createBufferSource();
  src.buffer = buffer;
  src.connect(analyser);
  playing++;
  src.onended = () => { playing = Math.max(0, playing - 1); };
  src.start(start);

  utterance.chunks.push({ index, start, end: start + buffer.duration, src });
  utterance.nextStart = start + buffer.duration;

  appendCues(cues, start - utterance.epoch, buffer.duration);
}

function stopSpeaking() {
  if (utterance.epoch < 0) return 0;
  const spoken = chunksSpoken();
  for (const c of utterance.chunks) {
    try { c.src.stop(); } catch {   }
  }
  utterance.chunks = [];
  utterance.epoch = -1;
  utterance.ended = true;
  playing = 0;
  cueEpoch = -1;
  pendingCues = [];
  return spoken;
}

function untilSpoken() {
  if (utterance.epoch < 0 || !utterance.chunks.length) return Promise.resolve();
  const last = utterance.chunks[utterance.chunks.length - 1];
  const remaining = Math.max(0, last.end - audioCtx.currentTime);
  return new Promise((r) => setTimeout(r, remaining * 1000 + 40));
}

function endUtterance() {
  utterance.epoch = -1;
  utterance.chunks = [];
  utterance.ended = true;
  cueEpoch = -1;
}

async function speak(base64, onStart) {
  stopSpeaking();
  utterance.ended = false;
  const ctx = ensureAudio();
  const buffer = await decodeBase64Wav(base64);
  utterance.epoch = ctx.currentTime + 0.06;
  utterance.nextStart = utterance.epoch;
  cueEpoch = utterance.epoch;
  pendingCues = [];

  const src = ctx.createBufferSource();
  src.buffer = buffer;
  src.connect(analyser);
  playing++;
  utterance.chunks.push({ index: 0, start: utterance.epoch,
                          end: utterance.epoch + buffer.duration, src });
  utterance.nextStart = utterance.epoch + buffer.duration;

  onStart?.(buffer.duration);

  return new Promise((resolve) => {
    src.onended = () => {
      playing = Math.max(0, playing - 1);
      endUtterance();
      resolve();
    };
    src.start(utterance.epoch);
  });
}

const DB_FLOOR = -46;
const DB_CEIL = -14;

const BANDS = { f1: [250, 900], f2: [900, 2500], sib: [4000, 9000] };
let bandBins = null;

function resolveBands() {
  const nyquist = audioCtx.sampleRate / 2;
  const n = analyser.frequencyBinCount;
  const toBin = (hz) => Math.max(0, Math.min(n - 1, Math.round((hz / nyquist) * n)));
  bandBins = {
    f1: BANDS.f1.map(toBin),
    f2: BANDS.f2.map(toBin),
    sib: BANDS.sib.map(toBin),
  };
}

function bandEnergy(range) {
  let sum = 0;
  for (let i = range[0]; i < range[1]; i++) sum += freqData[i];
  return sum / Math.max(1, (range[1] - range[0]) * 255);
}

const clamp01 = (v) => (v < 0 ? 0 : v > 1 ? 1 : v);

const VISEMES = ['aa', 'ih', 'ou', 'ee', 'oh'];
const viseme = { aa: 0, ih: 0, ou: 0, ee: 0, oh: 0 };
const visemeTarget = { aa: 0, ih: 0, ou: 0, ee: 0, oh: 0 };

function updateMouth(dt) {
  let open = 0;

  for (const v of VISEMES) visemeTarget[v] = 0;

  if (playing > 0 && analyser) {
    if (!bandBins) resolveBands();

    analyser.getByteTimeDomainData(timeData);
    let sum = 0;
    for (let i = 0; i < timeData.length; i++) {
      const a = (timeData[i] - 128) / 128;
      sum += a * a;
    }
    const rms = Math.sqrt(sum / timeData.length);
    const db = 20 * Math.log10(rms + 1e-6);

    open = clamp01((db - DB_FLOOR) / (DB_CEIL - DB_FLOOR));

    open = Math.pow(open, 1.35) * 0.92;
    if (open < 0.05) open = 0;

    analyser.getByteFrequencyData(freqData);
    const e1 = bandEnergy(bandBins.f1);
    const e2 = bandEnergy(bandBins.f2);
    const e3 = bandEnergy(bandBins.sib);

    const voiced = e1 + e2;
    const frontness = voiced > 0.001 ? clamp01(e2 / voiced) : 0.4;
    const sibilance = (voiced + e3) > 0.001 ? clamp01(e3 / (voiced + e3)) : 0;

    if (sibilance > 0.45) open *= 1 - (sibilance - 0.45) * 1.2;

    const w = {
      ee: clamp01((frontness - 0.58) * 3.4),
      ih: clamp01(1 - Math.abs(frontness - 0.52) * 4.2),
      aa: clamp01(1 - Math.abs(frontness - 0.34) * 3.6),
      oh: clamp01((0.36 - frontness) * 3.6),
      ou: clamp01((0.28 - frontness) * 4.0),
    };

    w.aa *= 0.5 + open * 0.5;
    w.ou *= 1.15 - open * 0.4;
    w.ee += sibilance * 0.5;

    let total = 0;
    for (const v of VISEMES) total += w[v];
    if (total > 0.001) {
      for (const v of VISEMES) visemeTarget[v] = (w[v] / total) * open;
    } else {
      visemeTarget.aa = open;
    }
  }

  for (const v of VISEMES) {
    const t = visemeTarget[v];
    const rate = t > viseme[v] ? 24 : 12;
    viseme[v] += (t - viseme[v]) * Math.min(1, rate * dt);
  }

  mouthOpen = clamp01(viseme.aa + viseme.oh + viseme.ee * 0.6 + viseme.ih * 0.6 + viseme.ou * 0.5);

  const em = vrm?.expressionManager;
  if (!em) return;
  for (const v of VISEMES) em.setValue(v, viseme[v]);
}

const TAU = Math.PI * 2;

function updateBody(t, dtBody) {

  envFast += (mouthOpen - envFast) * Math.min(1, dtBody * 14);
  envSlow += (mouthOpen - envSlow) * Math.min(1, dtBody * 2.2);
  const stress = Math.max(0, envFast - envSlow);

  const bphase = t * 0.21 + 0.07 * noise1(t * 0.05);
  const bw = bphase - Math.floor(bphase);
  const breath = (bw < 0.4
    ? Math.sin((bw / 0.4) * Math.PI * 0.5)
    : Math.cos(((bw - 0.4) / 0.6) * Math.PI * 0.5)) * 2 - 1;

  const energy = 0.68 + 0.42 * noise1(t * 0.035 + 3);

  const shift = fbm(t * 0.031 + 61) * energy;

  const TK = 2.6, TC = 2.9;
  torsoV.y += (TK * (gazeHead.x - torsoS.y) - TC * torsoV.y) * dtBody;
  torsoV.x += (TK * (-gazeHead.y - torsoS.x) - TC * torsoV.x) * dtBody;
  torsoS.y += torsoV.y * dtBody;
  torsoS.x += torsoV.x * dtBody;

  const twist = torsoS.y * 0.30;
  const lean  = torsoS.x * 0.10;

  poseBone('hips',
    lean * 0.4,
    twist * 0.30 + shift * 0.020,
    shift * -0.016);
  poseBone('spine',
    -0.004 * breath + lean * 0.5,
    twist * 0.34 + shift * 0.014,
    shift * 0.010);
  poseBone('chest',
    -0.013 * breath + lean * 0.7,
    twist * 0.22,
    shift * 0.008);
  poseBone('upperChest',
    -0.008 * breath,
    twist * 0.14,
    shift * 0.005);

  const lift = cueOut.shoulder;
  poseBone('leftShoulder',
    -0.010 * breath - lift - stress * 0.06, 0, 0.006 * breath + lift * 0.5);
  poseBone('rightShoulder',
    -0.010 * breath - lift - stress * 0.06, 0, -0.006 * breath - lift * 0.5);

  const armL = fbm(t * 0.077 + 11) * energy;
  const armR = fbm(t * 0.071 + 29) * energy;
  const swing = twist * 0.55;

  poseBone('leftUpperArm',
    0.012 * armL - 0.010 * breath,
    swing * 0.5,
    -0.030 * armL - swing * 0.35 - lift * 0.35);
  poseBone('rightUpperArm',
    0.012 * armR - 0.010 * breath,
    swing * 0.5,
    0.028 * armR - swing * 0.35 + lift * 0.35);
  poseBone('leftLowerArm', 0, 0.030 * armL + swing * 0.25, -0.014 * armL);
  poseBone('rightLowerArm', 0, -0.028 * armR + swing * 0.25, 0.013 * armR);
  poseBone('leftHand', 0.018 * armR, 0, -0.014 * armL);
  poseBone('rightHand', 0.017 * armL, 0, 0.013 * armR);

  const nx = fbm(t * 0.13);
  const ny = fbm(t * 0.11 + 40);
  const nz = fbm(t * 0.09 + 80);

  const followX = -gazeHead.y * 0.19;
  const followY = gazeHead.x * 0.40;

  const idleX = pointer.y * 0.09 + 0.016 * nx * energy;
  const idleY = pointer.x * 0.17 + 0.034 * ny * energy;
  const idleZ = 0.018 * nz * energy;

  const HK = 5.0, HC = 4.2;
  headV.x += (HK * (idleX - headS.x) - HC * headV.x) * dtBody;
  headV.y += (HK * (idleY - headS.y) - HC * headV.y) * dtBody;
  headV.z += (HK * (idleZ - headS.z) - HC * headV.z) * dtBody;
  headS.x += headV.x * dtBody;
  headS.y += headV.y * dtBody;
  headS.z += headV.z * dtBody;

  const x = headS.x + followX + stress * 0.60 + envSlow * 0.012 + cueOut.hx;
  const y = headS.y + followY + envSlow * 0.06 * fbm(t * 0.9 + 5) + cueOut.hy;
  const z = headS.z - followY * 0.13 + cueOut.hz;

  poseBone('neck', x * 0.40, y * 0.40, z * 0.5);
  poseBone('head', x * 0.60, y * 0.60, z * 0.5);
}

const ease = (p) => Math.sin(p * Math.PI);
const settle = (p) => Math.sin(p * Math.PI) * (1 - p);

const CUES = {
  nod:       { dur: 1.0, run: (p, o) => { o.hx += Math.sin(p * TAU * 1.5) * 0.20 * (1 - p); } },
  shake:     { dur: 1.1, run: (p, o) => { o.hy += Math.sin(p * TAU * 2) * 0.20 * (1 - p); } },
  tilt:      { dur: 1.6, run: (p, o) => { o.hz += ease(p) * 0.30; o.hy += ease(p) * 0.06; } },
  shrug:     { dur: 1.3, run: (p, o) => { o.shoulder += ease(p) * 0.14; o.hx += ease(p) * 0.05; } },
  lean:      { dur: 1.5, run: (p, o) => { o.hx += ease(p) * 0.10; o.expr.happy = ease(p) * 0.15; } },
  laugh:     { dur: 1.8, run: (p, o) => {
                 o.expr.happy = ease(p) * 0.9;
                 o.hx += Math.sin(p * TAU * 4) * 0.07 * (1 - p);
                 o.hz += Math.sin(p * TAU * 2) * 0.04;
               } },
  smile:     { dur: 2.0, run: (p, o) => { o.expr.happy = ease(p) * 0.75; } },
  wink:      { dur: 0.7, run: (p, o) => {
                 o.blinkLeft = p < 0.55 ? Math.min(1, p * 4) : Math.max(0, 1 - (p - 0.55) * 5);
                 o.expr.happy = ease(p) * 0.4;
               } },
  eyeroll:   { dur: 1.4, run: (p, o) => {
                 o.gazeY += ease(p) * 0.85;
                 o.hz += ease(p) * 0.08;
                 o.expr.relaxed = ease(p) * 0.3;
               } },
  sigh:      { dur: 2.0, run: (p, o) => {
                 o.hx += ease(p) * 0.16;
                 o.expr.sad = ease(p) * 0.45;
                 o.shoulder -= ease(p) * 0.06;
               } },
  pout:      { dur: 1.8, run: (p, o) => { o.expr.angry = ease(p) * 0.55; o.hy += ease(p) * 0.07; } },
  sad:       { dur: 2.0, run: (p, o) => { o.expr.sad = ease(p) * 0.7; o.hx += ease(p) * 0.12; } },
  surprised: { dur: 1.2, run: (p, o) => {
                 o.expr.surprised = ease(p) * 0.85;
                 o.hx -= settle(p) * 0.18;
               } },
  blush:     { dur: 2.2, run: (p, o) => {
                 o.expr.happy = ease(p) * 0.4;
                 o.hy += ease(p) * 0.16;
                 o.hx += ease(p) * 0.09;
               } },
  think:     { dur: 2.0, run: (p, o) => {
                 o.gazeY += ease(p) * 0.5;
                 o.gazeX += ease(p) * 0.4;
                 o.hz += ease(p) * 0.14;
               } },
  brow:      { dur: 1.4, run: (p, o) => {
                 o.expr.surprised = ease(p) * 0.35;
                 o.hz += ease(p) * 0.10;
                 o.hx -= ease(p) * 0.05;
               } },
  stare:     { dur: 1.6, run: (p, o) => {
                 o.expr.relaxed = ease(p) * 0.25;
                 o.hx += ease(p) * 0.04;
               } },
  yawn:      { dur: 2.2, run: (p, o) => {
                 o.hx += ease(p) * 0.18;
                 o.shoulder += ease(p) * 0.10;
               } },
  emote:     { dur: 1.0, run: (p, o) => { o.hx += Math.sin(p * TAU) * 0.06; } },
};

const CUE_EXPRESSIONS = ['happy', 'sad', 'angry', 'relaxed', 'surprised'];

let pendingCues = [];
let activeCues = [];
let cueClock = -1;

let cueEpoch = -1;

const cueOut = { hx: 0, hy: 0, hz: 0, shoulder: 0, gazeX: 0, gazeY: 0, blinkLeft: 0, expr: {} };
const cueScratch = { hx: 0, hy: 0, hz: 0, shoulder: 0, gazeX: 0, gazeY: 0, blinkLeft: 0, expr: {} };

function scheduleCues(cues, duration) {
  pendingCues = (cues || []).map((c) => ({
    animation: c.animation,
    at: Math.max(0, (c.fraction ?? 0) * duration - 0.15),
  }));
  activeCues = [];
  cueClock = pendingCues.length ? 0 : -1;
}

function appendCues(cues, offset, duration) {
  for (const c of cues || []) {
    pendingCues.push({
      animation: c.animation,
      at: Math.max(0, offset + (c.fraction ?? 0) * duration - 0.15),
    });
  }
  pendingCues.sort((a, b) => a.at - b.at);
}

const IDLE_GESTURES = ['tilt', 'lean', 'smile', 'nod', 'shrug', 'think', 'brow', 'sigh', 'eyeroll', 'stare'];

let gestureBag = [];
let lastGesture = null;
let gestureTimer = 6 + Math.random() * 8;

function drawGesture() {
  if (!gestureBag.length) {
    gestureBag = IDLE_GESTURES.slice();
    for (let i = gestureBag.length - 1; i > 0; i--) {
      const j = (Math.random() * (i + 1)) | 0;
      [gestureBag[i], gestureBag[j]] = [gestureBag[j], gestureBag[i]];
    }

    if (gestureBag[gestureBag.length - 1] === lastGesture && gestureBag.length > 1) {
      const swap = (Math.random() * (gestureBag.length - 1)) | 0;
      [gestureBag[gestureBag.length - 1], gestureBag[swap]] =
        [gestureBag[swap], gestureBag[gestureBag.length - 1]];
    }
  }
  lastGesture = gestureBag.pop();
  return lastGesture;
}

function updateIdleGestures(dt) {

  if (cueClock >= 0 || mouthOpen > 0.05) { gestureTimer = Math.max(gestureTimer, 2.5); return; }

  gestureTimer -= dt;
  if (gestureTimer > 0) return;
  gestureTimer = 7 + Math.random() * 11;

  const def = CUES[drawGesture()];

  if (def) activeCues.push({ run: def.run, elapsed: 0, dur: def.dur * 1.8, gain: 0.5 });
}

function updateCues(dt) {
  cueOut.hx = cueOut.hy = cueOut.hz = 0;
  cueOut.shoulder = cueOut.gazeX = cueOut.gazeY = cueOut.blinkLeft = 0;
  for (const name of CUE_EXPRESSIONS) cueOut.expr[name] = 0;

  if (cueEpoch >= 0 && audioCtx) {
    cueClock = audioCtx.currentTime - cueEpoch;
  } else if (cueClock >= 0) {
    cueClock += dt;
  }

  if (cueClock >= 0) {
    while (pendingCues.length && pendingCues[0].at <= cueClock) {
      const next = pendingCues.shift();
      const def = CUES[next.animation] || CUES.emote;
      activeCues.push({ run: def.run, elapsed: 0, dur: def.dur });
    }

    if (cueEpoch < 0 && !pendingCues.length && !activeCues.length) cueClock = -1;
  }

  for (let i = activeCues.length - 1; i >= 0; i--) {
    const c = activeCues[i];
    c.elapsed += dt;
    const p = c.elapsed / c.dur;
    if (p >= 1) { activeCues.splice(i, 1); continue; }

    if (c.gain === undefined || c.gain === 1) { c.run(p, cueOut); continue; }

    cueScratch.hx = cueScratch.hy = cueScratch.hz = 0;
    cueScratch.shoulder = cueScratch.gazeX = cueScratch.gazeY = cueScratch.blinkLeft = 0;
    for (const name of CUE_EXPRESSIONS) cueScratch.expr[name] = 0;
    c.run(p, cueScratch);
    cueOut.hx += cueScratch.hx * c.gain;
    cueOut.hy += cueScratch.hy * c.gain;
    cueOut.hz += cueScratch.hz * c.gain;
    cueOut.shoulder += cueScratch.shoulder * c.gain;
    cueOut.gazeX += cueScratch.gazeX * c.gain;
    cueOut.gazeY += cueScratch.gazeY * c.gain;
    cueOut.blinkLeft = Math.max(cueOut.blinkLeft, cueScratch.blinkLeft * c.gain);
    for (const name of CUE_EXPRESSIONS) {
      cueOut.expr[name] = Math.max(cueOut.expr[name], cueScratch.expr[name] * c.gain);
    }
  }
}

const WIND_STRENGTH = 0.15;

const _wind = new THREE.Vector3();
const _force = new THREE.Vector3();

function updateHair(t) {
  if (!springs.length) return;

  const gust = 0.55 + 0.45 * Math.sin(t * TAU * 0.037);
  const wx = (Math.sin(t * TAU * 0.13) * 0.6
            + Math.sin(t * TAU * 0.29 + 1.3) * 0.28
            + Math.sin(t * TAU * 0.61 + 2.4) * 0.10) * gust;
  const wz = (Math.sin(t * TAU * 0.11 + 2.1) * 0.5
            + Math.sin(t * TAU * 0.23 + 0.7) * 0.24
            + Math.sin(t * TAU * 0.53 + 1.1) * 0.09) * gust;

  _wind.set(wx * WIND_STRENGTH, 0, wz * WIND_STRENGTH);

  for (let i = 0; i < springs.length; i++) {
    const s = springs[i];
    _force.copy(s.dir).multiplyScalar(s.power).add(_wind);
    const len = _force.length();
    if (len < 1e-6) continue;
    s.joint.settings.gravityDir.copy(_force).divideScalar(len);
    s.joint.settings.gravityPower = len;
  }
}

function updateGaze(dt, t) {
  gazeTimer -= dt;
  if (gazeTimer <= 0) {
    const from = { x: gazeTarget.x, y: gazeTarget.y };

    if (gazeAway) {

      gazeAway = false;
      gazeTarget.x = (Math.random() - 0.5) * 0.10;
      gazeTarget.y = (Math.random() - 0.5) * 0.07;

      gazeTimer = (speaking() ? 2.6 : 1.6) + Math.random() * 3.4;
      browFlash = 1;
    } else if (Math.random() < (speaking() ? 0.16 : 0.45)) {
      gazeAway = true;
      const a = AVERSIONS[(Math.random() * AVERSIONS.length) | 0];

      const near = speaking() ? 0.55 : 1;
      gazeTarget.x = (a.x + (Math.random() - 0.5) * 0.10) * near;
      gazeTarget.y = (a.y + (Math.random() - 0.5) * 0.08) * near;
      gazeTimer = (a.hold[0] + Math.random() * (a.hold[1] - a.hold[0]))
                * (speaking() ? 0.45 : 1);
    } else {

      gazeTarget.x = (Math.random() - 0.5) * 0.14;
      gazeTarget.y = (Math.random() - 0.5) * 0.10;
      gazeTimer = 1.3 + Math.random() * 2.2;
    }

    const jump = Math.hypot(gazeTarget.x - from.x, gazeTarget.y - from.y);
    if (jump > 0.28 && blinkTimer > 0.9 && Math.random() < 0.4) blinkTimer = 0.02;
  }

  const dist = Math.hypot(gazeTarget.x - gaze.x, gazeTarget.y - gaze.y);
  const k = Math.min(1, dt * (13 - Math.min(7, dist * 9)));
  gaze.x += (gazeTarget.x - gaze.x) * k;
  gaze.y += (gazeTarget.y - gaze.y) * k;

  const driftX = noise1(t * 1.7) * 0.012;
  const driftY = noise1(t * 1.4 + 31) * 0.009;

  const K = 6, C = 4.4;
  gazeHeadV.x += (K * (gazeTarget.x - gazeHead.x) - C * gazeHeadV.x) * dt;
  gazeHeadV.y += (K * (gazeTarget.y - gazeHead.y) - C * gazeHeadV.y) * dt;
  gazeHead.x += gazeHeadV.x * dt;
  gazeHead.y += gazeHeadV.y * dt;

  browFlash = Math.max(0, browFlash - dt * 2.6);

  lookTarget.position.set(
    pointer.x * 0.45 + gaze.x + driftX + cueOut.gazeX,
    -pointer.y * 0.30 + gaze.y + driftY + cueOut.gazeY,
    -1,
  );
}

function updateBlink(dt) {
  blinkTimer -= dt;
  if (blinkTimer <= 0) {
    blinkT = 0;
    blinkDur = 0.11 + Math.random() * 0.07;
    if (blinkPending > 0) {
      blinkPending -= 1;
      blinkTimer = 2.4 + Math.random() * 4.6;
    } else if (Math.random() < 0.25) {
      blinkPending = 1;
      blinkTimer = 0.24;
    } else {
      blinkTimer = 2.4 + Math.random() * 4.6;
    }
  }

  blinkT += dt;
  const bp = blinkT / blinkDur;
  const blink = bp >= 1 ? 0
    : bp < 0.32
      ? Math.pow(bp / 0.32, 0.62)
      : Math.pow(1 - (bp - 0.32) / 0.68, 1.7);
  const em = vrm.expressionManager;
  if (!em) return;

  if (cueOut.blinkLeft > 0.01) {

    em.setValue('blink', 0);
    em.setValue('blinkLeft', Math.max(blink, cueOut.blinkLeft));
    em.setValue('blinkRight', blink);
  } else {
    em.setValue('blinkLeft', 0);
    em.setValue('blinkRight', 0);
    em.setValue('blink', blink);
  }
}

function updateMood(dt) {
  const em = vrm.expressionManager;
  if (!em) return;

  moodTimer -= dt;
  if (moodTimer <= 0) {
    moodTimer = 4 + Math.random() * 9;

    moodTarget = Math.random() < 0.5 ? 0 : 0.05 + Math.random() * 0.10;
  }
  mood += (moodTarget - mood) * Math.min(1, dt * 1.3);

  const idleHappy = mood * (1 - Math.min(1, mouthOpen * 1.4));
  em.setValue('happy', Math.max(idleHappy, cueOut.expr.happy));
  em.setValue('sad', cueOut.expr.sad);
  em.setValue('angry', cueOut.expr.angry);
  em.setValue('relaxed', cueOut.expr.relaxed);
  em.setValue('surprised', cueOut.expr.surprised);
}

const timer = new THREE.Timer();

function tick() {
  requestAnimationFrame(tick);
  timer.update();
  const dt = Math.min(timer.getDelta(), 0.1);
  const t = timer.getElapsed();

  if (vrm) {

    updateMouth(dt);
    updateCues(dt);
    updateIdleGestures(dt);
    updateGaze(dt, t);
    updateBody(t, dt);
    updateBlink(dt);
    updateMood(dt);
    updateHair(t);

    vrm.update(dt);

    applyRestingMouth();
    applyIdleBrow(t);
  }

  renderer.render(scene, camera);
  updateClickThrough();
}

const gl = renderer.getContext();
const probe = new Uint8Array(4);
const UI = ['#bar', '#chrome', '#status', '#bubble', '#picker', '#notice', '#drag-strip'];

function overUI(x, y) {
  const hit = document.elementFromPoint(x, y);
  if (!hit) return false;
  for (const sel of UI) {
    const box = hit.closest(sel);
    if (!box) continue;

    if (sel === '#drag-strip') return true;
    return parseFloat(getComputedStyle(box).opacity) > 0.05;
  }
  return false;
}

function overAvatar(x, y) {
  const r = renderer.getPixelRatio();
  const px = Math.round(x * r);
  const py = Math.round((window.innerHeight - y) * r);
  if (px < 0 || py < 0 || px >= gl.drawingBufferWidth || py >= gl.drawingBufferHeight) return false;
  gl.readPixels(px, py, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, probe);
  return probe[3] > 12;
}

let solid = null;
let cursor = null;

window.addEventListener('mousemove', (e) => {
  cursor = [e.clientX, e.clientY];

  document.body.classList.add('near');
});
window.addEventListener('mouseleave', () => {
  cursor = null;
  document.body.classList.remove('near');
  setSolid(false);
});

function setSolid(next) {
  if (next === solid) return;
  solid = next;
  window.marina.clickThrough(!next);
}

function updateClickThrough() {
  if (!cursor) return;
  const [x, y] = cursor;
  setSolid(overUI(x, y) || overAvatar(x, y));
}

tick();

let busy = false;
let recording = false;

function setStatus(kind, text) {
  dot.className = kind;
  statusText.textContent = text;
}

let noticeKind = null;

window.marina.onBridgeDown?.((msg) => {
  setStatus('bad', 'backend restarting');
  showNotice(msg || 'Backend stopped. Restarting\u2026', 'bridge');
});
window.marina.onBridgeUp?.(() => {
  hideNotice('bridge');
  setStatus('ok', 'ready');
});

function showNotice(msg, kind = 'general') {
  noticeKind = kind;
  notice.textContent = msg;
  notice.classList.remove('hidden');
}

function hideNotice(kind = null) {
  if (kind !== null && noticeKind !== kind) return;
  noticeKind = null;
  notice.classList.add('hidden');
}

let bubbleTimer = null;
function say(text) {
  bubbleText.textContent = text;
  bubble.classList.remove('hidden');
  clearTimeout(bubbleTimer);
  bubbleTimer = setTimeout(() => bubble.classList.add('hidden'), 6000 + text.length * 45);
}

const BRIDGE_DOWN = `Marina's bridge isn't running.\nIn the project folder:  python server/marina_server.py`;

async function post(path, body) {
  const res = await fetch(BRIDGE + path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw new Error(`bridge returned ${res.status}`);
  return res.json();
}

function setBusy(on, label) {
  busy = on;
  btnSend.disabled = on;
  const see = el('btn-see');
  if (see) see.disabled = on;
  setStatus(on ? 'busy' : 'ok', on ? label : 'ready');
}

async function handleResult(result) {
  if (result.error) showNotice(result.error, 'bridge'); else hideNotice('bridge');
  noteBackendUsed(result);

  if (result.speech) say(result.speech);

  if (result.audio) {
    setStatus('busy', 'speaking');
    utterance.ended = false;
    const req = newRequest();
    armBargeIn(req);
    await speak(result.audio, (duration) => scheduleCues(result.cues, duration));
    disarmBargeIn(req);
    if (inflight === req) inflight = null;
  } else if (result.cues && result.cues.length) {

    scheduleCues(result.cues, Math.max(1.5, (result.speech || '').length / 14));
  }
  setBusy(false);
}

async function* readEvents(response) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buf = '';
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let nl;
    while ((nl = buf.indexOf('\n')) >= 0) {
      const line = buf.slice(0, nl).trim();
      buf = buf.slice(nl + 1);
      if (line) yield JSON.parse(line);
    }
  }
  if (buf.trim()) yield JSON.parse(buf.trim());
}

let inflight = null;

async function playChunk(ev, req) {
  noteBackendUsed(ev);
  if (ev.error) showNotice(ev.error, 'bridge');

  if (ev.speech) {
    req.text = (req.text ? req.text + ' ' : '') + ev.speech;
    say(req.text);
  }
  if (ev.audio) {
    if (!req.chunks) setStatus('busy', 'speaking');
    await enqueueChunk(ev.audio, ev.cues);
  } else if (ev.cues && ev.cues.length) {

    appendCues(ev.cues, 0, Math.max(1.5, (ev.speech || '').length / 14));
    if (cueEpoch < 0 && cueClock < 0) cueClock = 0;
  }
  req.chunks++;

  if (req.chunks === 1) armBargeIn(req);
}

async function consumeReply(res, req) {
  if (!res.ok) throw new Error(`bridge returned ${res.status}`);
  for await (const ev of readEvents(res)) {

    if (req.cancelled) continue;
    if (ev.type === 'chunk') await playChunk(ev, req);
    else if (ev.type === 'error') showNotice(ev.message, 'bridge');
  }
  if (!req.cancelled) {
    hideNotice('bridge');
    await untilSpoken();
    endUtterance();
  }
}

function newRequest() {
  const req = { cancelled: false, text: '', chunks: 0, barge: null };
  utterance.ended = false;
  inflight = req;
  return req;
}

async function send(text) {
  if (busy || !text.trim()) return;
  setBusy(true, 'thinking');
  say('…');
  const req = newRequest();

  try {
    await consumeReply(await fetch(BRIDGE + '/chat/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
    }), req);
  } catch {
    if (!req.cancelled) bridgeLost();
  } finally {
    disarmBargeIn(req);
    if (inflight === req) inflight = null;
    setBusy(false);
  }
}

let bargeEnabled = true;

async function armBargeIn(req) {
  if (!bargeEnabled || req.barge || req.cancelled) return;
  const controller = new AbortController();
  req.barge = controller;

  try {
    const res = await fetch(`${BRIDGE}/barge/listen?timeout=45`,
                            { signal: controller.signal });
    if (!res.ok) return;
    const next = { cancelled: false, text: '', chunks: 0, barge: null };

    for await (const ev of readEvents(res)) {
      if (ev.type === 'disabled') { bargeEnabled = false; return; }
      if (ev.type === 'speech') {

        req.tookOver = true;
        await interrupt();
        inflight = next;
        setBusy(true, 'listening…');
      } else if (ev.type === 'transcript') {
        setBusy(true, 'thinking');
        say('…');
      } else if (ev.type === 'chunk') {
        await playChunk(ev, next);
      } else if (ev.type === 'cancelled') {
        setBusy(false);
        return;
      } else if (ev.type === 'error') {
        showNotice(ev.message, 'bridge');
      }
    }

    if (next.chunks) {
      await untilSpoken();
      endUtterance();
      setBusy(false);
    }

    disarmBargeIn(next);
    if (inflight === next) inflight = null;
  } catch {

  } finally {
    if (req.barge === controller) req.barge = null;
  }
}

let idleMuted = false;
let idlePoll = null;

async function waitForOpener() {
  if (idleMuted) return;
  const controller = new AbortController();
  idlePoll = controller;
  const req = { cancelled: false, text: '', chunks: 0, barge: null };

  try {
    const res = await fetch(`${BRIDGE}/idle/listen?timeout=120`,
                            { signal: controller.signal });
    if (!res.ok) throw new Error('idle poll failed');

    for await (const ev of readEvents(res)) {
      if (ev.type === 'disabled') { idleMuted = true; return; }

      if (busy || recording) return;
      if (ev.type === 'chunk') {
        if (!req.chunks) { inflight = req; setBusy(true, 'speaking'); }
        await playChunk(ev, req);
      }
    }
    if (req.chunks) {
      await untilSpoken();
      endUtterance();
    }
  } catch {

  } finally {
    if (idlePoll === controller) idlePoll = null;

    if (req.chunks) {
      disarmBargeIn(req);
      if (inflight === req) inflight = null;
      setBusy(false);
    }
  }
}

let openerLoopRunning = false;

async function startOpenerPoll() {
  if (openerLoopRunning) return;
  openerLoopRunning = true;
  for (;;) {
    await waitForOpener();
    await new Promise((r) => setTimeout(r, idleMuted ? 30000 : 1500));
  }
}

function setIdleMuted(value) {
  idleMuted = !!value;
  post('/idle/mute', { muted: idleMuted }).catch(() => {});
  if (idleMuted && idlePoll) {
    try { idlePoll.abort(); } catch {   }
  }
}

function disarmBargeIn(req) {
  if (req?.barge && !req.tookOver) {
    try { req.barge.abort(); } catch {   }
    req.barge = null;
  }
}

async function interrupt() {
  if (!inflight && utterance.epoch < 0) return 0;
  const heard = stopSpeaking();
  if (inflight) inflight.cancelled = true;
  setBusy(false);
  try {
    await post('/interrupt', { chunks: heard });
  } catch {   }
  return heard;
}

async function toggleListen() {
  if (busy && !recording) return;

  if (!recording) {
    try {
      await post('/listen/start');
      recording = true;
      btnMic.classList.add('recording');
      setStatus('busy', 'listening…');
      hideNotice('bridge');
    } catch {
      bridgeLost();
    }
    return;
  }

  recording = false;
  btnMic.classList.remove('recording');
  setBusy(true, 'transcribing');
  const req = newRequest();
  try {
    const res = await fetch(BRIDGE + '/listen/stop/stream', { method: 'POST' });

    await consumeReply(res, req);
  } catch (e) {
    if (!req.cancelled) showNotice(`Voice failed: ${e.message}`);
  } finally {
    disarmBargeIn(req);
    if (inflight === req) inflight = null;
    setBusy(false);
  }
}

function sendFromInput() {
  const text = input.value;
  input.value = '';
  send(text);
}

btnSend.addEventListener('click', sendFromInput);

input.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') sendFromInput();
  if (e.key === 'Escape') input.blur();
});

async function lookAtScreen() {
  if (busy) return;
  setBusy(true, 'looking…');
  hideNotice('bridge');

  const shot = await window.marina.captureScreen();
  if (shot.error) {
    setBusy(false);
    showNotice(shot.error, 'vision');
    return;
  }

  const question = input.value.trim();
  input.value = '';
  say(question || 'Let me look…');

  setBusy(true, 'thinking');
  try {
    await handleResult(await post('/see', {
      image: shot.image, mime: shot.mime, question,
    }));
  } catch {
    setBusy(false);
    bridgeLost();
  }
}

el('btn-see').addEventListener('click', lookAtScreen);
window.marina.onLookAtScreen(lookAtScreen);

btnMic.addEventListener('click', toggleListen);
window.marina.onToggleListen(toggleListen);

window.marina.onInterrupt?.(() => { interrupt(); });

window.marina.onSetOpeners?.((on) => {
  setIdleMuted(!on);
  if (!idleMuted) startOpenerPoll();
});

let brainMode = 'auto';

function paintBrain(mode, current, model) {
  brainMode = mode;
  const b = el('btn-brain');
  if (!b) return;
  const where = mode === 'auto' ? `auto → ${current || '?'}` : mode;
  b.title = `${where}${model ? ` · ${model}` : ''} — click to change`;
  b.classList.toggle('on', mode === 'local');
}

function pickItem(label, sub, selected, onClick, dim) {
  const d = document.createElement('div');
  d.className = 'pick-item' + (selected ? ' on' : '') + (dim ? ' dim' : '');
  d.innerHTML = `<span class="tick">${selected ? '\u2713' : ''}</span><span>${label}</span>`;
  if (sub) d.title = sub;
  if (!dim) d.addEventListener('click', onClick);
  return d;
}

async function openPicker() {
  const panel = el('picker');
  const list = el('pick-list');
  list.textContent = 'loading…';
  panel.classList.remove('hidden');

  let data;
  try {
    data = await (await fetch(`${BRIDGE}/models`)).json();
  } catch {
    list.textContent = 'bridge unreachable';
    return;
  }

  list.innerHTML = '';

  list.appendChild(pickItem(
    'Automatic', 'Prefer the server, fall back to this Mac',
    data.mode === 'auto',
    async () => { await post('/backend', { mode: 'auto' }); await refreshBrain(); closePicker(); },
  ));

  for (const which of ['server', 'local']) {
    const models = data[which] || [];
    const head = document.createElement('div');
    head.className = 'pick-group';
    head.textContent = which === 'server' ? 'GPU server' : 'This Mac';
    list.appendChild(head);

    if (!models.length) {
      list.appendChild(pickItem(
        which === 'server' ? 'unreachable' : 'no models found', '', false, null, true));
      continue;
    }
    for (const m of models) {
      const on = data.mode === which && data.selected[which] === m;
      list.appendChild(pickItem(m, `Run ${m} on the ${which}`, on, async () => {
        await post('/model', { backend: which, model: m });
        await refreshBrain();
        say(which === 'local' ? `Running ${m} here.` : `Using ${m} on the server.`);
        closePicker();
      }));
    }
  }
}

function closePicker() { el('picker').classList.add('hidden'); }

function noteBackendUsed(data) {
  if (!data || !data.backend) return;
  const label = data.backend === 'local' ? 'this Mac' : 'GPU server';
  setStatus('ok', `${label} · ${data.model || ''}`.trim());
  if (data.backend === 'local' && brainMode === 'auto') {
    showNotice('GPU server did not answer — running on this Mac.', 'failover');
  } else {
    hideNotice('failover');
  }
}

async function refreshBrain() {
  try {
    const h = await (await fetch(`${BRIDGE}/health`)).json();
    paintBrain(h.llm_mode, h.llm_using, h.model);
    setStatus('ok', `${h.llm_using} · ${h.model}`);
  } catch {   }
}

function togglePicker() {
  el('picker').classList.contains('hidden') ? openPicker() : closePicker();
}
el('status').addEventListener('click', togglePicker);
el('status').addEventListener('keydown', (e) => {
  if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); togglePicker(); }
});
el('btn-brain').addEventListener('click', () => {
  togglePicker();
});
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closePicker(); });

el('btn-quit').addEventListener('click', () => window.marina.quit());
el('btn-hide').addEventListener('click', () => window.marina.minimize());

async function chooseModel() {
  const res = await window.marina.pickVRM();
  if (res.canceled) return;
  try {
    await mountVRM(res.buffer, res.name);
  } catch (e) {
    showNotice(`Could not load ${res.name}: ${e.message}`, 'model');
  }
}

el('btn-model').addEventListener('click', chooseModel);
window.marina.onPickModel(chooseModel);

el('btn-reset').addEventListener('click', async () => {
  try {
    await post('/reset');
    say('Fine, forgotten.');
  } catch {   }
});

window.__marina = {
  get vrm() { return vrm; },
  get bones() { return bones; },
  get mouthOpen() { return mouthOpen; },
  get viseme() { return viseme; },
  restyleFace,
  LIPS,
  get camera() { return camera; },
  get springs() { return springs; },
  get mouthCloseTargets() { return mouthCloseTargets; },
  get cueOut() { return cueOut; },
  get activeCues() { return activeCues.length; },
  drawGesture: () => drawGesture(),
  hitTest: (x, y) => overUI(x, y) || overAvatar(x, y),
  scheduleCues,
  speak,
  send,
  interrupt,
  isSpeaking: () => playing > 0,

  get utterance() {
    return {
      epoch: utterance.epoch,
      now: audioCtx ? audioCtx.currentTime : 0,
      chunks: utterance.chunks.map((c) => ({ index: c.index, start: c.start, end: c.end })),
    };
  },
  get pendingCues() { return pendingCues.slice(); },
  audioState: () => (audioCtx ? audioCtx.state : 'none'),
  THREE,
};

let bridgeReady = false;
let polling = false;

async function pollForBridge({ quietFor = 16000 } = {}) {
if (polling) return;
polling = true;

const started = Date.now();
let announced = false;

while (true) {
    try {
      const res = await fetch(`${BRIDGE}/health`, { signal: AbortSignal.timeout(2000) });
      if (res.ok) {
        const info = await res.json();
        bridgeReady = true;
        polling = false;

        const see = el('btn-see');
        if (see) see.hidden = !info.vision;
        paintBrain(info.llm_mode || 'auto', info.llm_using, info.model);
        setStatus('ok', `ready · ${info.model}`);
        hideNotice('bridge');

        post('/warmup').catch(() => {});
        bargeEnabled = info.barge_in !== false;
        if (info.idle) idleMuted = !!info.idle.muted || info.idle.enabled === false;
        startOpenerPoll();
        return;
      }
    } catch {

    }

    const waited = Date.now() - started;
    if (waited < quietFor) {

      setStatus('busy', 'starting…');
    } else if (!announced) {
      announced = true;
      setStatus('bad', 'bridge down');
      showNotice(BRIDGE_DOWN, 'bridge');
    }

    await new Promise((r) => setTimeout(r, waited < quietFor ? 400 : 2000));
}
}

function bridgeLost() {
bridgeReady = false;
pollForBridge({ quietFor: 0 });
}

el('btn-see').hidden = true;

pollForBridge();
loadFromDisk();
