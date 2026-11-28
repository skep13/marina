// Keeps her arms and hands out of her body. Mocap clips are recorded on
// another body, and even her own hanging arms can swing into a wider skirt or
// hip, so after everything else has posed her this pushes the elbows, forearms,
// wrists and hands back out to her surface.
//
// Her body is measured once, from her own mesh in the bind pose: thin
// horizontal slices from her shoulders down to her knees, each an ellipse
// (two below the hips, one per leg) fixed to the bone it moves with. Hair, the
// face and the arms themselves are left out.
import { setWorldQuat, solveArm } from './actions.js';

const SLICE = 0.03;      // m between slices
const SKIP_MATERIAL = /hair|face|eye|brow|lash|mouth|teeth|tooth|tongue/i;
const ARM_BONE = /shoulder|upperarm|lowerarm|hand|thumb|index|middle|ring|little|arm|elbow|wrist|finger/i;
// How far each point on the arm must stay from her surface (its own thickness).
// Small: the slices already include her (loose) clothes, and an arm resting
// against her side is fine. This is for arms going *through* her.
const MARGIN = { elbow: 0.02, forearm: 0.02, wrist: 0.015, hand: 0.01, fingers: 0.006 };
// The slices are measured over her clothes; the body inside a loose jacket
// is narrower, and an arm hanging at her side sits against the jacket.
const SHRINK_X = 0.8, SHRINK_Z = 0.88;

export class Collide {
  constructor(THREE) {
    this.T = THREE;
    this._q = Array.from({ length: 6 }, () => new THREE.Quaternion());
    this.slices = [];
    this.enabled = true;
    this.hits = 0;   // points pushed out on the last frame, for tests
  }

