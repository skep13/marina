// How she stands. Not a clip: a person standing about keeps still most of the
// time, then shifts her weight onto one leg, turns at the waist to look at
// something, re-places a foot, and settles again. This does that by hand:
//
//   weight  -1..1, + on her left leg. The hips slide over that foot, the
//           standing hip rises and the free one drops, the spine leans back
//           the other way so her head stays over her feet.
//   feet    stay planted where they are (inverse kinematics from the hips),
//           and move only when the weight is off them: lift, re-place, set
//           down, usually turned out a little.
//   turn    when she looks well off to one side her waist turns with it.
//   arms    hang from her shoulders under their own weight, elbows soft and
//           pointing back, palms towards her thighs, fingers loosely curled.
//           They lag behind her body a touch, so a shift swings them slightly.
//
// app.js poses her torso, head and shoulders first (breathing, gaze); this
// runs after that, mocap.js blends actions in over it, and collide.js keeps
// her arms out of her body last of all.
import { setWorldQuat, aimBone, solveArm } from './actions.js';

const SHIFT = 0.055;      // m the hips slide over the standing leg at full weight
const DROP = 0.012;       // m the hips sink at full weight (the free knee bends)
const SOFT = 0.006;       // m of give in both knees, so they never lock
const HIP_TILT = 0.065;   // rad the standing hip rises
const SPINE_BACK = [0.035, 0.022, 0.012]; // spine, chest, upper chest lean back over
const TURN_SHARE = { hips: 0.25, spine: 0.3, chest: 0.25, upperChest: 0.2 };
const LIFT = 0.03;        // m a foot clears the floor when she re-places it
// Where a re-placed foot may go, relative to where it started: out, forward, toe-out.
const FOOT_OUT = [0, 0.06], FOOT_FWD = [-0.03, 0.08], FOOT_YAW = [0, 0.42];
const ARM_REACH = 0.93;   // hand this far down the arm's length: elbows soft
// A relaxed hand: each finger curls a little more than the one before it,
// index to little finger, and they fan apart slightly. Radians per joint,
// base to tip.
const CURL = [[0.28, 0.38, 0.22], [0.38, 0.48, 0.28], [0.46, 0.54, 0.32], [0.56, 0.6, 0.36]];
const SPREAD = [-0.07, 0, 0.06, 0.13];  // about the palm, + away from the thumb
// The thumb lies along the side of the index finger, a little in front of it:
// directions as (along the fingers, out to the thumb's side, into the palm).
const THUMB_AIM = [[0.72, 0.5, 0.22], [0.86, 0.22, 0.42]];
const THUMB_TIP = 0.28;                 // the last thumb joint's bend

const HIP_YAW = 0.05;     // rad the pelvis turns, free hip forward
const FREE_HEEL = 0.13;   // rad the free foot's heel comes up, toes down
const SWAY = 0.07;        // the never-quite-still drift of her weight
// Hand shapes, as how much each finger (index to little) curls against her
// relaxed hand, and how far they fan. Her fingers don't wander one by one:
// the whole hand takes a shape on purpose (opening as she makes a point,
// loosening with the index leading, gathering as she settles), holds it, and
// goes back to relaxed. Each finger glides there without overshoot, the
// index a moment before the little finger.
const SHAPES = {
  relaxed: { curl: [1, 1, 1, 1], fan: 0 },
  open: { curl: [0.42, 0.48, 0.56, 0.64], fan: 1 },
  half: { curl: [0.68, 0.76, 0.84, 0.92], fan: 0.5 },
  loose: { curl: [0.55, 0.84, 0.98, 1.04], fan: 0.25 },
  gathered: { curl: [1.18, 1.22, 1.22, 1.18], fan: -0.4 },
};
const TALK_SHAPES = ['open', 'half', 'half', 'loose', 'loose', 'relaxed'];
const FINGER_SPEED = [13, 12, 11, 10];  // rad/s: index gets there first
const smoother = (x) => x * x * x * (x * (x * 6 - 15) + 10);
// Smooth wandering in -1..1 (a few incommensurate sines).
const wander = (t, seed) => (Math.sin(t * 1.0 + seed) * 0.5 + Math.sin(t * 2.31 + seed * 1.7) * 0.3
  + Math.sin(t * 4.07 + seed * 2.9) * 0.2);
