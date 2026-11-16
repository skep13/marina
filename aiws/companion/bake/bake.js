// Bakes Marina's VRM into flat 2D cel frames: toon shading, ink lines
// from normal/depth edges, transparent background. One PNG per
// expression x (rest, blink, mouth shapes), plus a few poses, and a
// manifest.json the player reads.
//
// Open /aiws/companion/bake/ on the dev server (serve.py). ?save=1 writes
// the PNGs to aiws/companion/frames/marina/.
import { THREE, GLTFLoader, VRMLoaderPlugin, VRMUtils } from '/app/renderer/vendor/vrm-bundle.js';

const W = 768, H = 1024, SS = 2;               // output size, supersampling
const LINE_PX = 2.2;                           // ink width in output pixels
const INK = new THREE.Color('#1b1730');
const SAVE = new URLSearchParams(location.search).has('save');
const status = (t) => (document.getElementById('status').textContent = t);

// ---- what to bake ---------------------------------------------------------
// Expressions (VRM presets), each with mouth closed, blink and two mouth
// shapes, so the player can talk and blink in any mood.
const EXPRESSIONS = {
  neutral:   {},
  soft:      { happy: 0.4 },
  happy:     { happy: 1 },
  smug:      { relaxed: 0.85 },
  sad:       { sad: 0.85 },
  annoyed:   { angry: 0.7 },
  surprised: { surprised: 0.9 },
  thinking:  { relaxed: 0.25, _head: [0.05, -0.18, 0.13] },
};
const VARIANTS = {
  rest:  {},
  blink: { blink: 1 },
  talk_a: { aa: 0.75 },
  talk_o: { oh: 0.65, aa: 0.15 },
};
// Poses: bone offsets (radians) on top of the rest pose.
const POSES = {
  point: { expr: { happy: 0.35, aa: 0.3 }, bones: {
    rightUpperArm: [-0.9, 0.35, 0.45], rightLowerArm: [0, -0.9, 0], rightHand: [0, 0, 0.2],
    head: [0, 0.12, -0.05] } },
  sleep: { expr: { blink: 1, relaxed: 0.5 }, bones: {
    head: [0.38, 0.05, 0.12], neck: [0.12, 0, 0.05], spine: [0.08, 0, 0] } },
  wave:  { expr: { happy: 0.9 }, bones: {
    rightUpperArm: [0.1, 0, 0.3], rightLowerArm: [0, -1.9, 0.2], rightHand: [0, 0, -0.3] } },
};

// Same rest pose the desktop app uses (app/renderer/app.js).
const REST_POSE = {
  leftShoulder: [0, 0, 0.05], rightShoulder: [0, 0, -0.06],
  leftUpperArm: [0.06, 0, -1.24], rightUpperArm: [0.04, 0, 1.20],
  leftLowerArm: [0, 0.24, -0.10], rightLowerArm: [0, -0.20, 0.09],
  leftHand: [0, 0, -0.07], rightHand: [0, 0, 0.05],
  spine: [0.02, 0, 0], chest: [0.01, 0, 0],
};

// ---- scene ------------------------------------------------------------------
const renderer = new THREE.WebGLRenderer({ antialias: false, alpha: true, preserveDrawingBuffer: true });
renderer.setPixelRatio(1);
renderer.setSize(W, H, false);
renderer.setClearColor(0x000000, 0);
renderer.outputColorSpace = THREE.SRGBColorSpace;

const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(16, W / H, 0.1, 20);   // long lens: flatter, more 2D
const key = new THREE.DirectionalLight(0xffffff, 2.6);
key.position.set(-0.6, 1.4, 1.6);
scene.add(key, new THREE.AmbientLight(0xffffff, 0.55));

const rt = (withDepth) => {
  const t = new THREE.WebGLRenderTarget(W * SS, H * SS, { samples: 0 });
  if (withDepth) t.depthTexture = new THREE.DepthTexture(W * SS, H * SS);
  return t;
};
const colorRT = rt(true);
const normalRT = rt(false);
const normalMat = new THREE.MeshNormalMaterial();

