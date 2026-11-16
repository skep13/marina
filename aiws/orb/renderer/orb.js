// The sphere. One fragment shader draws a lit core with churning noise
// inside, a rim glow, a soft halo, and up to MAX_PULSES rings rippling
// outward. Everything visible is driven by a few numbers:
//
//   state   idle | listening | thinking | speaking | acting | approval | error
//   level   0..1 how "loud" she is right now (eases toward a target)
//   pulse() one ring outward: called per burst of streamed text or speech
//
// Colours come from settings and can be changed live with setColors().
// To stay cheap it redraws ~15 times a second when idle and only runs at the
// display rate while she's active; it stops entirely when the window is hidden.
const MAX_PULSES = 12;
const IDLE_FRAME_MS = 66;

const FRAG = `
precision highp float;
uniform vec2 res; uniform float t, level, swirl, breath;
uniform vec3 core, glow, ring, accent;
uniform vec4 pulses[${MAX_PULSES}];   // x: start time, y: strength, z: hue mix (0 ring, 1 accent)
varying vec2 vUv;

float hash(vec3 p){ p = fract(p * .3183099 + .1); p *= 17.; return fract(p.x * p.y * p.z * (p.x + p.y + p.z)); }
float noise(vec3 x){
  vec3 i = floor(x), f = fract(x); f = f * f * (3. - 2. * f);
  return mix(mix(mix(hash(i), hash(i + vec3(1,0,0)), f.x), mix(hash(i + vec3(0,1,0)), hash(i + vec3(1,1,0)), f.x), f.y),
             mix(mix(hash(i + vec3(0,0,1)), hash(i + vec3(1,0,1)), f.x), mix(hash(i + vec3(0,1,1)), hash(i + vec3(1,1,1)), f.x), f.y), f.z);
}
float fbm(vec3 p){ float a = .5, s = 0.; for (int i = 0; i < 5; i++){ s += a * noise(p); p *= 2.03; a *= .5; } return s; }

void main(){
  vec2 p = (vUv - .5) * 2.;
  p.x *= res.x / res.y;
  float r = length(p);
  float R = .44 * (1. + .025 * sin(t * 1.3) * breath + .07 * level);

  vec3 col = vec3(0.); float a = 0.;

  // halo
  float halo = exp(-max(r - R, 0.) * (7. - 3. * level)) * (.35 + .65 * level);
  col += glow * halo * .55; a = max(a, halo * .55);

  // pulse rings
  for (int i = 0; i < ${MAX_PULSES}; i++) {
    vec4 pu = pulses[i];
    float age = t - pu.x;
    if (pu.y <= 0. || age < 0. || age > 2.2) continue;
    float rr = R + age * .55;
    float w = .012 + age * .02;
    float ringv = exp(-pow((r - rr) / w, 2.)) * pu.y * exp(-age * 1.9);
    vec3 rc = mix(ring, accent, pu.z);
    col += rc * ringv; a = max(a, ringv);
  }

  // the sphere itself
  if (r < R) {
    float z = sqrt(R * R - r * r) / R;                 // 1 at centre, 0 at the edge
    vec3 n = normalize(vec3(p / R, z));
    vec3 q = vec3(n.xy * 1.6, t * (.15 + .5 * swirl));
    q.xy += vec2(fbm(q + 3.1), fbm(q + 7.7)) * (.6 + 1.4 * swirl);
    float inner = fbm(q * 1.4);
    float light = .45 + .55 * max(dot(n, normalize(vec3(-.4, .5, .8))), 0.);
    vec3 body = mix(core * .55, mix(core, accent, .55), smoothstep(.35, .8, inner));
    body *= light;
    body += accent * pow(inner, 3.) * (.6 + level);    // bright veins
    float rim = pow(1. - z, 2.4);
    body += glow * rim * (1.1 + level);
    float edge = smoothstep(R, R - .01, r);
    col = mix(col, body, edge); a = max(a, edge);
  }
  gl_FragColor = vec4(col, clamp(a, 0., 1.));
}`;

const STATES = {
  idle:      { level: .05, swirl: .15, breath: 1 },
  listening: { level: .25, swirl: .25, breath: .5 },
  thinking:  { level: .35, swirl: .9,  breath: .3 },
  speaking:  { level: .55, swirl: .45, breath: .2 },
  acting:    { level: .45, swirl: .7,  breath: .3 },
  approval:  { level: .4,  swirl: .3,  breath: 1 },
  error:     { level: .3,  swirl: .2,  breath: 0 },
};

export function hex(c) {
  const n = parseInt(c.replace('#', ''), 16);
  return [(n >> 16 & 255) / 255, (n >> 8 & 255) / 255, (n & 255) / 255];
}

