// Fills in the mockup: skyline, 7-segment readouts, code, and Marina
// (her baked cel frames, held on twos, with the glitch shader).
const $ = (id) => document.getElementById(id);

// ---- fit the 1920x1080 stage to the window ----
function fit() {
  const s = Math.min(innerWidth / 1920, innerHeight / 1080);
  document.getElementById('screen').style.setProperty('--fit', s);
}
addEventListener('resize', fit); fit();

// ---- skyline (seeded, so it's the same every load) ----
let seed = 7;
const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
const sky = $('skyline'), lights = $('lights');
for (let x = 0; x < 1920;) {
  const w = 30 + rnd() * 70, h = 60 + Math.pow(rnd(), 2) * 260;
  const y = 740 - h;
  sky.insertAdjacentHTML('beforeend', `<rect x="${x}" y="${y}" width="${w}" height="${h + 340}"/>`);
  for (let i = 0; i < h / 9; i++) if (rnd() < 0.22) {
    const lx = x + 4 + rnd() * (w - 8), ly = y + 6 + rnd() * (h - 10);
    const c = rnd() < 0.8 ? '#f2a541' : '#3de1ff';
    lights.insertAdjacentHTML('beforeend', `<rect x="${lx}" y="${ly}" width="2" height="3" fill="${c}" opacity="${0.35 + rnd() * 0.5}"/>`);
  }
  x += w + rnd() * 6;
}
const grid = $('grid');
for (let i = -24; i <= 24; i++) grid.insertAdjacentHTML('beforeend', `<line x1="${960 + i * 18}" y1="740" x2="${960 + i * 160}" y2="1080"/>`);
for (let i = 0; i < 9; i++) { const y = 742 + Math.pow(i / 8, 1.8) * 338; grid.insertAdjacentHTML('beforeend', `<line x1="0" y1="${y}" x2="1920" y2="${y}"/>`); }

// ---- workspaces ----
$('ws').innerHTML = [1, 2, 3, 4, 5, 6].map((n) => `<i class="${n === 2 ? 'on' : n < 4 ? 'has' : ''}">${n}</i>`).join('');

// ---- 7-segment digits ----
const SEGS = { 0: 'abcdef', 1: 'bc', 2: 'abged', 3: 'abgcd', 4: 'fgbc', 5: 'afgcd', 6: 'afgedc', 7: 'abc', 8: 'abcdefg', 9: 'abcdfg' };
const SHAPE = { a: 'M2 0h8l-2 2H4z', b: 'M10 1l2 2v7l-2 1-1-1V3z', c: 'M10 11l2 1v7l-2 2-1-2v-6z',
  d: 'M2 22h8l-2-2H4z', e: 'M1 12l2-1 1 1v6l-1 2-2-2z', f: 'M1 3l2-2 1 2v7l-1 1-2-1z', g: 'M2 11l2-1h4l2 1-2 1H4z' };
function digit(ch) {
  if (ch === ':') return '<svg viewBox="0 0 5 22"><rect class="on" x="1" y="6" width="2.4" height="2.4"/><rect class="on" x="1" y="14" width="2.4" height="2.4"/></svg>';
  if (ch === '.') return '<svg viewBox="0 0 4 22"><rect class="on" x=".8" y="19" width="2.4" height="2.4"/></svg>';
  const on = SEGS[ch] || '';
  return '<svg viewBox="0 0 13 22">' + Object.entries(SHAPE).map(([k, d]) =>
    `<path class="${on.includes(k) ? 'on' : 'off'}" d="${d}"/>`).join('') + '</svg>';
}
for (const el of document.querySelectorAll('.seg')) el.innerHTML = [...el.dataset.v].map(digit).join('');

// ---- code window ----
const CODE = [
  ['cm', '# mergesort.py'],
  ['', '<span class="kw">def</span> <span class="fn">merge</span>(a, b):'],
  ['', '    out = []'],
  ['', '    i = j = <span class="nu">0</span>'],
  ['', '    <span class="kw">while</span> i &lt; <span class="fn">len</span>(a) <span class="kw">and</span> j &lt; <span class="fn">len</span>(b):'],
  ['', '        <span class="kw">if</span> a[i] &lt; b[j]:'],
  ['', '            out.append(a[i]); i += <span class="nu">1</span>'],
  ['', '        <span class="kw">else</span>:'],
  ['', '            out.append(b[j]); j += <span class="nu">1</span>'],
  ['hl', '    out.extend(a[i:])   <span class="cm"># ← marina: the tail was being dropped</span>'],
  ['hl', '    out.extend(b[j:])'],
  ['', '    <span class="kw">return</span> out'],
  ['', ''],
  ['', ''],
  ['', '<span class="kw">def</span> <span class="fn">sort</span>(xs):'],
  ['', '    <span class="kw">if</span> <span class="fn">len</span>(xs) &lt;= <span class="nu">1</span>:'],
  ['', '        <span class="kw">return</span> <span class="fn">list</span>(xs)'],
  ['', '    mid = <span class="fn">len</span>(xs) // <span class="nu">2</span>'],
  ['', '    <span class="kw">return</span> merge(sort(xs[:mid]), sort(xs[mid:]))'],
];
$('code').innerHTML = CODE.map(([cls, html], i) => {
  const line = `<span class="ln">${i + 1}</span>${cls === 'cm' ? `<span class="cm">${html}</span>` : html}`;
  return cls === 'hl' ? `<span class="hl">${line}</span>` : line;
}).join('\n');