// Composite: colour + ink where normals, depth or the silhouette change.
const quad = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), new THREE.ShaderMaterial({
  uniforms: {
    tColor: { value: colorRT.texture }, tDepth: { value: colorRT.depthTexture },
    tNormal: { value: normalRT.texture }, texel: { value: new THREE.Vector2(1 / (W * SS), 1 / (H * SS)) },
    line: { value: LINE_PX * SS * 0.5 }, ink: { value: INK },
    near: { value: camera.near }, far: { value: camera.far },
  },
  vertexShader: 'varying vec2 vUv; void main(){ vUv = uv; gl_Position = vec4(position.xy, 0., 1.); }',
  fragmentShader: `
    uniform sampler2D tColor, tDepth, tNormal; uniform vec2 texel; uniform float line, near, far; uniform vec3 ink;
    varying vec2 vUv;
    float lin(float d){ float z = d * 2. - 1.; return (2. * near * far) / (far + near - z * (far - near)); }
    float edgeAt(vec2 uv){
      vec2 o = texel * line;
      vec3 n0 = texture2D(tNormal, uv).rgb;
      float a0 = texture2D(tColor, uv).a, d0 = lin(texture2D(tDepth, uv).r);
      float e = 0.;
      for (int i = 0; i < 8; i++) {
        float ang = float(i) * 0.785398;
        vec2 p = uv + vec2(cos(ang), sin(ang)) * o;
        e = max(e, length(texture2D(tNormal, p).rgb - n0) * 1.6);          // creases
        e = max(e, abs(lin(texture2D(tDepth, p).r) - d0) * 9.);             // overlaps
        e = max(e, abs(texture2D(tColor, p).a - a0) * 2.);                  // silhouette
      }
      return smoothstep(0.45, 0.75, e);
    }
    void main(){
      vec4 c = vec4(0.); float e = 0.;
      for (int x = 0; x < 2; x++) for (int y = 0; y < 2; y++) {           // 2x2 downsample
        vec2 uv = vUv + (vec2(float(x), float(y)) - 0.5) * texel;
        c += texture2D(tColor, uv); e += edgeAt(uv);
      }
      c /= 4.; e /= 4.;
      vec3 col = c.a > 0. ? c.rgb / c.a : vec3(0.);
      col = mix(vec3(dot(col, vec3(.299,.587,.114))), col, 1.1);             // a little punch
      // Render targets hold linear colour; the PNG wants sRGB.
      col = mix(col * 12.92, 1.055 * pow(col, vec3(1. / 2.4)) - 0.055, step(0.0031308, col));
      float a = max(c.a, e);
      gl_FragColor = vec4(mix(col, ink, e), a);
    }`,
  transparent: true, depthTest: false, depthWrite: false,
}));
const post = new THREE.Scene();
post.add(quad);
const postCam = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);

// ---- model ------------------------------------------------------------------
let vrm, bones = {}, base = {};

async function load() {
  const loader = new GLTFLoader();
  loader.register((p) => new VRMLoaderPlugin(p));
  const gltf = await loader.loadAsync('/app/models/model.vrm');
  vrm = gltf.userData.vrm;
  VRMUtils.rotateVRM0(vrm);
  VRMUtils.removeUnnecessaryVertices?.(vrm.scene);
  scene.add(vrm.scene);
  vrm.scene.traverse((o) => {
    if (!o.isMesh) return;
    o.frustumCulled = false;
    for (const m of [].concat(o.material)) {
      if (m.isMToonMaterial) {               // hard cel terminator, no glossy extras
        m.shadingToonyFactor = 1.0;
        m.shadingShiftFactor = -0.05;
        if ('rimLightingMixFactor' in m) m.rimLightingMixFactor = 0;
        if ('parametricRimColorFactor' in m) m.parametricRimColorFactor.set(0, 0, 0);
        if ('outlineWidthFactor' in m) m.outlineWidthFactor = 0;   // we draw our own ink
      }
    }
  });
  const h = vrm.humanoid;
  for (const name of new Set([...Object.keys(REST_POSE), 'head', 'neck', 'spine', 'chest',
                              'rightUpperArm', 'rightLowerArm', 'rightHand'])) {
    const n = h.getNormalizedBoneNode(name);
    if (!n) continue;
    const r = REST_POSE[name] || [n.rotation.x, n.rotation.y, n.rotation.z];
    bones[name] = n;
    base[name] = r;
  }
  frame();
}