export class Orb {
  constructor(canvas) {
    this.canvas = canvas;
    const gl = (this.gl = canvas.getContext('webgl', { premultipliedAlpha: false, alpha: true, antialias: true }));
    const sh = (type, src) => {
      const s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s);
      if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s));
      return s;
    };
    const prog = gl.createProgram();
    gl.attachShader(prog, sh(gl.VERTEX_SHADER,
      'attribute vec2 p; varying vec2 vUv; void main(){ vUv = p * .5 + .5; gl_Position = vec4(p, 0., 1.); }'));
    gl.attachShader(prog, sh(gl.FRAGMENT_SHADER, FRAG));
    gl.linkProgram(prog); gl.useProgram(prog);
    gl.bindBuffer(gl.ARRAY_BUFFER, gl.createBuffer());
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
    const loc = gl.getAttribLocation(prog, 'p');
    gl.enableVertexAttribArray(loc); gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
    gl.enable(gl.BLEND); gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
    this.u = Object.fromEntries(['res', 't', 'level', 'swirl', 'breath', 'core', 'glow', 'ring', 'accent', 'pulses']
      .map((n) => [n, gl.getUniformLocation(prog, n === 'pulses' ? 'pulses[0]' : n)]));

    this.colors = {};
    this.state = 'idle';
    this.cur = { ...STATES.idle, accent: [1, 1, 1] };
    this.pulses = new Float32Array(MAX_PULSES * 4);
    this.next = 0;
    this.t0 = performance.now();
    this.last = this.now();
    this.frame = this.frame.bind(this);
    document.addEventListener('visibilitychange', () => { if (!document.hidden) this.schedule(); });
    this.schedule();
  }

  setColors(c) { this.colors = c; }

  setState(s) {
    if (!STATES[s]) return;
    this.state = s;
    this.schedule(true);                                  // wake to full speed straight away
  }

  // One ring outward. strength 0..1; accent=true tints it with the state colour.
  pulse(strength = 1, accent = false) {
    const i = this.next++ % MAX_PULSES;
    this.pulses.set([this.now(), Math.min(1, strength), accent ? 1 : 0, 0], i * 4);
    this.kick = Math.min(1, (this.kick || 0) + .25 * strength);
    this.lastPulse = this.now();
    this.schedule(true);
  }

  now() { return (performance.now() - this.t0) / 1000; }

  // Idle and settled: a slow timer. Active, pulsing or still easing: every display frame.
  busy() {
    const settled = Math.abs(this.cur.level - STATES[this.state].level) < .01 && (this.kick || 0) < .01;
    const pulsing = this.now() - (this.lastPulse || -10) < 2;
    return this.state !== 'idle' || !settled || pulsing;
  }

  schedule(now = false) {
    if (document.hidden) return;
    if (now) { clearTimeout(this.timer); cancelAnimationFrame(this.raf); }
    else if (this.timer || this.raf) return;
    this.timer = this.raf = 0;
    if (this.busy() || now) this.raf = requestAnimationFrame(this.frame);
    else this.timer = setTimeout(this.frame, IDLE_FRAME_MS);
  }

  frame() {
    this.timer = this.raf = 0;
    if (document.hidden) return;
    const gl = this.gl, c = this.canvas;
    const dpr = window.devicePixelRatio || 1;
    const w = c.clientWidth * dpr | 0, h = c.clientHeight * dpr | 0;
    if (c.width !== w || c.height !== h) { c.width = w; c.height = h; }
    const t = this.now();
    const dt = Math.min(.1, t - this.last); this.last = t;
    const goal = STATES[this.state];
    const accentGoal = hex(this.colors[this.state] || '#ffffff');
    const k = 1 - Math.pow(.92, dt * 60);                // same easing at any frame rate
    this.kick = (this.kick || 0) * Math.pow(.9, dt * 60);
    for (const key of ['level', 'swirl', 'breath']) this.cur[key] += ((goal[key] + (key === 'level' ? this.kick : 0)) - this.cur[key]) * k;
    this.cur.accent = this.cur.accent.map((v, i) => v + (accentGoal[i] - v) * k);
    // approval: a slow attention blink; error: a flicker
    let level = this.cur.level;
    if (this.state === 'approval') level += .2 * (0.5 + 0.5 * Math.sin(t * 4));
    if (this.state === 'error') level += .15 * (Math.random() < .1 ? 1 : 0);

    gl.viewport(0, 0, w, h); gl.clearColor(0, 0, 0, 0); gl.clear(gl.COLOR_BUFFER_BIT);
    gl.uniform2f(this.u.res, w, h);
    gl.uniform1f(this.u.t, t);
    gl.uniform1f(this.u.level, Math.min(1, level));
    gl.uniform1f(this.u.swirl, this.cur.swirl);
    gl.uniform1f(this.u.breath, this.cur.breath);
    gl.uniform3fv(this.u.core, hex(this.colors.core || '#2a6cff'));
    gl.uniform3fv(this.u.glow, hex(this.colors.glow || '#7fd8ff'));
    gl.uniform3fv(this.u.ring, hex(this.colors.pulse || '#bfefff'));
    gl.uniform3fv(this.u.accent, this.cur.accent);
    gl.uniform4fv(this.u.pulses, this.pulses);
    gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
    this.schedule();
  }
}