// One step of a critically damped spring: speeds up, slows, never overshoots.
function spring(x, v, target, omega, dt) {
  const a = omega * omega * (target - x) - 2 * omega * v;
  v += a * dt;
  return [x + v * dt, v];
}
const rand = (a, b) => a + Math.random() * (b - a);

export class Stance {
  constructor(THREE) {
    this.T = THREE;
    this._q = Array.from({ length: 6 }, () => new THREE.Quaternion());
    this.vrm = null;
    this.enabled = true;
    this.reset();
  }

  reset() {
    this.w = 0; this.wv = 0;    // weight, + on her left leg, and how fast it's moving
    this.wT = 0; this.wOmega = 4;
    this.up_w = 0; this.up_wv = 0; // her upper body follows the hips a beat later
    this.turn = 0; this.turnTarget = 0; this.turnV = 0;
    this.clock = Math.random() * 100;
    const foot = () => ({ x: 0, z: 0, yaw: 0, lift: 0, pitch: 0 });
    this.feet = { 1: foot(), [-1]: foot() };
    this.queue = [];            // foot moves waiting for the weight to come off
    this.task = null;
    this.restless = rand(8, 16);  // seconds until she shifts by herself
    this.hands = {};
    const hand = () => ({ shape: 'relaxed', hold: 0, curl: [1, 1, 1, 1], curlV: [0, 0, 0, 0], fan: 0, fanV: 0 });
    this.shape = { 1: hand(), [-1]: hand() };
    this.settle = rand(8, 20);  // seconds until an idle hand re-settles
  }

