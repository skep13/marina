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

// ============================================================
//  Three.js scene
// ============================================================

const renderer = new THREE.WebGLRenderer({
  canvas,
  alpha: true,             // transparent framebuffer -> transparent desktop window
  antialias: true,
  // The click-through hit test reads a pixel back after the frame is drawn,
  // which is only valid if the buffer survives the composite.
  preserveDrawingBuffer: true,
});
renderer.setClearColor(0x000000, 0);
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.outputColorSpace = THREE.SRGBColorSpace;

const scene = new THREE.Scene();               // no background => stays transparent

// A narrow FOV is a long lens. Wide angles up close enlarge the nearest
// feature (the head) and read as caricature; ~21 deg is portrait territory.
const camera = new THREE.PerspectiveCamera(21, 1, 0.1, 20);

const key = new THREE.DirectionalLight(0xffffff, 2.0);
key.position.set(1, 1.6, 2.2);
scene.add(key);
scene.add(new THREE.AmbientLight(0xffffff, 1.2));

// three-vrm drives the eyes toward this object; parenting it to the camera
// means "look at the cursor" is just a small offset in view space.
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

// ============================================================
//  VRM
// ============================================================

let vrm = null;
let bones = {};
let basePose = {};
let springs = [];        // { joint, dir, power } captured at load
let mouthCloseTargets = [];   // VRoid's Fcl_MTH_Close morph, per face mesh

const loader = new GLTFLoader();
loader.register((parser) => new VRMLoaderPlugin(parser));