  mount(vrm) {
    const T = this.T;
    this.vrm = vrm;
    this.slices = [];
    const h = vrm.humanoid;
    if (!h) return;
    const b = (n) => h.getNormalizedBoneNode(n);
    const scene = vrm.scene;

    // Bind pose for the measuring, then back to how app.js left her.
    const saved = new Map();
    scene.traverse((o) => saved.set(o, [o.quaternion.clone(), o.position.clone()]));
    h.resetNormalizedPose();
    h.update?.();
    scene.updateWorldMatrix(true, true);
    const local = (n) => { const node = b(n); return node ? scene.worldToLocal(node.getWorldPosition(new T.Vector3())) : null; };

    const left = local('leftUpperLeg').sub(local('rightUpperLeg')).setY(0).normalize();
    const fwd = new T.Vector3().crossVectors(left, new T.Vector3(0, 1, 0)).normalize();
    const top = (local('leftUpperArm') || local('upperChest') || local('chest')).y - 0.09;
    const knee = (local('leftLowerLeg') || local('hips')).y;
    const crotch = local('leftUpperLeg').y - 0.05;
    const heights = ['upperChest', 'chest', 'spine'].map((n) => [n, local(n)?.y]).filter(([, y]) => y != null);

    // Every body vertex in the scene's frame, as (side, up, forward).
    const bins = new Map();
    const v = new T.Vector3();
    scene.traverse((m) => {
      if (!m.isSkinnedMesh || !m.geometry?.attributes?.position) return;
      const g = m.geometry, pos = g.attributes.position;
      const si = g.attributes.skinIndex, sw = g.attributes.skinWeight;
      const bonesOf = m.skeleton.bones;
      const mats = Array.isArray(m.material) ? m.material : [m.material];
      const skipMat = mats.map((mt) => SKIP_MATERIAL.test(mt?.name || '') || SKIP_MATERIAL.test(m.name));
      const ranges = g.groups.length ? g.groups : [{ start: 0, count: (g.index || pos).count, materialIndex: 0 }];
      const idx = g.index;
      const seen = new Uint8Array(pos.count);
      for (const r of ranges) {
        if (skipMat[r.materialIndex ?? 0]) continue;
        for (let k = r.start; k < r.start + r.count; k++) {
          const i = idx ? idx.getX(k) : k;
          if (seen[i]) continue;
          seen[i] = 1;
          // Its main bone: skip the arms.
          let best = 0, bone = null;
          for (let j = 0; j < 4; j++) {
            const wj = sw.getComponent(i, j);
            if (wj > best) { best = wj; bone = bonesOf[si.getComponent(i, j)]; }
          }
          if (bone && ARM_BONE.test(bone.name)) continue;
          v.fromBufferAttribute(pos, i);
          m.applyBoneTransform(i, v);
          m.localToWorld(v);
          scene.worldToLocal(v);
          if (v.y > top || v.y < knee) continue;
          const key = Math.round(v.y / SLICE);
          let bin = bins.get(key);
          if (!bin) bins.set(key, bin = []);
          bin.push(v.dot(left), v.dot(fwd));
        }
      }
    });

    const boneAt = (y) => {
      for (const [n, by] of heights) if (y >= by) return n;
      return 'hips';
    };
    for (const [key, pts] of bins) {
      if (pts.length < 24) continue;
      const y = key * SLICE;
      const blobs = [];
      if (y < crotch) {
        // Two legs, unless a skirt joins them: look for a gap down the middle.
        let near = 0;
        for (let i = 0; i < pts.length; i += 2) if (Math.abs(pts[i]) < 0.012) near++;
        if (near < 2) {
          const l = [], r = [];
          for (let i = 0; i < pts.length; i += 2) (pts[i] > 0 ? l : r).push(pts[i], pts[i + 1]);
          if (l.length >= 12) blobs.push([l, 'leftUpperLeg']);
          if (r.length >= 12) blobs.push([r, 'rightUpperLeg']);
        } else blobs.push([pts, 'hips']);
      } else blobs.push([pts, boneAt(y)]);

      for (const [p, boneName] of blobs) {
        const node = b(boneName);
        if (!node) continue;
        let x0 = Infinity, x1 = -Infinity, z0 = Infinity, z1 = -Infinity;
        for (let i = 0; i < p.length; i += 2) {
          x0 = Math.min(x0, p[i]); x1 = Math.max(x1, p[i]);
          z0 = Math.min(z0, p[i + 1]); z1 = Math.max(z1, p[i + 1]);
        }
        const cx = (x0 + x1) / 2, cz = (z0 + z1) / 2;
        // An ellipse inside the box. Her clothes are loose (the box takes in
        // the jacket hanging open), so a little smaller than the box: arms
        // resting on the jacket press into it a touch, as they would.
        const rx = (x1 - x0) / 2 * SHRINK_X, rz = (z1 - z0) / 2 * SHRINK_Z;
        const c = left.clone().multiplyScalar(cx).addScaledVector(fwd, cz).setY(y);
        // In the bone's frame (normalized bones rest aligned with the scene).
        const cl = node.worldToLocal(scene.localToWorld(c.clone()));
        const lx = node.worldToLocal(scene.localToWorld(c.clone().add(left))).sub(cl).normalize();
        const lz = node.worldToLocal(scene.localToWorld(c.clone().add(fwd))).sub(cl).normalize();
        const ly = new T.Vector3().crossVectors(lz, lx).normalize();
        this.slices.push({ node, c: cl, ax: lx, az: lz, ay: ly, rx, rz, y });
      }
    }
    this.slices.sort((a, b2) => b2.y - a.y);

    this.arms = {};
    for (const side of ['left', 'right']) {
      const a = { up: b(`${side}UpperArm`), lo: b(`${side}LowerArm`), hand: b(`${side}Hand`),
        mid: b(`${side}MiddleProximal`), tip: b(`${side}MiddleDistal`) };
      if (a.up && a.lo && a.hand) this.arms[side] = a;
    }

    for (const [o, [q, p]] of saved) { o.quaternion.copy(q); o.position.copy(p); }
    h.update?.();
    scene.updateWorldMatrix(true, true);
  }

  get ready() { return this.slices.length > 0; }