  mount(vrm) {
    const T = this.T;
    this.vrm = vrm;
    this.reset();
    const h = vrm.humanoid;
    if (!h) { this.vrm = null; return; }
    const b = (n) => h.getNormalizedBoneNode(n);
    this.b = {};
    for (const n of ['hips', 'spine', 'chest', 'upperChest',
      'leftUpperLeg', 'leftLowerLeg', 'leftFoot', 'rightUpperLeg', 'rightLowerLeg', 'rightFoot',
      'leftUpperArm', 'leftLowerArm', 'leftHand', 'rightUpperArm', 'rightLowerArm', 'rightHand']) this.b[n] = b(n);
    if (!this.b.hips || !this.b.leftFoot || !this.b.rightFoot) { this.vrm = null; return; }

    // Measure her in her bind pose, then put back whatever app.js had set.
    const saved = new Map();
    vrm.scene.traverse((o) => { if (o.isBone || o.type === 'Object3D') saved.set(o, o.quaternion.clone()); });
    const savedHips = this.b.hips.position.clone();
    h.resetNormalizedPose();
    vrm.scene.updateWorldMatrix(true, true);

    const scene = vrm.scene;
    const local = (node) => scene.worldToLocal(node.getWorldPosition(new T.Vector3()));
    const sceneQ = scene.getWorldQuaternion(new T.Quaternion());
    const sceneQi = sceneQ.clone().invert();

    // Her own directions in the scene's frame (VRM 0 and 1 face opposite ways).
    this.up = new T.Vector3(0, 1, 0);
    this.left = local(this.b.leftUpperLeg).sub(local(this.b.rightUpperLeg)).setY(0).normalize();
    this.fwd = new T.Vector3().crossVectors(this.left, this.up).normalize();
    this.hipsRest = this.b.hips.position.clone();
    this.hipsY = local(this.b.hips).y;
    // Sizes are tuned on a 1.5 m model; scale for others.
    this.k = Math.max(0.6, Math.min(1.6, this.hipsY / 0.8));

    this.footRest = {}; this.footQ = {};
    for (const [s, n] of [[1, 'leftFoot'], [-1, 'rightFoot']]) {
      this.footRest[s] = local(this.b[n]);
      this.footQ[s] = sceneQi.clone().multiply(this.b[n].getWorldQuaternion(new T.Quaternion()));
      const toes = b(n.replace('Foot', 'Toes'));
      this.footLen = toes ? local(toes).distanceTo(this.footRest[s]) : 0.1;
    }

    // Each hand's bind-pose frame (fingers, palm) so it can be turned to face
    // her thigh whichever way the model's bones are set up.
    for (const [s, side] of [[1, 'left'], [-1, 'right']]) {
      const hand = this.b[`${side}Hand`];
      const mid = b(`${side}MiddleProximal`);
      if (!hand || !mid) continue;
      const fing = local(mid).sub(local(hand)).normalize();
      const palm = this.up.clone().negate();
      palm.addScaledVector(fing, -palm.dot(fing)).normalize();
      const rest = new T.Matrix4().makeBasis(fing, palm, new T.Vector3().crossVectors(fing, palm));
      const handQ = sceneQi.clone().multiply(hand.getWorldQuaternion(new T.Quaternion()));
      // Fingers curl about fing x palm (towards the palm), in each bone's own frame.
      const axisScene = new T.Vector3().crossVectors(fing, palm).normalize();
      const fingers = [];
      ['Index', 'Middle', 'Ring', 'Little'].forEach((f, n) => {
        ['Proximal', 'Intermediate', 'Distal'].forEach((j, i) => {
          const node = b(`${side}${f}${j}`);
          if (node) fingers.push({ node, n, i, axis: this.boneAxis(node, axisScene, sceneQ),
            spread: this.boneAxis(node, palm, sceneQ) });
        });
      });
      const thumb = ['Metacarpal', 'Proximal', 'Distal'].map((j) => b(`${side}Thumb${j}`));
      const thumbTipAxis = thumb[2] ? this.boneAxis(thumb[2], axisScene, sceneQ) : null;
      const l1 = local(this.b[`${side}UpperArm`]).distanceTo(local(this.b[`${side}LowerArm`]));
      const l2 = local(this.b[`${side}LowerArm`]).distanceTo(local(hand));
      this.hands[s] = { side, rest: rest.invert(), handQ, fingers, thumb, thumbTipAxis, len: l1 + l2,
        target: null, vel: new T.Vector3() };
    }

    // What she rests on when this is switched off: her own bind pose for
    // everything app.js doesn't pose itself (legs, feet, fingers).
    this.neutral = [];
    for (const n of ['leftUpperLeg', 'leftLowerLeg', 'leftFoot', 'leftToes', 'rightUpperLeg', 'rightLowerLeg', 'rightFoot', 'rightToes']) {
      const node = b(n); if (node) this.neutral.push(node);
    }
    for (const side of ['left', 'right']) for (const f of ['Thumb', 'Index', 'Middle', 'Ring', 'Little']) {
      for (const j of f === 'Thumb' ? ['Metacarpal', 'Proximal', 'Distal'] : ['Proximal', 'Intermediate', 'Distal']) {
        const node = b(`${side}${f}${j}`); if (node) this.neutral.push(node);
      }
    }

    for (const [o, q] of saved) o.quaternion.copy(q);
    this.b.hips.position.copy(savedHips);
    vrm.scene.updateWorldMatrix(true, true);
  }

  // A scene-frame direction in a bone's own rest frame (bind pose).
  boneAxis(node, dirScene, sceneQ) {
    const q = node.getWorldQuaternion(new this.T.Quaternion()).invert().multiply(sceneQ);
    return dirScene.clone().applyQuaternion(q).normalize();
  }

  get ready() { return !!this.vrm; }
  // Visibly moving (a shift, a step, a turn): the app draws at full rate then.
  get moving() {
    if (!this.enabled) return false;
    return !!this.task || Math.abs(this.wv) > 0.03 || Math.abs(this.wT - this.w) > 0.05 || Math.abs(this.turnV) > 0.01;
  }

