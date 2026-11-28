// Motion-captured clips for what she does in *asterisks* (laughs, claps,
// waves, stretches…) and a little hand movement while she talks. The clips are
// Mixamo mocap, retargeted to VRM humanoid bones ahead of time by
// tools/mocap-build.mjs and packed into models/mocap.bin.
//
// Standing still is not a clip: stance.js poses her as a person stands, and
// this blends each clip in from that pose and back out to it. Her neck and
// head keep app.js's gaze on top, so she still looks at you mid-action.
// collide.js runs after both and keeps her arms out of her body.

// Which clips an action from classifyAction() plays; one is picked at random.
export const ACTION_CLIPS = {
  hugKnees: ['bashful'], hugSelf: ['rubShoulder'], hug: ['reach'],
  stretch: ['stretch', 'neckStretch'], cheer: ['excited', 'victory'],
  dance: ['dance', 'danceSilly'], clap: ['clap'], wave: ['wave'],
  facepalm: ['defeated'], coverEyes: ['bashful'], coverMouth: ['startle'],
  rubEyes: ['crying'], wipeTear: ['crying'], chin: ['think'], think: ['think'],
  crossArms: ['pout'], kiss: ['kiss'], thumbsUp: ['acknowledge'], salute: ['salute'],
  peace: ['happyGesture'], hair: ['bashful'], sip: ['drink'], point: ['armGesture'],
  reach: ['reach'], nudge: ['happyGesture'], fidget: ['nervous'], bow: ['bow'],
  yawn: ['yawn'], rubNeck: ['bashful'], wince: ['lookAway'],
  dismiss: ['dismiss', 'whatever'], leanBack: ['relief'],
  leanIn: ['handsForward', 'acknowledge'], shrug: ['shrug'],
  laugh: ['laugh'], sighBody: ['relief'], startle: ['startle'],
  nod: ['nod', 'nodThoughtful'], headShake: ['headShake', 'annoyed'],
  angry: ['angry'], sad: ['defeated'], lookAway: ['lookAway'], thankful: ['thankful'],
  agree: ['agree'], gesture: ['happyGesture', 'armGesture', 'acknowledge'],
};

const TALKS = ['talk2', 'talk3', 'talk4'];
// A little hand movement while she talks, not a performance. Talk clips add
// only their movement (each bone's turn away from the clip's own average
// pose) on top of how she stands: pulling her hanging arms part way towards
// the clip's bent, held-forward ones flared her elbows out and left her hands
// sticking out at hip height. Her legs and hips stay with stance.js, and
// her arms hang as stance.js has them (her body still sways as she talks).
const TALK_WEIGHT = 0.25, TALK_RATE = 0.75;
const TALK_SKIP = /^hips$|(UpperLeg|LowerLeg|Foot|Toes|Metacarpal|Proximal|Intermediate|Distal)$/;
// Hanging at her sides, the clips' wrist and shoulder movement swung her
// fingers into her thighs: those bones take less of it. Her fingers are
// stance.js's (whole-hand shapes on stressed words), not the clips'.
const TALK_BONE = { leftHand: 0.35, rightHand: 0.35, leftUpperArm: 0.7, rightUpperArm: 0.7 };
// So she isn't doing the same thing every time she talks: each stretch of a
// clip starts somewhere new in it, is mirrored half the time (the other hand
// leads), and is stronger or quieter; now and then she hardly gestures.
const TALK_MIN_LEFT = 2.6;     // s of clip left after a random start
const TALK_QUIET = 0.25, TALK_STRENGTH = [0.6, 1.15];
const mirrorName = (b) => (b.startsWith('left') ? 'right' + b.slice(4) : b.startsWith('right') ? 'left' + b.slice(5) : b);
// Neck and head: how much of a clip they take; app.js's gaze keeps the rest.
const HEAD_SHARE = { neck: 0.55, head: 0.45 };