// ---- marina's corner: caption + action log ----
$('say').textContent = "ok that's cursed. the loop stops early and you never add what's left. fixed it — running your tests now.";
$('log').innerHTML = [
  ['read_file mergesort.py', 'ok', '✓'],
  ['edit_file mergesort.py  +2 lines', 'ok', '✓'],
  ['terminal_run make test', 'run', 'waiting for you'],
].map(([t, c, s]) => `<li>${t} <span class="${c}">${s}</span></li>`).join('');

// ---- Marina herself: baked cel frames + glitch shader ----
const FR = '/aiws/companion/frames/marina/';
const cv = $('marina');
const gl = cv.getContext('webgl', { premultipliedAlpha: false, alpha: true, preserveDrawingBuffer: true });
const prog = gl.createProgram();
for (const [t, src] of [[gl.VERTEX_SHADER,
  'attribute vec2 p; varying vec2 uv; void main(){ uv = vec2(p.x*.5+.5, .5-p.y*.5); gl_Position = vec4(p,0.,1.); }'],
  [gl.FRAGMENT_SHADER, `precision mediump float; uniform sampler2D tex; uniform float g, s, seed, bob; varying vec2 uv;
    float h(float n){ return fract(sin(n*91.7+seed*13.1)*43758.5); }
    void main(){ vec2 u = uv; u.y += bob; float band = floor(u.y*44.);
      if (g > 0. && h(band) > 1.-g*.5) u.x += (h(band+7.)-.5)*g*.16;
      float sp = s + g*.01;
      vec4 c = texture2D(tex, u); vec4 r = texture2D(tex, u+vec2(sp,0.)); vec4 b = texture2D(tex, u-vec2(sp,0.));
      float a = max(c.a, max(r.a, b.a)*step(.0005, sp));
      vec3 col = vec3(r.r, c.g, b.b);
      if (g > .4 && h(band+3.) > .86) col = mix(col, vec3(.24,.88,1.), .55);
      if (u.y < 0. || u.y > 1.) a = 0.;
      gl_FragColor = vec4(col, a); }`]]) {
  const sh = gl.createShader(t); gl.shaderSource(sh, src); gl.compileShader(sh); gl.attachShader(prog, sh);
}
gl.linkProgram(prog); gl.useProgram(prog);
gl.bindBuffer(gl.ARRAY_BUFFER, gl.createBuffer());
gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
const L = gl.getAttribLocation(prog, 'p'); gl.enableVertexAttribArray(L); gl.vertexAttribPointer(L, 2, gl.FLOAT, false, 0, 0);
gl.enable(gl.BLEND); gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
const U = Object.fromEntries(['g', 's', 'seed', 'bob'].map((n) => [n, gl.getUniformLocation(prog, n)]));

const tex = {};
const NAMES = ['smug_rest', 'smug_talk_a', 'smug_talk_o', 'smug_blink'];
await Promise.all(NAMES.map((n) => new Promise((ok) => {
  const im = new Image();
  im.onload = () => {
    const t = gl.createTexture(); gl.bindTexture(gl.TEXTURE_2D, t);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, im);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    tex[n] = t; ok();
  };
  im.onerror = ok; im.src = FR + n + '.png';
})));

// Still mode (?still) draws one fixed frame with a light glitch, for screenshots.
const still = new URLSearchParams(location.search).has('still');
const st = { tick: 0, frame: 'smug_talk_a', blink: 0, g: still ? 0.18 : 0, gt: 0, s: still ? 0.0035 : 0, seed: 4.2, bob: 0 };
function draw() {
  gl.viewport(0, 0, cv.width, cv.height); gl.clearColor(0, 0, 0, 0); gl.clear(gl.COLOR_BUFFER_BIT);
  gl.bindTexture(gl.TEXTURE_2D, tex[st.blink > 0 ? 'smug_blink' : st.frame] || tex.smug_rest);
  gl.uniform1f(U.g, st.g); gl.uniform1f(U.s, st.s); gl.uniform1f(U.seed, st.seed); gl.uniform1f(U.bob, st.bob);
  gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
}
if (still) {
  draw();
} else {
  setInterval(() => {
    st.tick++;
    if (st.blink > 0) st.blink--; else if (Math.random() < 0.025) st.blink = 2;
    if (st.tick % 2 === 0) {                             // on twos
      st.frame = ['smug_rest', 'smug_talk_a', 'smug_talk_o', 'smug_talk_a'][Math.random() * 4 | 0];
      st.bob = [0, 0.003, 0.006, 0.003][(st.tick / 6 | 0) % 4];
    }
    if (st.gt > 0) { st.gt--; st.seed = Math.random() * 99; if (!st.gt) { st.g = 0; st.s = 0; } }
    else if (Math.random() < 0.01) { st.g = 0.6; st.s = 0.004; st.gt = 3; }
    draw();
  }, 1000 / 12);
}
window.__mockReady = true;