  // --- what she decides to do -------------------------------------------

  // Move her weight (+1 all on her left leg), taking about `dur` seconds.
  shiftTo(w, dur = rand(1.0, 1.6)) {
    this.wT = Math.max(-1, Math.min(1, w));
    this.wOmega = 5.5 / dur;
  }
  // Re-place a foot (side +1 her left): out, forward, toe-out, from where it
  // started. It waits for her weight to come off that foot.
  step(side, x, z, yaw, dur = rand(0.6, 0.85)) { this.queue.push({ side, to: { x, z, yaw }, dur, wait: 0 }); }
  freeFoot() { return Math.abs(this.w) > 0.4 ? -Math.sign(this.w) : 0; }

  // Looking off to one side (+1 her left), strength 0..1.
  look(side, strength = 1) {
    this.turnTarget = side * 0.12 * strength;
    this.restless = Math.max(this.restless, rand(6, 12));
    if (Math.random() < 0.65) {
      this.queue = [];
      this.shiftTo(side * rand(0.6, 1));
      // Then perhaps the free foot (the far one) finds a new spot.
      if (Math.random() < 0.4) this.replace(-side);
    }
  }

  unlook() {
    this.turnTarget = 0;
    if (Math.random() < 0.4) {
      this.queue = [];
      const back = Math.random() < 0.5;
      // Bring a wandered foot home while it's free, else just even out.
      const out = this.feet[-Math.sign(this.w) || 1];
      if (back && Math.abs(this.w) > 0.4 && (Math.abs(out.x) + Math.abs(out.z) + out.yaw) > 0.03) {
        this.step(-Math.sign(this.w), 0, rand(-0.01, 0.02), rand(0, 0.12));
      }
      this.shiftTo(rand(-0.25, 0.25));
    }
  }

  replace(side) {
    const k = this.k;
    this.step(side, rand(...FOOT_OUT) * k * Math.random(), rand(...FOOT_FWD) * k, rand(...FOOT_YAW));
  }

  // On her own every so often: over to the other leg, or even again, with
  // the occasional foot moved.
  fidget() {
    const r = Math.random();
    if (Math.abs(this.w) < 0.3 || r < 0.45) {
      const side = Math.random() < 0.5 ? 1 : -1;
      this.shiftTo(side * rand(0.55, 1));
      if (Math.random() < 0.35) this.replace(-side);
    } else if (r < 0.75) {
      this.shiftTo(-Math.sign(this.w) * rand(0.5, 0.95), rand(1.2, 1.8));
    } else {
      const free = this.freeFoot();
      if (free) this.step(free, 0, rand(-0.01, 0.02), rand(0, 0.15));
      this.shiftTo(rand(-0.2, 0.2), rand(1.1, 1.6));
    }
  }

  // A stressed word while she talks: a hand may take a new shape for it.
  beat(strength = 1) {
    this.shapeT = rand(2, 4);
    const first = Math.random() < 0.5 ? 1 : -1;
    for (const s of [first, -first]) {
      const h = this.shape[s];
      if (h.hold > 0 || Math.random() < (s === first ? 0.35 : 0.6)) continue;
      const pool = strength > 1 ? ['open', 'open', 'half', 'loose'] : TALK_SHAPES;
      let next = pool[(Math.random() * pool.length) | 0];
      if (next === h.shape) next = 'relaxed';
      this.handShape(s, next, rand(0.8, 2.2));
    }
  }

  handShape(s, name, hold) { const h = this.shape[s]; h.shape = name; h.hold = hold; }

  // --- time -------------------------------------------------------------