const FADE_IN = 0.5, FADE_OUT = 1.0;
// A clip cut short (MAX_ACTION) is stopped mid-movement: let it go slower.
const CUT_FADE_OUT = 1.4;
// Idle clips under everything: partly blended over how she stands, eased in
// and out slowly, so they read as someone settling rather than performing.
const IDLE_WEIGHT = 0.7, IDLE_FADE_IN = 1.6, IDLE_FADE_OUT = 2.0, IDLE_MAX = 10;
const KIND_ORDER = { idle: 0, talk: 1, action: 2 };
// Weights ease (slow, faster, slow) instead of ramping in a straight line.
const ease = (x) => x * x * (3 - 2 * x);
// Clips that are one cycle of a loop, played round until they've run this long.
const REPEAT = { clap: 2.6, wave: 2.8 };
// How long an action may take. Most mocap runs on well past the moment (an
// angry clip is 19 s); a stretch or a yawn gets its whole length.
const MAX_ACTION = 4.5;
const LONG_ACTION = { stretch: 9, yawn: 8.3, dance: 7, danceSilly: 5.4, drink: 6, excited: 5.5, victory: 5.5, laugh: 5 };

export class Mocap {
  constructor(THREE) {
    this.T = THREE;
    this.clips = null;
    this.vrm = null;
    this.layers = [];     // { key, t, w, target, kind, age, length }
    this.hold = null;     // { key, t } for tests and screenshots
    this.talkWeight = TALK_WEIGHT;
    this._q = [new THREE.Quaternion(), new THREE.Quaternion(), new THREE.Quaternion()];
  }

  load(buffer) {
    const len = new DataView(buffer).getUint32(0, true);
    const index = JSON.parse(new TextDecoder().decode(new Uint8Array(buffer, 4, len)));
    this.data = new Int16Array(buffer, 4 + len);
    this.fps = index.fps;
    this.posScale = index.posScale;
    this.clips = index.clips;
    if (this.vrm) this.mount(this.vrm);
  }

  get ready() { return !!(this.clips && this.vrm); }
  has(name) { return !!(this.clips && ACTION_CLIPS[name]?.some((k) => this.clips[k])); }
  // An action clip is playing.
  get active() { return !!this.hold || this.layers.some((l) => l.kind === 'action' && !l.done); }
  // How much an action has her body right now, 0 to 1.
  get actionWeight() {
    if (this.hold) return 1;
    let w = 0;
    for (const l of this.layers) if (l.kind === 'action') w = Math.max(w, l.w);
    return w;
  }

  mount(vrm) {
    this.vrm = vrm;
    this.layers = [];
    if (!this.clips) return;
    const h = vrm.humanoid;
    const names = new Set();
    for (const c of Object.values(this.clips)) for (const n in c.bones) names.add(n);
    this.nodes = {};
    for (const n of names) {
      const node = h?.getNormalizedBoneNode(n);
      if (node) this.nodes[n] = node;
    }
    this.flip = vrm.meta?.metaVersion === '0';
    vrm.scene.updateWorldMatrix(true, true);
    const hips = this.nodes.hips;
    this.hipsRest = hips ? hips.position.clone() : null;
    this.hipsHeight = hips ? Math.abs(hips.getWorldPosition(new this.T.Vector3()).y - vrm.scene.getWorldPosition(new this.T.Vector3()).y) : 1;
    // Talk clips' average pose per bone, which their movement is measured from.
    this.mean = {};
    const q = new this.T.Quaternion(), sum = new this.T.Vector4();
    for (const k of TALKS) {
      const c = this.clips[k];
      if (!c) continue;
      this.mean[k] = {};
      for (const bone of Object.keys(c.bones)) {
        if (TALK_SKIP.test(bone) || !c.bones[bone].rot) continue;
        const n = c.bones[bone].rot[1];
        sum.set(0, 0, 0, 0);
        let first = null;
        for (let i = 0; i < n; i++) {
          this.rot(k, bone, i / this.fps, q);
          if (!first) first = q.clone();
          const s = q.dot(first) < 0 ? -1 : 1;
          sum.x += q.x * s; sum.y += q.y * s; sum.z += q.z * s; sum.w += q.w * s;
        }
        this.mean[k][bone] = new this.T.Quaternion(sum.x, sum.y, sum.z, sum.w).normalize();
      }
    }
    // Each clip's starting spot, so she stays where she stands.
    this.start = {};
    for (const [k, c] of Object.entries(this.clips)) {
      const p = c.bones.hips?.pos;
      this.start[k] = p ? [this.data[p[0]], this.data[p[0] + 1], this.data[p[0] + 2]] : [0, 0, 0];
    }
  }

