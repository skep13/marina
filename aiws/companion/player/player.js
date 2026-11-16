// Plays Marina's baked cel frames the way the Capri companions do: held
// frames on twos (12 fps ticks, changes every other tick), cut-out style
// bobbing, blinks, mouth flaps while text types out with a blip per
// syllable, and glitch / RGB-split / scanline effects in one shader.
const FRAMES = '/aiws/companion/frames/marina/';
const TICK = 1000 / 12;

const canvas = document.getElementById('marina');
const gl = canvas.getContext('webgl', { premultipliedAlpha: false, alpha: true });

// ---- shader -----------------------------------------------------------------
const vs = `attribute vec2 p; varying vec2 uv;
  void main(){ uv = vec2(p.x * .5 + .5, .5 - p.y * .5); gl_Position = vec4(p, 0., 1.); }`;
const fs = `precision mediump float;
  uniform sampler2D tex; uniform float t, glitch, split, seed, bob, fade; varying vec2 uv;
  float h(float n){ return fract(sin(n * 91.7 + seed * 13.1) * 43758.5); }
  void main(){
    vec2 u = uv; u.y += bob;
    float band = floor(u.y * 38.);
    if (glitch > 0. && h(band) > 1. - glitch * .6) u.x += (h(band + 7.) - .5) * glitch * .22;
    float s = split + glitch * .012;
    vec4 c = texture2D(tex, u);
    float r = texture2D(tex, u + vec2(s, 0.)).r, b = texture2D(tex, u - vec2(s, 0.)).b;
    float a = max(c.a, max(texture2D(tex, u + vec2(s, 0.)).a, texture2D(tex, u - vec2(s, 0.)).a) * step(.001, s));
    vec3 col = vec3(r, c.g, b);
    col *= .93 + .07 * step(1., mod(gl_FragCoord.y, 3.));                      // scanlines
    if (glitch > .5 && h(band + 3.) > .85) col = mix(col, vec3(.24, .88, 1.), .6); // cyan tears
    if (u.y < 0. || u.y > 1. || u.x < 0. || u.x > 1.) a = 0.;
    gl_FragColor = vec4(col, a * fade);
  }`;
const prog = gl.createProgram();
for (const [type, src] of [[gl.VERTEX_SHADER, vs], [gl.FRAGMENT_SHADER, fs]]) {
  const sh = gl.createShader(type);
  gl.shaderSource(sh, src); gl.compileShader(sh);
  if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(sh));
  gl.attachShader(prog, sh);
}
gl.linkProgram(prog); gl.useProgram(prog);
gl.bindBuffer(gl.ARRAY_BUFFER, gl.createBuffer());
gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
const loc = gl.getAttribLocation(prog, 'p');
gl.enableVertexAttribArray(loc); gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
gl.enable(gl.BLEND); gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
const U = Object.fromEntries(['t', 'glitch', 'split', 'seed', 'bob', 'fade'].map((n) => [n, gl.getUniformLocation(prog, n)]));

// ---- frames -----------------------------------------------------------------
const textures = {};
async function loadFrames() {
  const m = await (await fetch(FRAMES + 'manifest.json', { cache: 'no-store' })).json();
  const names = [...Object.values(m.expressions).flatMap((e) => Object.values(e).flat()),
                 ...Object.values(m.poses).flat()];
  await Promise.all(names.map((n) => new Promise((ok, bad) => {
    const img = new Image();
    img.onload = () => {
      const tx = gl.createTexture();
      gl.bindTexture(gl.TEXTURE_2D, tx);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, img);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
      textures[n] = tx; ok();
    };
    img.onerror = bad;
    img.src = FRAMES + n + '.png';
  })));
  return m;
}

// ---- state ------------------------------------------------------------------
const st = {
  mood: 'neutral', pose: null, talking: false, blinkTicks: 0, nextBlink: 30,
  mouth: 'rest', bob: 0, glitch: 0, glitchTicks: 0, split: 0, fade: 1, seed: 0, tick: 0,
};

function frameName() {
  if (st.pose) return `pose_${st.pose}`;
  if (st.blinkTicks > 0) return `${st.mood}_blink`;
  return `${st.mood}_${st.mouth}`;
}