  update(dt, { speaking = false, acting = false } = {}) {
    if (!this.vrm || !this.enabled) return;
    this.clock += dt;
    // The waist turn is a soft spring, never a snap.
    const K = 7, C = 5.2;
    this.turnV += (K * (this.turnTarget - this.turn) - C * this.turnV) * dt;
    this.turn += this.turnV * dt;
    // Hand shapes: held a while, then back to relaxed; now and then a quiet
    // hand re-settles (gathers a moment, then relaxes), as people do.
    this.settle -= dt;
    // Between stressed words too, so a long sentence isn't one held shape.
    this.shapeT = (this.shapeT ?? 2) - (speaking ? dt : 0);
    if (speaking && this.shapeT <= 0) this.beat(0.8);
    for (const s of [1, -1]) {
      const h = this.shape[s], st = Math.min(dt, 0.05);
      h.hold -= dt;
      if (h.hold <= 0 && h.shape !== 'relaxed') { h.shape = 'relaxed'; h.hold = speaking ? rand(0.3, 0.8) : 0; }
      const goal = SHAPES[h.shape];
      for (let n = 0; n < 4; n++) [h.curl[n], h.curlV[n]] = spring(h.curl[n], h.curlV[n], goal.curl[n], FINGER_SPEED[n], st);
      [h.fan, h.fanV] = spring(h.fan, h.fanV, goal.fan, 10, st);
    }
    if (this.settle <= 0) {
      if (!speaking) { const s = Math.random() < 0.5 ? 1 : -1; this.handShape(s, 'gathered', rand(0.5, 0.9)); }
      this.settle = rand(10, 25);
    }

    if (!acting) {
      this.restless -= dt * (speaking ? 0.5 : 1);
      if (this.restless <= 0 && !this.task && !this.queue.length) {
        this.fidget();
        this.restless = rand(10, 25);
      }
    }

    // Her weight: towards where she's decided, plus a slow drift, so she's
    // never quite still; the body above the hips follows a beat later.
    const h = Math.min(dt, 0.05);
    const goal = Math.max(-1, Math.min(1, this.wT + SWAY * wander(this.clock * 0.16, 1.3) + (this.stepLean || 0)));
    [this.w, this.wv] = spring(this.w, this.wv, goal, this.wOmega, h);
    [this.up_w, this.up_wv] = spring(this.up_w, this.up_wv, this.w, this.wOmega * 0.7, h);

    if (!this.task && this.queue.length) {
      const t = this.queue[0];
      if (this.freeFoot() === t.side) {
        this.queue.shift();
        const f = this.feet[t.side];
        t.from = { x: f.x, z: f.z, yaw: f.yaw };
        t.t = 0;
        this.task = t;
      } else if ((t.wait += dt) > 3) this.queue.shift();  // she never got off it
    }
    const t = this.task;
    if (!t) { this.stepLean = 0; return; }
    t.t += dt;
    const p = Math.min(1, t.t / t.dur);
    // Heel peels up first, the foot travels, then sets down heel and all.
    const e = smoother(Math.min(1, Math.max(0, (p - 0.12) / 0.8)));
    const f = this.feet[t.side];
    f.x = t.from.x + (t.to.x - t.from.x) * e;
    f.z = t.from.z + (t.to.z - t.from.z) * e;
    f.yaw = t.from.yaw + (t.to.yaw - t.from.yaw) * e;
    f.lift = Math.pow(Math.sin(Math.PI * p), 1.5) * LIFT * this.k;
    f.pitch = 0.4 * Math.sin(Math.PI * Math.min(1, p * 1.4)) * (1 - p * 0.6);
    // The body helps: a little more weight onto the standing leg meanwhile.
    this.stepLean = Math.sin(Math.PI * p) * 0.15 * -t.side;
    if (p >= 1) { f.lift = 0; f.pitch = 0; this.task = null; this.stepLean = 0; }
  }

  // --- posing -----------------------------------------------------------