  pick(list) {
    const ok = list.filter((k) => this.clips[k]);
    return ok[(Math.random() * ok.length) | 0];
  }

  play(name) {
    if (!this.ready) return false;
    const key = this.pick(ACTION_CLIPS[name] || [name]);
    if (!key) return false;
    for (const l of this.layers) if (l.kind === 'action' || l.kind === 'idle') l.target = 0;
    const d = this.clips[key].duration;
    const length = REPEAT[key] || Math.min(d, LONG_ACTION[key] || MAX_ACTION);
    const fadeOut = !REPEAT[key] && length < d - 0.3 ? CUT_FADE_OUT : FADE_OUT;
    this.add({ key, t: 0, age: 0, length, w: 0, target: 1, kind: 'action', fadeOut });
    return true;
  }

  // A quiet clip while nothing else is going on: played through, under any
  // action or talking, which fade it out.
  idle(key, weight = IDLE_WEIGHT) {
    if (!this.ready || !this.clips[key]) return false;
    if (this.layers.some((l) => l.kind === 'idle' && l.target > 0)) return false;
    const length = Math.min(this.clips[key].duration, IDLE_MAX);
    this.add({ key, t: 0, age: 0, length, w: 0, target: weight, kind: 'idle',
      fadeIn: IDLE_FADE_IN, fadeOut: IDLE_FADE_OUT });
    return true;
  }

  // A fresh stretch of talking movement, never quite the last one.
  addTalk(weight) {
    const key = this.pick(TALKS);
    if (!key) return;
    const d = this.clips[key].duration;
    const strength = Math.random() < TALK_QUIET ? 0.25 : TALK_STRENGTH[0] + Math.random() * (TALK_STRENGTH[1] - TALK_STRENGTH[0]);
    this.add({ key, t: Math.random() * Math.max(0, d - 1.2 - TALK_MIN_LEFT), w: 0, target: weight * strength,
      strength, kind: 'talk', mirror: Math.random() < 0.5 });
  }

  // Talking under actions; within a kind, newest on top.
  add(layer) {
    this.layers.push(layer);
    this.layers.sort((a, b) => KIND_ORDER[a.kind] - KIND_ORDER[b.kind]);
  }

  stop() { for (const l of this.layers) if (l.kind === 'action') l.target = 0; }

  update(dt, { speaking = false } = {}) {
    if (!this.ready) return;
    const acting = this.active;
    const talkTarget = speaking && !acting ? this.talkWeight : 0;
    const talk = this.layers.find((l) => l.kind === 'talk' && l.target > 0);
    if (talkTarget && !talk) this.addTalk(talkTarget);
    else if (talk) talk.target = talkTarget * talk.strength;

    let nextTalk = false;
    for (const l of this.layers) {
      const c = this.clips[l.key];
      if (l.kind === 'action' || l.kind === 'idle') {
        l.t += dt;
        l.age += dt;
        if (REPEAT[l.key] && l.t >= c.duration) l.t -= c.duration;
        if (l.age >= l.length - (l.fadeOut ?? FADE_OUT)) l.target = 0;
        if (l.kind === 'idle' && (speaking || acting)) l.target = 0;
      } else {
        l.t += dt * TALK_RATE;
        // Hand over to a fresh clip before this one runs out, never wrapping.
        if (l.target > 0 && l.t >= c.duration - 1.2) { l.target = 0; nextTalk = true; }
      }
      l.t = Math.min(l.t, c.duration);
      const fade = l.target > l.w ? (l.fadeIn ?? FADE_IN) : (l.fadeOut ?? FADE_OUT);
      const step = dt / fade;
      l.w = l.target > l.w ? Math.min(l.target, l.w + step) : Math.max(l.target, l.w - step);
      if (l.kind !== 'talk' && l.target === 0 && l.w <= 0.001) l.done = true;
    }
    if (nextTalk && talkTarget) this.addTalk(talkTarget);
    this.layers = this.layers.filter((l) => l.w > 0.001 || l.target > 0);
  }