// One tick = 1/12 s. Drawing changes only on even ticks: animation on twos.
function tick() {
  st.tick++;
  if (st.blinkTicks > 0) st.blinkTicks--;
  else if (--st.nextBlink <= 0) { st.blinkTicks = 2; st.nextBlink = 24 + Math.random() * 50 | 0; }
  if (st.tick % 2 === 0) {
    st.mouth = st.talking ? ['rest', 'talk_a', 'talk_o', 'talk_a'][Math.random() * 4 | 0] : 'rest';
    // Cut-out breathing: three held positions, not a smooth sine.
    st.bob = [0, 0.004, 0.008, 0.004][(st.tick / 6 | 0) % 4];
  }
  if (st.glitchTicks > 0) {
    st.glitchTicks--; st.seed = Math.random() * 100;
    if (st.glitchTicks === 0) { st.glitch = 0; st.split = 0; }
  } else if (Math.random() < 0.004) glitch(0.35, 3);                       // stray flicker
  draw();
}

function draw() {
  const tx = textures[frameName()] || textures['neutral_rest'];
  gl.viewport(0, 0, canvas.width, canvas.height);
  gl.clearColor(0, 0, 0, 0); gl.clear(gl.COLOR_BUFFER_BIT);
  gl.bindTexture(gl.TEXTURE_2D, tx);
  gl.uniform1f(U.t, st.tick / 12); gl.uniform1f(U.glitch, st.glitch); gl.uniform1f(U.split, st.split);
  gl.uniform1f(U.seed, st.seed); gl.uniform1f(U.bob, st.bob); gl.uniform1f(U.fade, st.fade);
  gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
}

function glitch(amount = 1, ticks = 6) {
  st.glitch = amount; st.split = 0.006 * amount; st.glitchTicks = ticks; st.seed = Math.random() * 100;
}

// Glitch apart, vanish, reappear elsewhere and resolve.
async function teleport() {
  const wait = (n) => new Promise((r) => setTimeout(r, n * TICK));
  glitch(1, 6); await wait(4);
  st.fade = 0.4; await wait(1); st.fade = 0; await wait(2);
  canvas.style.left = (8 + Math.random() * 60) + '%';
  st.fade = 0.5; glitch(1, 5); await wait(1); st.fade = 1; await wait(4);
}

// ---- talking: typewriter + blip per syllable ------------------------------------
let audio;
function blip(pitch) {
  audio ||= new AudioContext();
  const o = audio.createOscillator(), g = audio.createGain();
  o.type = 'square'; o.frequency.value = pitch;
  g.gain.setValueAtTime(0.04, audio.currentTime);
  g.gain.exponentialRampToValueAtTime(0.0001, audio.currentTime + 0.05);
  o.connect(g).connect(audio.destination); o.start(); o.stop(audio.currentTime + 0.06);
}

async function say(text, mood) {
  const bubble = document.getElementById('bubble'), out = document.getElementById('btext');
  if (mood) st.mood = mood;
  st.pose = null; st.talking = true;
  const r = canvas.getBoundingClientRect();
  bubble.style.display = 'block';
  bubble.style.left = Math.max(8, r.left - 220) + 'px';
  bubble.style.top = (r.top + r.height * 0.12) + 'px';
  out.textContent = '';
  for (let i = 0; i < text.length; i++) {
    out.textContent += text[i];
    if (/[aeiouy]/i.test(text[i]) && !/[aeiouy]/i.test(text[i - 1] || '')) blip(520 + Math.random() * 120);
    await new Promise((r) => setTimeout(r, /[.,!?]/.test(text[i]) ? 160 : 28));
  }
  st.talking = false;
  setTimeout(() => { if (!st.talking) bubble.style.display = 'none'; }, 3500);
}

// ---- controls ----------------------------------------------------------------
function buttons(host, names, onClick) {
  for (const n of names) {
    const b = document.createElement('button');
    b.textContent = n; b.onclick = () => onClick(n);
    document.getElementById(host).append(b);
  }
}

loadFrames().then((m) => {
  buttons('moods', Object.keys(m.expressions), (n) => { st.mood = n; st.pose = null; glitch(0.4, 2); });
  buttons('poses', ['none', ...Object.keys(m.poses)], (n) => { st.pose = n === 'none' ? null : n; glitch(0.4, 2); });
  document.getElementById('glitch').onclick = () => glitch(1, 8);
  document.getElementById('teleport').onclick = teleport;
  document.getElementById('talk').onclick = () => say(document.getElementById('say').value);
  setInterval(tick, TICK);
  window.__player = { st, say, glitch, teleport, ready: true };
}).catch((e) => { document.body.insertAdjacentHTML('beforeend', `<pre style="color:#f66">${e}</pre>`); });