  // armsFree: { 1: left, [-1]: right } 0..1, how much each arm is hers to hang.
  apply(dt, armsFree = { 1: 1, [-1]: 1 }) {
    if (!this.vrm) return;
    if (!this.enabled) {
      // Off: she stands in her bind pose, and anything an action moved
      // (legs, fingers, the hips) comes back there once it's over.
      this.b.hips.position.copy(this.hipsRest);
      for (const node of this.neutral) node.quaternion.identity();
      return;
    }
    const T = this.T, k = this.k, b = this.b;
    const w = Math.max(-1.1, Math.min(1.1, this.w));
    const aw = Math.abs(w), wu = this.up_w;
    // Fore and aft, very slowly: nobody stands plumb.
    const rock = 0.004 * k * wander(this.clock * 0.11, 4.2);
    const [qa, qb] = this._q;

    // Hips over the standing foot, sunk a little, standing hip up.
    b.hips.position.copy(this.hipsRest)
      .addScaledVector(this.left, w * SHIFT * k)
      .addScaledVector(this.up, -(DROP * aw + SOFT) * k)
      .addScaledVector(this.fwd, rock);
    const tilt = (node, angle) => { qa.setFromAxisAngle(this.fwd, angle); node.quaternion.premultiply(qa); };
    const yaw = (node, angle) => { qa.setFromAxisAngle(this.up, angle); node.quaternion.premultiply(qa); };
    tilt(b.hips, w * HIP_TILT);
    yaw(b.hips, this.turn * TURN_SHARE.hips + w * HIP_YAW);
    ['spine', 'chest', 'upperChest'].forEach((n, i) => {
      if (!b[n]) return;
      // Leaning back over: the hips' tilt undone, and the lag's overshoot.
      tilt(b[n], -w * HIP_TILT * (i === 0 ? 0.5 : 0.25) - wu * SPINE_BACK[i]);
      if (i === 0) yaw(b[n], -w * HIP_YAW * 0.6);
      yaw(b[n], this.turn * TURN_SHARE[n]);
    });
    b.hips.updateWorldMatrix(true, true);

    const scene = this.vrm.scene;
    const sceneQ = scene.getWorldQuaternion(new T.Quaternion());

    // Legs: each foot stays on its spot.
    for (const [s, side] of [[1, 'left'], [-1, 'right']]) {
      const up = b[`${side}UpperLeg`], lo = b[`${side}LowerLeg`], foot = b[`${side}Foot`];
      if (!up || !lo) continue;
      const f = this.feet[s];
      // The free leg relaxes: knee forward, heel up a little, toes down.
      const relax = Math.max(0, Math.min(1, (-s * w - 0.3) / 0.6));
      const pitch = f.pitch + FREE_HEEL * smoother(relax);
      const spot = this.footRest[s].clone()
        .addScaledVector(this.left, s * f.x)
        .addScaledVector(this.fwd, f.z)
        // Turning about the ankle would sink the toes: raise it to keep them down.
        .addScaledVector(this.up, Math.max(f.lift, this.footLen * Math.sin(pitch) * 0.8));
      const target = scene.localToWorld(spot);
      // Knee forward, a touch outward.
      const hip = up.getWorldPosition(new T.Vector3());
      const pole = hip.lerp(target, 0.5).add(this.dir(this.fwd, sceneQ).multiplyScalar(0.6))
        .add(this.dir(this.left, sceneQ).multiplyScalar(s * 0.07));
      solveArm(this, up, lo, foot, target, pole, 1);
      // On the floor, toes turned out by its yaw, heel up by its pitch.
      qa.setFromAxisAngle(this.up, s * f.yaw);
      qb.setFromAxisAngle(this.left, pitch);
      qa.multiply(qb);
      qb.copy(sceneQ).multiply(qa).multiply(this.footQ[s]);
      setWorldQuat(this, foot, qb, 1);
    }

    // Arms hang.
    for (const s of [1, -1]) {
      const hd = this.hands[s];
      const free = armsFree[s] ?? 1;
      if (!hd || free <= 0.001) { if (hd) hd.target = null; continue; }
      const up = b[`${hd.side}UpperArm`], lo = b[`${hd.side}LowerArm`], hand = b[`${hd.side}Hand`];
      const shoulder = up.getWorldPosition(new T.Vector3());
      const down = this.dir(this.up, sceneQ).negate();
      const out = this.dir(this.left, sceneQ).multiplyScalar(s);
      const fwd = this.dir(this.fwd, sceneQ);
      const ideal = shoulder.clone().addScaledVector(down, hd.len * ARM_REACH)
        .addScaledVector(out, 0.035 * k).addScaledVector(fwd, 0.035 * k);
      // Clear of her hips and skirt to begin with, so collide.js has
      // nothing to fight while she just stands.
      if (this.clear) {
        const d = this.clear(ideal, 0.04 * k) || this.clear(ideal.clone().addScaledVector(down, 0.08 * k), 0.03 * k);
        if (d) ideal.add(d);
      }
      // The hand trails the body a little, like a pendulum.
      if (!hd.target) { hd.target = ideal.clone(); hd.vel.set(0, 0, 0); }
      const step = Math.min(dt, 0.05);
      hd.vel.addScaledVector(ideal.clone().sub(hd.target), 60 * step).multiplyScalar(Math.max(0, 1 - 11 * step));
      hd.target.addScaledVector(hd.vel, step);
      if (hd.target.distanceTo(ideal) > 0.08) hd.target.copy(ideal);
      const pole = shoulder.clone().addScaledVector(fwd, -0.4).addScaledVector(out, 0.22).addScaledVector(down, 0.2);
      solveArm(this, up, lo, hand, hd.target, pole, free);

      // Palm to her thigh, fingers down and a little forward.
      const fing = down.clone().multiplyScalar(0.96).addScaledVector(fwd, 0.22).addScaledVector(out, 0.05).normalize();
      const palm = out.clone().negate();
      palm.addScaledVector(fing, -palm.dot(fing)).normalize();
      const want = new T.Matrix4().makeBasis(fing, palm, new T.Vector3().crossVectors(fing, palm));
      // The turn from her bind-pose hand frame to this one, applied to the
      // bind-pose hand: world = want * rest^-1 * handQ.
      qa.setFromRotationMatrix(want.multiply(hd.rest)).multiply(hd.handQ).normalize();
      setWorldQuat(this, hand, qa, free);

      // The hand's shape, and a slow drift of the whole hand so it never
      // sets solid.
      const drift = 0.06 * wander(this.clock * 0.3, s * 2.1);
      const sh = this.shape[s];
      for (const { node, n, i, axis, spread } of hd.fingers) {
        qa.setFromAxisAngle(axis, CURL[n][i] * (sh.curl[n] + drift * (1 + n * 0.3)));
        if (i === 0) qa.premultiply(qb.setFromAxisAngle(spread, SPREAD[n] * (1 + drift) + sh.fan * 0.06 * (n - 1.2)));
        node.quaternion.slerp(qa, free);
      }
      // The thumb, aimed in world space along the index finger.
      const [tm, tp, td] = hd.thumb;
      if (tm && tp) {
        hand.updateWorldMatrix(false, true);
        const side3 = new T.Vector3().crossVectors(fing, palm);
        const aim = (node, child, [a, b2, c]) => {
          const len = node.getWorldPosition(new T.Vector3()).distanceTo(child.getWorldPosition(new T.Vector3()));
          const d = fing.clone().multiplyScalar(a).addScaledVector(side3, b2).addScaledVector(palm, c).normalize();
          aimBone(this, node, child, node.getWorldPosition(new T.Vector3()).addScaledVector(d, len), free);
        };
        aim(tm, tp, THUMB_AIM[0]);
        if (td) aim(tp, td, THUMB_AIM[1]);
        if (td && hd.thumbTipAxis) {
          qa.setFromAxisAngle(hd.thumbTipAxis, THUMB_TIP * (0.4 + 0.6 * (sh.curl[0] + sh.curl[1]) / 2 + drift));
          td.quaternion.slerp(qa, free);
        }
      }
    }
  }

  // One of her scene-frame directions in world space.
  dir(v, sceneQ) { return v.clone().applyQuaternion(sceneQ); }
}