  // One bone's rotation from one clip at time t.
  rot(key, bone, t, out) {
    const tr = this.clips[key].bones[bone]?.rot;
    if (!tr) return null;
    const [at, n] = tr;
    const d = this.data;
    if (n === 1) out.set(d[at], d[at + 1], d[at + 2], d[at + 3]).normalize();
    else {
      const f = Math.min(n - 1, t * this.fps);
      const i = Math.min(n - 2, f | 0), s = f - i;
      const a = at + i * 4, b = a + 4;
      out.set(d[a] + (d[b] - d[a]) * s, d[a + 1] + (d[b + 1] - d[a + 1]) * s,
        d[a + 2] + (d[b + 2] - d[a + 2]) * s, d[a + 3] + (d[b + 3] - d[a + 3]) * s).normalize();
    }
    if (this.flip) { out.x = -out.x; out.z = -out.z; }
    return out;
  }

  // The hips' movement from where the clip starts, in metres on her.
  hipsMove(key, t, out) {
    const tr = this.clips[key].bones.hips?.pos;
    if (!tr) return null;
    const [at, n] = tr;
    const d = this.data;
    const f = n === 1 ? 0 : Math.min(n - 1, t * this.fps);
    const i = n === 1 ? 0 : Math.min(n - 2, f | 0), s = n === 1 ? 0 : f - i;
    const a = at + i * 3, b = n === 1 ? a : a + 3;
    const st = this.start[key];
    const k = this.hipsHeight / this.posScale;
    for (let j = 0; j < 3; j++) out[j] = (d[a + j] + (d[b + j] - d[a + j]) * s - st[j]) * k;
    if (this.flip) { out[0] = -out[0]; out[2] = -out[2]; }
    return out;
  }

  // After stance.js has posed her: each clip pulls her pose towards its own
  // by its weight.
  apply() {
    if (!this.ready) return;
    const layers = this.hold ? [{ key: this.hold.key, t: this.hold.t, w: 1 }]
      : this.layers.filter((l) => l.w > 0.001).map((l) => {
        // Ease against the layer's own peak (talk and idle never reach 1).
        const peak = l.kind === 'action' ? 1 : Math.max(l.w, l.target, 0.001);
        return { key: l.key, t: l.t, w: ease(Math.min(1, l.w / peak)) * peak, talk: l.kind === 'talk', mirror: l.mirror };
      });
    if (!layers.length) return;
    const [q, tmp] = this._q;
    for (const [bone, node] of Object.entries(this.nodes)) {
      const share = HEAD_SHARE[bone];
      for (const l of layers) {
        const src = l.mirror ? mirrorName(bone) : bone;
        if (l.talk && !this.mean[l.key]?.[src]) continue;
        if (!this.rot(l.key, src, l.t, q)) continue;
        if (l.talk) {
          // The clip's movement away from its average, in the bone's own
          // frame (a twist of her arm stays a twist, not a swing out), added
          // to her pose.
          tmp.copy(this.mean[l.key][src]).invert().multiply(q);
          if (tmp.w < 0) { tmp.x = -tmp.x; tmp.y = -tmp.y; tmp.z = -tmp.z; tmp.w = -tmp.w; }
          // Mirrored left for right: the same turn reflected across her middle.
          if (l.mirror) { tmp.y = -tmp.y; tmp.z = -tmp.z; }
          tmp.copy(this._q[2].identity().slerp(tmp, l.w * (share ?? TALK_BONE[bone] ?? 1)));
          node.quaternion.multiply(tmp);
        } else if (share !== undefined) {
          // The clip's head movement on top of where she's looking.
          tmp.identity().slerp(q, share * l.w);
          node.quaternion.premultiply(tmp);
        } else {
          node.quaternion.slerp(q, l.w);
        }
      }
    }
    const hips = this.nodes.hips;
    if (hips && this.hipsRest) {
      const p = [0, 0, 0];
      for (const l of layers) {
        if (l.talk || !this.hipsMove(l.key, l.t, p)) continue;
        hips.position.x += (this.hipsRest.x + p[0] - hips.position.x) * l.w;
        hips.position.y += (this.hipsRest.y + p[1] - hips.position.y) * l.w;
        hips.position.z += (this.hipsRest.z + p[2] - hips.position.z) * l.w;
      }
    }
  }
}