function frame() {
  vrm.scene.updateWorldMatrix(true, true);
  const head = new THREE.Vector3();
  vrm.humanoid.getNormalizedBoneNode('head').getWorldPosition(head);
  const VIEW_H = 0.72;                       // head to waist, like the Capri cut-outs
  const dist = VIEW_H / (2 * Math.tan(THREE.MathUtils.degToRad(camera.fov / 2)));
  const aimY = head.y - 0.11;   // room above for the ahoge
  camera.position.set(head.x, aimY, head.z + dist);
  camera.lookAt(head.x, aimY, head.z);
  camera.near = dist - 1; camera.far = dist + 1;
  camera.updateProjectionMatrix();
  quad.material.uniforms.near.value = camera.near;
  quad.material.uniforms.far.value = camera.far;
}

function pose(boneOffsets = {}, expr = {}) {
  for (const [name, r] of Object.entries(base)) {
    const o = boneOffsets[name] || [0, 0, 0];
    bones[name].rotation.set(r[0] + o[0], r[1] + o[1], r[2] + o[2]);
  }
  const em = vrm.expressionManager;
  for (const e of em.expressions) em.setValue(e.expressionName, 0);
  for (const [k, v] of Object.entries(expr)) if (!k.startsWith('_')) em.setValue(k, v);
  // Let the hair springs settle into the pose.
  vrm.springBoneManager?.reset?.();
  for (let i = 0; i < 90; i++) vrm.update(1 / 60);
}

function render() {
  renderer.setRenderTarget(colorRT);
  renderer.clear();
  renderer.render(scene, camera);
  scene.overrideMaterial = normalMat;
  renderer.setRenderTarget(normalRT);
  renderer.setClearColor(0x808080, 1);
  renderer.clear();
  renderer.render(scene, camera);
  renderer.setClearColor(0x000000, 0);
  scene.overrideMaterial = null;
  renderer.setRenderTarget(null);
  renderer.clear();
  renderer.render(post, postCam);
}

async function emit(name, manifest, group) {
  render();
  const blob = await new Promise((r) => renderer.domElement.toBlob(r, 'image/png'));
  const url = URL.createObjectURL(blob);
  const fig = document.createElement('figure');
  fig.innerHTML = `<img src="${url}" alt="${name}"><figcaption>${name}</figcaption>`;
  document.getElementById('grid').append(fig);
  if (SAVE) await fetch(`/save/${name}.png`, { method: 'POST', body: blob });
  (manifest[group] ||= []).push(name);
}

async function bake() {
  const manifest = { size: [W, H], fps: 12, expressions: {}, poses: {} };
  const exprNames = Object.keys(EXPRESSIONS);
  let i = 0;
  const total = exprNames.length * Object.keys(VARIANTS).length + Object.keys(POSES).length;
  for (const ex of exprNames) {
    const { _head, ...mood } = EXPRESSIONS[ex];
    const headOff = _head ? { head: _head } : {};
    manifest.expressions[ex] = {};
    for (const [vn, v] of Object.entries(VARIANTS)) {
      pose(headOff, { ...mood, ...v });
      const name = `${ex}_${vn}`;
      status(`baking ${++i}/${total} · ${name}`);
      await emit(name, manifest.expressions[ex], vn);
    }
  }
  for (const [pn, p] of Object.entries(POSES)) {
    pose(p.bones, p.expr);
    status(`baking ${++i}/${total} · pose_${pn}`);
    await emit(`pose_${pn}`, manifest.poses, pn);
  }
  if (SAVE) await fetch('/save/manifest.json', { method: 'POST', body: JSON.stringify(manifest, null, 1) });
  status(`done · ${i} frames${SAVE ? ' saved to aiws/companion/frames/marina/' : ' (preview only; add ?save=1 to write them)'}`);
  window.__baked = i;
}

document.getElementById('out').replaceWith(renderer.domElement);
renderer.domElement.style.display = 'none';
load().then(bake).catch((e) => { status('error: ' + e.message); console.error(e); window.__bakeError = String(e); });