  // How far, and which way, a world point must move to sit `margin` outside
  // her body; null when it's already clear. Everything here is continuous in
  // the point (slices fade out at their edges, no direction flips), so a
  // hand moving smoothly is pushed smoothly.
  push(p, margin) {
    const T = this.T;
    let best = null, bestLen = 0;
    const l = this._l || (this._l = new T.Vector3());
    for (const s of this.slices) {
      l.copy(p);
      s.node.worldToLocal(l);
      l.sub(s.c);
      const dy = Math.abs(l.dot(s.ay));
      if (dy > SLICE) continue;
      const fade = dy < SLICE * 0.5 ? 1 : 1 - smooth01((dy - SLICE * 0.5) / (SLICE * 0.5));
      const x = l.dot(s.ax), z = l.dot(s.az);
      const rx = s.rx + margin, rz = s.rz + margin;
      if ((x * x) / (rx * rx) + (z * z) / (rz * rz) >= 1) continue;
      // Out along the ray from the slice's centre, leaning forwards unless
      // the point is well behind her: arms crossed or hands clasped belong
      // in front of her, hands behind her back stay there.
      // (Only near her middle: a point at her side just goes out sideways.)
      const middle = 1 - smooth01(Math.abs(x) / (0.6 * rx));
      let dx = x, dz = z + 0.6 * rz * middle * smooth01((z + 0.75 * rz) / (0.3 * rz));
      if (Math.hypot(dx, dz) < 1e-4) { dx = 0; dz = 1; }
      const sc = 1 / Math.sqrt((dx * dx) / (rx * rx) + (dz * dz) / (rz * rz));
      const ox = (dx * sc - x) * fade, oz = (dz * sc - z) * fade;
      const len = Math.hypot(ox, oz);
      if (len <= bestLen) continue;
      bestLen = len;
      const q = s.node.getWorldQuaternion(this._q[0]);
      best = (best || new T.Vector3()).copy(s.ax).multiplyScalar(ox).addScaledVector(s.az, oz).applyQuaternion(q);
    }
    return best;
  }

  // After everything else has posed her arms this frame. The correction is
  // worked out from that pose alone (never from last frame's correction, so
  // it can't feed back on itself) and eased in and out over time.
  apply(dt = 1 / 60) {
    if (!this.enabled || !this.ready) return;
    const T = this.T;
    this.vrm.scene.updateWorldMatrix(true, true);
    this.hits = 0;
    const P = (n) => n.getWorldPosition(new T.Vector3());
    const up = 1 - Math.exp(-dt * 22), down = 1 - Math.exp(-dt * 6);
    const ease = (cur, raw) => {
      const k = raw.lengthSq() > cur.lengthSq() ? up : down;
      return cur.lerp(raw, k);
    };
    const zero = new T.Vector3();
    for (const a of Object.values(this.arms)) {
      a.offH ||= new T.Vector3(); a.offE ||= new T.Vector3();
      const S = P(a.up), E = P(a.lo), W = P(a.hand);
      const H = a.mid ? P(a.mid) : W.clone();
      const F = a.tip ? P(a.tip) : H.clone();
      const M = E.clone().lerp(W, 0.5);
      const dE = this.push(E, MARGIN.elbow) || zero.clone();
      const dM = this.push(M, MARGIN.forearm);
      let dH = zero.clone();
      for (const [pt, m] of [[W, MARGIN.wrist], [H, MARGIN.hand], [F, MARGIN.fingers]]) {
        const d = this.push(pt, m);
        if (d && d.lengthSq() > dH.lengthSq()) dH = d;
      }
      if (dM) { dH.addScaledVector(dM, 0.6); dE.addScaledVector(dM, 0.7); }
      this.hits += (dE.lengthSq() > 1e-8) + (dH.lengthSq() > 1e-8);
      a.last = { elbow: dE.length(), forearm: dM ? dM.length() : 0, hand: dH.length() };
      ease(a.offH, dH);
      ease(a.offE, dE);
      if (a.offH.lengthSq() < 1e-8 && a.offE.lengthSq() < 1e-8) continue;
      // Hand out, and the elbow swung out by aiming the arm's bend there.
      const target = W.clone().add(a.offH);
      const pole = E.clone().addScaledVector(a.offE, 3)
        .add(E.clone().sub(S.clone().lerp(W, 0.5)));
      // Faded in with the size of the push: with her arm hanging nearly
      // straight the bend direction above is barely defined, and solving
      // fully for a millimetre's push could snap her elbow round.
      const w = smooth01(Math.max(a.offH.length(), a.offE.length()) / 0.012);
      const keep = a.hand.getWorldQuaternion(this._q[1]).clone();
      solveArm(this, a.up, a.lo, a.hand, target, pole, w);
      setWorldQuat(this, a.hand, keep, w);
    }
  }
}

const smooth01 = (x) => (x <= 0 ? 0 : x >= 1 ? 1 : x * x * (3 - 2 * x));