function frameUpperBody(v) {
  // Aim the camera at the head and pull back enough to see head + shoulders.
  const head = v.humanoid?.getNormalizedBoneNode('head');
  const target = new THREE.Vector3();
  if (head) {
    v.scene.updateWorldMatrix(true, true);
    head.getWorldPosition(target);
  } else {
    new THREE.Box3().setFromObject(v.scene).getCenter(target);
  }
  // Frame head-to-waist rather than just the face: pick the distance that
  // makes VIEW_HEIGHT metres of the avatar fill the window vertically.
  const VIEW_HEIGHT = 0.67;                 // metres of avatar in frame
  const DROP = 0.06;                        // how far below the head to centre
  const fovRad = (camera.fov * Math.PI) / 180;
  const dist = VIEW_HEIGHT / (2 * Math.tan(fovRad / 2));

  // VRM avatars face +Z once three-vrm has normalised them, so the camera
  // belongs on the +Z side.
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

  // No-op for VRM 1.0; rotates 0.x models 180 deg so both face the same way.
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

// Bones the idle animation drives. Not every model rigs all of them
// (upperChest and the shoulders are optional in VRM), so each is guarded.
const IDLE_BONES = [
  'hips', 'spine', 'chest', 'upperChest', 'neck', 'head',
  'leftShoulder', 'rightShoulder',
  'leftUpperArm', 'rightUpperArm',
  'leftLowerArm', 'rightLowerArm',
  'leftHand', 'rightHand',
];

// VRM's rest pose is a T-pose with the arms straight out to the sides.
// This is the relaxed standing pose everything else is layered on top of.
// Z swings the arms down; asymmetry keeps it from looking like a mannequin.
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

/** Offset a bone from its rest pose. Additive, so layers compose. */
function poseBone(name, dx, dy, dz) {
  const node = bones[name];
  const base = basePose[name];
  if (!node || !base) return;
  node.rotation.set(base.x + dx, base.y + (dy || 0), base.z + (dz || 0));
}

// ---------------------------------------------------------------------------
//  Lip colour
//
//  The lips are painted into the face-skin texture, so there's no material to
//  tint — the pixels have to change. Luckily they're the only strongly
//  saturated thing on that texture, and they sit in a known patch of UV space
//  (the cheek blush is saturated too, but lives lower down), so a box plus a
//  saturation floor isolates them cleanly.
//
//  Measured on this model: lips at u 0.44-0.56, v 0.74-0.78, saturation > 0.22,
//  where nothing else on the texture exceeds 0.20 inside that box.
// ---------------------------------------------------------------------------

const LIPS = {
  // Fractions of texture size, so this survives a different texture resolution.
  region: { u0: 0.40, v0: 0.72, u1: 0.62, v1: 0.80 },
  minSaturation: 0.18,
  saturation: 0.42,     // multiplier: 1 = untouched, 0 = grey
  lighten: 1.06,        // slight lift so they don't read as a dark line
  hueShift: -0.012,     // nudge off pink, toward a neutral rose-brown
};

// The inner mouth is a separate, very red texture; left alone it looks lurid
// next to desaturated lips once she opens her mouth.
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

/** Repaint a texture in place. `box` is in UV fractions, or null for all of it. */
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

  // Swapping the source keeps every other texture setting (flipY, colorSpace,
  // wrapping) exactly as the loader configured it.
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

// VRoid exports the face with the lips slightly parted, and the VRM `neutral`
// expression doesn't bind the blendshape that closes them — so at rest the
// mouth hangs open. The shape exists (Fcl_MTH_Close), it's just never driven.
// Find it and drive it ourselves.
const MOUTH_CLOSE_MORPH = 'Fcl_MTH_Close';

// The VRM expression presets carry no plain brow raise, but the VRoid face
// ships the shapes — they are simply never driven outside a full expression.
// A face with a completely static brow is the other half of looking vacant.
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

/** Idle brow life. Runs after vrm.update() for the same reason the mouth does.
 *
 *  This model binds no brow morph to any VRM expression, so the brows were
 *  simply never driven — half of why a resting face reads as vacant. Nothing
 *  else writes them, so we own them outright: an earlier version took the max
 *  against the previous frame to avoid stepping on the expression system, but
 *  with nothing resetting them each frame that was a ratchet the value could
 *  never come back down from. `room` is what keeps a cue's expression clear.
 */
function applyIdleBrow(t) {
  const emoting = Math.max(
    cueOut.expr.happy || 0, cueOut.expr.sad || 0, cueOut.expr.angry || 0,
    cueOut.expr.surprised || 0, cueOut.expr.relaxed || 0,
  );
  const room = Math.max(0, 1 - emoting * 2);

  const values = {
    // Slow ambient tension, plus the lift when she re-engages with you.
    Fcl_BRW_Fun: room * (0.06 + 0.05 * noise1(t * 0.19 + 7) + browFlash * 0.22),
    // A touch of raise while she is speaking; flat brows read as bored.
    Fcl_BRW_Surprised: room * Math.max(0, mouthOpen * 0.14 + 0.03 * noise1(t * 0.23 + 19)),
    // Faint inner-brow drift, the difference between resting and blank.
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

/** Close the resting mouth, releasing as she speaks or emotes.
 *
 *  Must run AFTER vrm.update(), which rewrites every morph the expression
 *  system owns — set it before and it gets clobbered the same frame.
 */
function applyRestingMouth() {
  if (!mouthCloseTargets.length) return;

  // A deliberate cue should win over the resting shape — but the ambient mood
  // drift must NOT. On this model `happy` parts the lips, so letting the idle
  // smile release the closing morph left the mouth hanging open at rest, which
  // is the exact bug this is here to prevent.
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

/** Grab every spring-bone joint and remember its resting gravity. */
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

// ============================================================
//  Idle motion + lip sync
// ============================================================

const pointer = { x: 0, y: 0 };
window.addEventListener('mousemove', (e) => {
  pointer.x = (e.clientX / window.innerWidth) * 2 - 1;
  pointer.y = (e.clientY / window.innerHeight) * 2 - 1;
});

let blinkTimer = 1 + Math.random() * 3;
let blinkPending = 0;
let blinkT = 999;        // seconds into the current blink
let blinkDur = 0.14;

let moodTimer = 0;
let mood = 0;
let moodTarget = 0;

// ---------------------------------------------------------------------------
//  Idle gaze
//
//  Not a random walk around centre — that reads as staring through you. Real
//  idle gaze is a series of *held* fixations, mostly on the person you are
//  with, broken by aversions: a glance up while recalling, down while
//  thinking, sideways when bored. Coming back is what makes it read as being
//  with someone rather than looking past them.
//
//  Where she looks away to is not arbitrary either. Up-and-off tends to go
//  with remembering, down with turning something over.
// ---------------------------------------------------------------------------

const AVERSIONS = [
  { x: -0.38, y:  0.27, hold: [1.1, 2.4] },   // up-left, recalling
  { x:  0.36, y:  0.25, hold: [1.1, 2.4] },   // up-right
  { x: -0.27, y: -0.23, hold: [1.4, 3.0] },   // down-left, thinking
  { x:  0.25, y: -0.21, hold: [1.4, 3.0] },
  { x: -0.48, y:  0.04, hold: [1.6, 3.4] },   // sideways, drifting off
  { x:  0.46, y: -0.02, hold: [1.6, 3.4] },
];

let gazeTimer = 0;
let gazeAway = false;
const gaze = { x: 0, y: 0 };
const gazeTarget = { x: 0, y: 0 };
// The head chases the eyes rather than moving with them, so it lags.
const gazeHead = { x: 0, y: 0 };
const gazeHeadV = { x: 0, y: 0 };
// Smoothed ambient head pose, and its velocity.
const headS = { x: 0, y: 0, z: 0 };
const headV = { x: 0, y: 0, z: 0 };
// The torso trails the head down the same chain.
const torsoS = { x: 0, y: 0 };
const torsoV = { x: 0, y: 0 };
let browFlash = 0;          // brief raise on re-engaging

/** Smooth value noise. Sines at fixed frequencies visibly loop; this doesn't. */
const _hash = (i) => {
  const s = Math.sin(i * 127.1) * 43758.5453;
  return (s - Math.floor(s)) * 2 - 1;
};
function noise1(x) {
  const i = Math.floor(x), f = x - i;
  // Quintic rather than smoothstep: its second derivative is continuous too,
  // so the motion has no faint kink as it crosses each control point.
  const u = f * f * f * (f * (f * 6 - 15) + 10);
  return _hash(i) * (1 - u) + _hash(i + 1) * u;
}

/** Two octaves. One octave drifts evenly; real movement has a fine tremor
 *  riding on the slow wander. */
function fbm(x) {
  return noise1(x) * 0.72 + noise1(x * 2.7 + 13.7) * 0.28;
}

let audioCtx = null;
let analyser = null;
let freqData = null;
let timeData = null;
let currentSource = null;
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

/** Play base64 WAV from the bridge and drive the mouth from its envelope. */
async function speak(base64, onStart) {
  const ctx = ensureAudio();

  const bin = atob(base64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);

  const buffer = await ctx.decodeAudioData(bytes.buffer);

  if (currentSource) {
    try { currentSource.stop(); } catch { /* already ended */ }
  }

  const src = ctx.createBufferSource();
  src.buffer = buffer;
  src.connect(analyser);
  currentSource = src;

  onStart?.(buffer.duration);

  return new Promise((resolve) => {
    src.onended = () => {
      if (currentSource === src) currentSource = null;
      resolve();
    };
    src.start();
  });
}

/** Lip sync.
 *
 *  Jaw opening comes from loudness, but a mouth that only opens and closes
 *  reads as a puppet. Vowel *shape* comes from where the energy sits in the
 *  spectrum: the first two formants roughly separate open/closed (F1) and
 *  front/back (F2), so the ratio between those bands picks between the five
 *  visemes the model rigs. Sibilants ("s", "sh") are almost all high-frequency
 *  energy with a nearly closed mouth, so they get detected and damped —
 *  otherwise every "s" reads as a shout.
 */
const DB_FLOOR = -46;    // below this the mouth is closed
const DB_CEIL = -14;     // at this it is fully open

// Band edges in Hz, resolved to FFT bins once the context sample rate is known.
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

// Current and target weights per viseme. Each is smoothed on its own so the
// mouth morphs between shapes instead of snapping.
const VISEMES = ['aa', 'ih', 'ou', 'ee', 'oh'];
const viseme = { aa: 0, ih: 0, ou: 0, ee: 0, oh: 0 };
const visemeTarget = { aa: 0, ih: 0, ou: 0, ee: 0, oh: 0 };

function updateMouth(dt) {
  let open = 0;

  for (const v of VISEMES) visemeTarget[v] = 0;

  if (currentSource && analyser) {
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
    // Jaw opening isn't linear in loudness.
    open = Math.pow(open, 1.35) * 0.92;
    if (open < 0.05) open = 0;

    analyser.getByteFrequencyData(freqData);
    const e1 = bandEnergy(bandBins.f1);
    const e2 = bandEnergy(bandBins.f2);
    const e3 = bandEnergy(bandBins.sib);

    const voiced = e1 + e2;
    const frontness = voiced > 0.001 ? clamp01(e2 / voiced) : 0.4;
    const sibilance = (voiced + e3) > 0.001 ? clamp01(e3 / (voiced + e3)) : 0;

    // A sibilant is a near-closed mouth, not an open one.
    if (sibilance > 0.45) open *= 1 - (sibilance - 0.45) * 1.2;

    // Overlapping tents across the front/back axis, so neighbouring vowels
    // blend rather than pop.
    const w = {
      ee: clamp01((frontness - 0.58) * 3.4),
      ih: clamp01(1 - Math.abs(frontness - 0.52) * 4.2),
      aa: clamp01(1 - Math.abs(frontness - 0.34) * 3.6),
      oh: clamp01((0.36 - frontness) * 3.6),
      ou: clamp01((0.28 - frontness) * 4.0),
    };
    // Rounded vowels close the mouth; open ones need the jaw down.
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

  // Attack fast, release slower — reads as speech, not a flapping jaw.
  for (const v of VISEMES) {
    const t = visemeTarget[v];
    const rate = t > viseme[v] ? 24 : 12;
    viseme[v] += (t - viseme[v]) * Math.min(1, rate * dt);
  }

  // A single scalar for everything that reacts to "is she talking".
  mouthOpen = clamp01(viseme.aa + viseme.oh + viseme.ee * 0.6 + viseme.ih * 0.6 + viseme.ou * 0.5);

  const em = vrm?.expressionManager;
  if (!em) return;
  for (const v of VISEMES) em.setValue(v, viseme[v]);
}

const TAU = Math.PI * 2;

/** The torso, kept deliberately small.
 *
 *  At portrait framing the arms, hips and legs are off-screen, so animating
 *  them is wasted work. What's left is a trace of breathing through the
 *  shoulders — enough that the frame isn't a freeze-frame, and enough to give
 *  the spring bones something to react to.
 */
function updateBody(t, dtBody) {
  // Breathing is not a sine. The in-breath is quicker than the out-breath,
  // and the period wanders — a metronome is the giveaway.
  const bphase = t * 0.21 + 0.07 * noise1(t * 0.05);
  const bw = bphase - Math.floor(bphase);
  const breath = (bw < 0.4
    ? Math.sin((bw / 0.4) * Math.PI * 0.5)
    : Math.cos(((bw - 0.4) / 0.6) * Math.PI * 0.5)) * 2 - 1;

  // People are not equally animated minute to minute. A slow envelope gives
  // her livelier stretches and calmer ones instead of a constant activity
  // level, which is the other half of what reads as mechanical.
  const energy = 0.68 + 0.42 * noise1(t * 0.035 + 3);

  // ---- weight shift -------------------------------------------------
  // Nobody stands evenly on both feet for long. A very slow lateral shift
  // through the hips, with the spine leaning back the other way so she stays
  // over her own centre rather than toppling.
  const shift = fbm(t * 0.031 + 61) * energy;

  // ---- the torso follows the head -----------------------------------
  // Later and less than the head, which is itself later and less than the
  // eyes. That descending chain is what makes a turn read as one movement
  // through a body instead of three parts moving independently.
  const TK = 2.6, TC = 2.9;
  torsoV.y += (TK * (gazeHead.x - torsoS.y) - TC * torsoV.y) * dtBody;
  torsoV.x += (TK * (-gazeHead.y - torsoS.x) - TC * torsoV.x) * dtBody;
  torsoS.y += torsoV.y * dtBody;
  torsoS.x += torsoV.x * dtBody;

  const twist = torsoS.y * 0.30;      // yaw carried by the torso
  const lean  = torsoS.x * 0.10;

  // Each bone gets one call: poseBone sets from rest rather than accumulating,
  // so every contribution for a bone has to be summed here.
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
  poseBone('leftShoulder', -0.010 * breath - lift, 0, 0.006 * breath + lift * 0.5);
  poseBone('rightShoulder', -0.010 * breath - lift, 0, -0.006 * breath - lift * 0.5);

  // ---- arms ----------------------------------------------------------
  // Mostly passive: they hang off a torso that is moving, so they swing a
  // little against it and settle a beat later. A touch of independent drift
  // on top, out of phase left to right, so they aren't a mirrored pair.
  const armL = fbm(t * 0.077 + 11) * energy;
  const armR = fbm(t * 0.071 + 29) * energy;
  const swing = twist * 0.55;         // arms lag the twist, so they trail it

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

  // Head motion is what actually swings the hair, so it carries most of the
  // life in this framing. Split across neck and head so the skull isn't
  // pivoting on a stick.
  const talk = mouthOpen;

  // Noise rather than sines: fixed frequencies beat against each other into a
  // pattern you start to recognise after a minute of watching her.
  const nx = fbm(t * 0.13);
  const ny = fbm(t * 0.11 + 40);
  const nz = fbm(t * 0.09 + 80);

  // The head carries part of the gaze shift, a beat behind the eyes. Without
  // this the eyes slide about in a head that is doing something unrelated,
  // which is most of what makes an idle avatar look vacant.
  const followX = -gazeHead.y * 0.19;
  const followY = gazeHead.x * 0.40;

  // The ambient layer — drift, gaze-following, breathing sway — goes through
  // its own soft filter before anything else is added. Every source feeding it
  // (a stepped saccade target, a noise field, an energy envelope) has its own
  // character, and filtering the sum is what stops those seams showing as
  // snap. Deliberate cues are added *after* it, so a nod stays a nod instead
  // of being smoothed into a nod-shaped smudge.
  // Only the raw sources go through it. The gaze-follow already came out of
  // its own spring, and running it through a second filter in series ate the
  // motion — head range fell to 5 degrees and the head stopped visibly
  // tracking the eyes at all. It is added after, still smooth, undiminished.
  const idleX = pointer.y * 0.09 + 0.016 * nx * energy;
  const idleY = pointer.x * 0.17 + 0.034 * ny * energy;
  const idleZ = 0.018 * nz * energy;

  const HK = 5.0, HC = 4.2;          // 0.36 Hz, near-critically damped
  headV.x += (HK * (idleX - headS.x) - HC * headV.x) * dtBody;
  headV.y += (HK * (idleY - headS.y) - HC * headV.y) * dtBody;
  headV.z += (HK * (idleZ - headS.z) - HC * headV.z) * dtBody;
  headS.x += headV.x * dtBody;
  headS.y += headV.y * dtBody;
  headS.z += headV.z * dtBody;

  const x = headS.x + followX + talk * 0.045 * Math.sin(t * 7.1) + cueOut.hx;
  const y = headS.y + followY + talk * 0.030 * Math.sin(t * 3.1) + cueOut.hy;
  const z = headS.z - followY * 0.13 + cueOut.hz;

  poseBone('neck', x * 0.40, y * 0.40, z * 0.5);
  poseBone('head', x * 0.60, y * 0.60, z * 0.5);
}

// ---------------------------------------------------------------------------
//  Action cues
//
//  The model writes physical actions as *tilts head*. The bridge strips those
//  out of the spoken text and sends them here with a position in the reply, so
//  each one fires at roughly the moment it would have been said.
//
//  Only the head, face and shoulders are on camera, so every cue is built from
//  those. `p` is 0..1 progress through the cue.
// ---------------------------------------------------------------------------

const ease = (p) => Math.sin(p * Math.PI);               // up and back down
const settle = (p) => Math.sin(p * Math.PI) * (1 - p);   // overshoot, then rest

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
                 o.hx += ease(p) * 0.16;                  // head drops
                 o.expr.sad = ease(p) * 0.45;
                 o.shoulder -= ease(p) * 0.06;
               } },
  pout:      { dur: 1.8, run: (p, o) => { o.expr.angry = ease(p) * 0.55; o.hy += ease(p) * 0.07; } },
  sad:       { dur: 2.0, run: (p, o) => { o.expr.sad = ease(p) * 0.7; o.hx += ease(p) * 0.12; } },
  surprised: { dur: 1.2, run: (p, o) => {
                 o.expr.surprised = ease(p) * 0.85;
                 o.hx -= settle(p) * 0.18;                // head pulls back
               } },
  blush:     { dur: 2.2, run: (p, o) => {
                 o.expr.happy = ease(p) * 0.4;
                 o.hy += ease(p) * 0.16;                  // looks away
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

// Expressions a cue can drive, so we know what to clear each frame.
const CUE_EXPRESSIONS = ['happy', 'sad', 'angry', 'relaxed', 'surprised'];

let pendingCues = [];   // { animation, at } seconds from cue-clock start
let activeCues = [];    // { animation, elapsed, dur }
let cueClock = -1;      // seconds since the reply started, or -1 when idle

const cueOut = { hx: 0, hy: 0, hz: 0, shoulder: 0, gazeX: 0, gazeY: 0, blinkLeft: 0, expr: {} };
const cueScratch = { hx: 0, hy: 0, hz: 0, shoulder: 0, gazeX: 0, gazeY: 0, blinkLeft: 0, expr: {} };

/** Queue a reply's cues against the real audio duration. */
function scheduleCues(cues, duration) {
  pendingCues = (cues || []).map((c) => ({
    animation: c.animation,
    at: Math.max(0, (c.fraction ?? 0) * duration - 0.15),   // land slightly early
  }));
  activeCues = [];
  cueClock = pendingCues.length ? 0 : -1;
}

// ---------------------------------------------------------------------------
//  Spontaneous gestures
//
//  Between replies she only drifted, which is most of what still read as
//  robotic: a person waiting is not motionless, they shift and glance and
//  settle. These are the same cues the model can ask for, fired on her own.
//
//  Drawn from a shuffled bag rather than picked at random each time. Plain
//  random repeats itself in clumps — three tilts in a row — and a fixed list
//  is worse, because you learn the order. A bag gives every gesture an outing
//  before any repeats, reshuffled each pass, and never lets the reshuffle
//  butt the same gesture against itself.
// ---------------------------------------------------------------------------

const IDLE_GESTURES = ['tilt', 'lean', 'smile', 'nod', 'shrug', 'think', 'brow', 'sigh', 'eyeroll', 'stare'];

let gestureBag = [];
let lastGesture = null;
let gestureTimer = 6 + Math.random() * 8;

function drawGesture() {
  if (!gestureBag.length) {
    gestureBag = IDLE_GESTURES.slice();
    for (let i = gestureBag.length - 1; i > 0; i--) {      // Fisher-Yates
      const j = (Math.random() * (i + 1)) | 0;
      [gestureBag[i], gestureBag[j]] = [gestureBag[j], gestureBag[i]];
    }
    // Don't let a fresh shuffle hand back what just played.
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
  // Never on top of a reply — those cues are timed to her words.
  if (cueClock >= 0 || mouthOpen > 0.05) { gestureTimer = Math.max(gestureTimer, 2.5); return; }

  gestureTimer -= dt;
  if (gestureTimer > 0) return;
  gestureTimer = 7 + Math.random() * 11;

  const def = CUES[drawGesture()];
  // Stretched and damped: the cue shapes are written for punctuating speech,
  // and at that intensity an unprompted one lands as a jolt.
  if (def) activeCues.push({ run: def.run, elapsed: 0, dur: def.dur * 1.8, gain: 0.5 });
}

function updateCues(dt) {
  cueOut.hx = cueOut.hy = cueOut.hz = 0;
  cueOut.shoulder = cueOut.gazeX = cueOut.gazeY = cueOut.blinkLeft = 0;
  for (const name of CUE_EXPRESSIONS) cueOut.expr[name] = 0;

  if (cueClock >= 0) {
    cueClock += dt;
    while (pendingCues.length && pendingCues[0].at <= cueClock) {
      const next = pendingCues.shift();
      const def = CUES[next.animation] || CUES.emote;
      activeCues.push({ run: def.run, elapsed: 0, dur: def.dur });
    }
    if (!pendingCues.length && !activeCues.length) cueClock = -1;
  }

  for (let i = activeCues.length - 1; i >= 0; i--) {
    const c = activeCues[i];
    c.elapsed += dt;
    const p = c.elapsed / c.dur;
    if (p >= 1) { activeCues.splice(i, 1); continue; }

    if (c.gain === undefined || c.gain === 1) { c.run(p, cueOut); continue; }

    // A spontaneous gesture is a smaller version of the same movement. Run it
    // into a scratch buffer and fold the result in at reduced strength, so an
    // unprompted shrug is a shift in the seat rather than a performance.
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

// Most of this model's spring joints ship with gravityPower: 0, which means
// gravityDir alone does nothing — it gets multiplied by zero. So the breeze has
// to supply its own magnitude: compose (restGravity * restPower) + wind, then
// feed the solver the resulting direction AND length.
const WIND_STRENGTH = 0.15;

const _wind = new THREE.Vector3();
const _force = new THREE.Vector3();

function updateHair(t) {
  if (!springs.length) return;

  // Two slow components plus a faster flutter, under a slower gust envelope,
  // so it breathes instead of oscillating.
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

/** Eyes and face — the part you actually see at this crop. */
function updateGaze(dt, t) {
  gazeTimer -= dt;
  if (gazeTimer <= 0) {
    const from = { x: gazeTarget.x, y: gazeTarget.y };

    if (gazeAway) {
      // Come back. Settling near the eyes rather than exactly on them, so it
      // is not the identical spot every time.
      gazeAway = false;
      gazeTarget.x = (Math.random() - 0.5) * 0.10;
      gazeTarget.y = (Math.random() - 0.5) * 0.07;
      gazeTimer = 1.6 + Math.random() * 3.4;
      browFlash = 1;                     // brows lift a touch on re-engaging
    } else if (Math.random() < 0.45) {
      gazeAway = true;
      const a = AVERSIONS[(Math.random() * AVERSIONS.length) | 0];
      gazeTarget.x = a.x + (Math.random() - 0.5) * 0.10;
      gazeTarget.y = a.y + (Math.random() - 0.5) * 0.08;
      gazeTimer = a.hold[0] + Math.random() * (a.hold[1] - a.hold[0]);
    } else {
      // Still on you, just not frozen: a small shift within the face.
      gazeTarget.x = (Math.random() - 0.5) * 0.14;
      gazeTarget.y = (Math.random() - 0.5) * 0.10;
      gazeTimer = 1.3 + Math.random() * 2.2;
    }

    // People often, but not always, blink through a large gaze shift. Firing
    // on every one of them pushed the rate to 34/min against a human resting
    // rate of 15-20, which reads as nervous rather than alive.
    const jump = Math.hypot(gazeTarget.x - from.x, gazeTarget.y - from.y);
    if (jump > 0.28 && blinkTimer > 0.9 && Math.random() < 0.4) blinkTimer = 0.02;
  }

  // Saccades snap; they don't glide. Larger ones take measurably longer than
  // small ones, so the rate falls off with distance rather than every jump
  // taking the same time regardless of how far it goes.
  const dist = Math.hypot(gazeTarget.x - gaze.x, gazeTarget.y - gaze.y);
  const k = Math.min(1, dt * (13 - Math.min(7, dist * 9)));
  gaze.x += (gazeTarget.x - gaze.x) * k;
  gaze.y += (gazeTarget.y - gaze.y) * k;

  // Ocular drift: the eye never truly holds still on a fixation.
  const driftX = noise1(t * 1.7) * 0.012;
  const driftY = noise1(t * 1.4 + 31) * 0.009;

  // The head follows the eyes, late and only part of the way. This coupling
  // is what stops the head and eyes reading as two separate mechanisms.
  //
  // A spring rather than an exponential lag. An exponential approach eases in
  // and never overshoots, which is precisely the motion that reads as
  // mechanical; damping below critical (2*sqrt(K) = 10.2 here) lets the head
  // carry slightly past the mark and settle back, the way a real one does.
  // K=26 was a 0.81 Hz head settling in ~0.6s — brisk enough to read as a
  // servo; a real head turn takes over a second. Softening this costs no
  // range, because a spring still converges on its target either way; it only
  // changes how it gets there. C sits just under critical (2*sqrt(6) = 4.9),
  // leaving a trace of overshoot so it settles rather than arrives.
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
    blinkDur = 0.11 + Math.random() * 0.07;   // no two blinks the same length
    if (blinkPending > 0) {
      blinkPending -= 1;
      blinkTimer = 2.4 + Math.random() * 4.6;
    } else if (Math.random() < 0.25) {
      blinkPending = 1;        // people often blink twice in quick succession
      blinkTimer = 0.24;
    } else {
      blinkTimer = 2.4 + Math.random() * 4.6;
    }
  }
  // A blink is not symmetric: the lid snaps shut in roughly a third of the
  // time it takes to open again. Decaying one linear value did both halves at
  // the same rate, which is a shutter, not an eyelid.
  blinkT += dt;
  const bp = blinkT / blinkDur;
  const blink = bp >= 1 ? 0
    : bp < 0.32
      ? Math.pow(bp / 0.32, 0.62)                    // snap shut
      : Math.pow(1 - (bp - 0.32) / 0.68, 1.7);       // ease back open
  const em = vrm.expressionManager;
  if (!em) return;

  if (cueOut.blinkLeft > 0.01) {
    // A wink: one eye closes on its own, the other keeps blinking normally.
    em.setValue('blink', 0);
    em.setValue('blinkLeft', Math.max(blink, cueOut.blinkLeft));
    em.setValue('blinkRight', blink);
  } else {
    em.setValue('blinkLeft', 0);
    em.setValue('blinkRight', 0);
    em.setValue('blink', blink);
  }
}

/** A slow drift between neutral and a faint smile, so the face isn't a mask. */
function updateMood(dt) {
  const em = vrm.expressionManager;
  if (!em) return;

  moodTimer -= dt;
  if (moodTimer <= 0) {
    moodTimer = 4 + Math.random() * 9;
    // Kept low deliberately: this expression opens the mouth on VRoid models,
    // and a resting smile should be closed-lipped.
    moodTarget = Math.random() < 0.5 ? 0 : 0.05 + Math.random() * 0.10;
  }
  mood += (moodTarget - mood) * Math.min(1, dt * 1.3);

  // 'happy' moves the mouth too, so back off while she's speaking or it
  // fights the visemes. A cue always wins over the idle mood.
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
    // Mouth first: the idle layer reads mouthOpen to add a talking nod.
    updateMouth(dt);
    updateCues(dt);
    updateIdleGestures(dt);
    updateGaze(dt, t);       // before the body: the head reads the gaze target
    updateBody(t, dt);
    updateBlink(dt);
    updateMood(dt);
    updateHair(t);

    // Drives the humanoid rig, expressions, lookAt and the hair/skirt
    // spring bones — which is what makes the idle motion carry.
    vrm.update(dt);

    // After update, so the expression system doesn't overwrite it.
    applyRestingMouth();
    applyIdleBrow(t);
  }

  renderer.render(scene, camera);
  updateClickThrough();          // after render: the hit test reads the frame
}

// ============================================================
//  Click-through
//
//  The window is a big transparent rectangle and, to the mouse, entirely
//  solid — so it swallows every click on the desktop behind it. Main keeps it
//  ignoring the mouse; this decides when to hand it back, by testing what is
//  actually under the cursor: a visible control, or a non-transparent pixel
//  of her. Everything else clicks through to whatever is behind.
// ============================================================

const gl = renderer.getContext();
const probe = new Uint8Array(4);
const UI = ['#bar', '#chrome', '#status', '#bubble', '#picker', '#notice', '#drag-strip'];

function overUI(x, y) {
  const hit = document.elementFromPoint(x, y);
  if (!hit) return false;
  for (const sel of UI) {
    const box = hit.closest(sel);
    if (!box) continue;
    // The bar and chrome are opacity:0 until hovered, but still hit-testable —
    // without this check their invisible footprints would block clicks.
    if (sel === '#drag-strip') return true;
    return parseFloat(getComputedStyle(box).opacity) > 0.05;
  }
  return false;
}

function overAvatar(x, y) {
  const r = renderer.getPixelRatio();
  const px = Math.round(x * r);
  const py = Math.round((window.innerHeight - y) * r);   // GL origin is bottom-left
  if (px < 0 || py < 0 || px >= gl.drawingBufferWidth || py >= gl.drawingBufferHeight) return false;
  gl.readPixels(px, py, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, probe);
  return probe[3] > 12;      // ignore antialiased fringes and faint hair tips
}

let solid = null;
let cursor = null;

window.addEventListener('mousemove', (e) => {
  cursor = [e.clientX, e.clientY];
  // :hover is not dependable while the window is ignoring the mouse, and the
  // controls only become clickable once they are visible — so reveal them from
  // the forwarded move instead of relying on it.
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

// Started here, not at the render loop: the first frame calls
// updateClickThrough(), which would hit `cursor` in its temporal dead zone.
tick();

// ============================================================
//  Bridge
// ============================================================

let busy = false;
let recording = false;

function setStatus(kind, text) {
  dot.className = kind;
  statusText.textContent = text;
}

let noticeKind = null;
function showNotice(msg, kind = 'general') {
  noticeKind = kind;
  notice.textContent = msg;
  notice.classList.remove('hidden');
}
/** Only clear the notice if it belongs to the subsystem that just recovered. */
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

  // The bridge already strips the markup; `reply` is what to show.
  if (result.reply) say(result.reply);

  if (result.audio) {
    setStatus('busy', 'speaking');
    await speak(result.audio, (duration) => scheduleCues(result.cues, duration));
  } else if (result.cues && result.cues.length) {
    // No audio (TTS down, or a reply that was nothing but actions) — still
    // perform, timed off a rough reading pace of ~14 characters/second.
    scheduleCues(result.cues, Math.max(1.5, (result.speech || '').length / 14));
  }
  setBusy(false);
}

async function send(text) {
  if (busy || !text.trim()) return;
  setBusy(true, 'thinking');
  say('…');
  try {
    await handleResult(await post('/chat', { text }));
  } catch {
    setBusy(false);
    bridgeLost();
  }
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
  try {
    await handleResult(await post('/listen/stop'));
  } catch (e) {
    setBusy(false);
    showNotice(`Voice failed: ${e.message}`);
  }
}

// ============================================================
//  UI wiring
// ============================================================

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

/** Take one screenshot and ask her about it. Never automatic. */
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

  // Anything already typed becomes the question about the screen.
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

// Brain picker. Lists what each backend can actually serve and lets you
// choose explicitly — no guessing which model you're talking to.
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
  d.innerHTML = `<span class="tick">${selected ? '✓' : ''}</span><span>${label}</span>`;
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

  // Automatic first — it's the sensible default.
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

async function refreshBrain() {
  try {
    const h = await (await fetch(`${BRIDGE}/health`)).json();
    paintBrain(h.llm_mode, h.llm_using, h.model);
    setStatus('ok', `${h.llm_using} · ${h.model}`);
  } catch { /* status dot already reflects trouble */ }
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
  } catch { /* bridge down; the status dot already says so */ }
});


// Debug hook — lets the test harness sample the rig, and makes the scene
// pokeable from devtools without exporting module internals.
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
  isSpeaking: () => !!currentSource,
  audioState: () => (audioCtx ? audioCtx.state : 'none'),
  THREE,
};

// ---- boot ----

// The app launches the Python bridge as a child process, so the window is up
// well before the bridge is listening. A single health check at boot therefore
// loses the race and shows "bridge isn't running" forever. Poll instead, and
// drop back into polling any time a request fails.

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
        // The screen-look button only exists when the bridge says vision is on.
        const see = el('btn-see');
        if (see) see.hidden = !info.vision;
        paintBrain(info.llm_mode || 'auto', info.llm_using, info.model);
        setStatus('ok', `ready · ${info.model}`);
        hideNotice('bridge');
        post('/warmup').catch(() => {});
        return;
      }
    } catch {
      /* not up yet */
    }

    const waited = Date.now() - started;
    if (waited < quietFor) {
      // A cold start takes ~10s (Python imports Whisper and friends), so
      // don't cry wolf inside that window.
      setStatus('busy', 'starting…');
    } else if (!announced) {
      announced = true;
      setStatus('bad', 'bridge down');
      showNotice(BRIDGE_DOWN, 'bridge');
    }

    await new Promise((r) => setTimeout(r, waited < quietFor ? 400 : 2000));
}
}

/** Call when a request fails, so we recover instead of staying stuck. */
function bridgeLost() {
bridgeReady = false;
pollForBridge({ quietFor: 0 });
}

// Hidden until /health confirms vision is on, so it never flashes into view
// on a cold start and then vanishes.
el('btn-see').hidden = true;

pollForBridge();
loadFromDisk();
