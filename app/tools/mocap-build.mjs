// Packs the Mixamo clips in mocap-src/*.fbx into models/mocap.bin, already
// retargeted to VRM humanoid bones, so the app needs no FBX loader.
//
//   node tools/mocap-build.mjs            (from app/)
//
// Rotations are stored the way three-vrm's normalized humanoid wants them
// (VRM 1 axes; the renderer flips x/z for VRM 0 models). The hips position is
// stored as a fraction of the source rig's hips height, so the renderer can
// scale it to any model. The FBX files are Mixamo exports (X Bot, no skin,
// 30 fps); they and the .bin stay out of git.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { Quaternion, Vector3 } from 'three';
import { FBXLoader } from 'three/examples/jsm/loaders/FBXLoader.js';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
// Optional: node tools/mocap-build.mjs <fbx folder> <out.bin>, for trying clips out.
const SRC = process.argv[2] ? path.resolve(process.argv[2]) : path.join(ROOT, 'mocap-src');
const OUT = process.argv[3] ? path.resolve(process.argv[3]) : path.join(ROOT, 'models', 'mocap.bin');
const FPS = 30;
const POS_SCALE = 8192;
// How much of the hips' turn about the vertical to keep. Some clips (looking
// around, the bored idle) turn her whole body away from the camera; she should
// stay facing you, with the turn left to her waist and head.
const HIPS_YAW = 0.25; // hips position: fraction of hips height, x8192 in int16

const BONES = {
  Hips: 'hips', Spine: 'spine', Spine1: 'chest', Spine2: 'upperChest', Neck: 'neck', Head: 'head',
  LeftUpLeg: 'leftUpperLeg', LeftLeg: 'leftLowerLeg', LeftFoot: 'leftFoot', LeftToeBase: 'leftToes',
  RightUpLeg: 'rightUpperLeg', RightLeg: 'rightLowerLeg', RightFoot: 'rightFoot', RightToeBase: 'rightToes',
};
for (const side of ['Left', 'Right']) {
  const s = side.toLowerCase();
  Object.assign(BONES, {
    [`${side}Shoulder`]: `${s}Shoulder`, [`${side}Arm`]: `${s}UpperArm`,
    [`${side}ForeArm`]: `${s}LowerArm`, [`${side}Hand`]: `${s}Hand`,
    [`${side}HandThumb1`]: `${s}ThumbMetacarpal`, [`${side}HandThumb2`]: `${s}ThumbProximal`, [`${side}HandThumb3`]: `${s}ThumbDistal`,
  });
  for (const [mx, vrm] of [['Index', 'Index'], ['Middle', 'Middle'], ['Ring', 'Ring'], ['Pinky', 'Little']]) {
    BONES[`${side}Hand${mx}1`] = `${s}${vrm}Proximal`;
    BONES[`${side}Hand${mx}2`] = `${s}${vrm}Intermediate`;
    BONES[`${side}Hand${mx}3`] = `${s}${vrm}Distal`;
  }
}

// Rokoko's skeleton (and other BVH/FBX rigs) use mostly the same names
// without the mixamorig prefix, with an extra spine bone or two and their own
// toe and finger names.
const ALIASES = {
  Spine3: 'Spine2', Spine4: 'Spine2', LeftToe: 'LeftToeBase', RightToe: 'RightToeBase',
  LeftUpperLeg: 'LeftUpLeg', RightUpperLeg: 'RightUpLeg', LeftLowerLeg: 'LeftLeg', RightLowerLeg: 'RightLeg',
  LeftUpperArm: 'LeftArm', RightUpperArm: 'RightArm', LeftLowerArm: 'LeftForeArm', RightLowerArm: 'RightForeArm',
};
for (const side of ['Left', 'Right']) {
  for (const [ro, mx] of [['Thumb', 'Thumb'], ['Index', 'Index'], ['Middle', 'Middle'], ['Ring', 'Ring'], ['Pinky', 'Pinky'], ['Little', 'Pinky']]) {
    for (const n of [1, 2, 3]) ALIASES[`${side}Finger${ro}${n}`] = ALIASES[`${side}${ro}${n}`] = `${side}Hand${mx}${n}`;
  }
}
// A rig bone's name as a Mixamo name, whatever rig it came from.
const canon = (name) => {
  const bare = name.replace(/^mixamorig\d*:?/, '').replace(/^.*:/, '');
  return ALIASES[bare] || bare;
};

function load(file) {
  const buf = fs.readFileSync(file);
  return new FBXLoader().parse(buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength), '');
}

const q = new Quaternion();
const restInv = new Quaternion();
const twist = new Quaternion();
const ident = new Quaternion();
const parentRest = new Quaternion();
const chunks = [];
let offset = 0;
const index = { version: 1, fps: FPS, posScale: POS_SCALE, clips: {} };

function push(arr) {
  const int = Int16Array.from(arr);
  chunks.push(int);
  const at = offset;
  offset += int.length;
  return at;
}

// One frame if the track never moves, so still bones cost nothing.
function packed(values, stride, frames) {
  const first = values.slice(0, stride);
  const still = values.every((v, i) => Math.abs(v - first[i % stride]) <= 1);
  return still ? { n: 1, data: first } : { n: frames, data: values };
}

const files = fs.readdirSync(SRC).filter((f) => f.endsWith('.fbx')).sort();
for (const f of files) {
  const key = f.replace(/\.fbx$/, '');
  const asset = load(path.join(SRC, f));
  const clip = asset.animations[0];
  if (!clip) { console.warn('no animation in', f); continue; }
  let hipsNode = null;
  asset.traverse((o) => { if (!hipsNode && canon(o.name) === 'Hips') hipsNode = o; });
  if (!hipsNode) { console.warn('no hips in', f); continue; }
  // Height of the hips above the feet in the rig's rest pose.
  asset.updateMatrixWorld(true);
  const hipsWorld = hipsNode.getWorldPosition(new Vector3());
  let footY = Infinity;
  asset.traverse((o) => { if (/Foot|Toe/.test(canon(o.name))) footY = Math.min(footY, o.getWorldPosition(new Vector3()).y); });
  // (Mixamo's hips sit straight above the origin at the floor: keep its own
  // number so existing clips build exactly as before.)
  const hipsHeight = /mixamorig/.test(hipsNode.name) ? hipsNode.position.y
    : (Number.isFinite(footY) ? hipsWorld.y - footY : hipsNode.position.y) / asset.scale.y;
  const frames = Math.max(2, Math.round(clip.duration * FPS) + 1);
  const entry = { frames, duration: (frames - 1) / FPS, bones: {} };

  for (const track of clip.tracks) {
    const [rigName, prop] = track.name.split('.');
    const bone = BONES[canon(rigName)];
    if (!bone) continue;
    const node = asset.getObjectByName(rigName);
    const interp = track.createInterpolant();
    if (prop === 'quaternion') {
      node.getWorldQuaternion(restInv).invert();
      node.parent.getWorldQuaternion(parentRest);
      const out = new Array(frames * 4);
      let prev = null;
      for (let i = 0; i < frames; i++) {
        q.fromArray(interp.evaluate(Math.min(i / FPS, clip.duration)));
        q.premultiply(parentRest).multiply(restInv).normalize();
        if (bone === 'hips') {
          // q = swing * twist, twist about the vertical: keep a little twist.
          twist.set(0, q.y, 0, q.w).normalize();
          q.multiply(twist.clone().invert()).multiply(ident.clone().slerp(twist, HIPS_YAW)).normalize();
        }
        // Keep neighbouring frames in the same hemisphere so int16 rounding
        // and linear reads between frames never flip through the long way.
        if (prev && prev.dot(q) < 0) q.set(-q.x, -q.y, -q.z, -q.w);
        prev = q.clone();
        out[i * 4] = Math.round(q.x * 32767);
        out[i * 4 + 1] = Math.round(q.y * 32767);
        out[i * 4 + 2] = Math.round(q.z * 32767);
        out[i * 4 + 3] = Math.round(q.w * 32767);
      }
      const p = packed(out, 4, frames);
      (entry.bones[bone] ||= {}).rot = [push(p.data), p.n];
    } else if (prop === 'position' && bone === 'hips') {
      const out = new Array(frames * 3);
      for (let i = 0; i < frames; i++) {
        const v = interp.evaluate(Math.min(i / FPS, clip.duration));
        for (let k = 0; k < 3; k++) out[i * 3 + k] = Math.round((v[k] / hipsHeight) * POS_SCALE);
      }
      const p = packed(out, 3, frames);
      (entry.bones.hips ||= {}).pos = [push(p.data), p.n];
    }
  }
  index.clips[key] = entry;
}

const json = Buffer.from(JSON.stringify(index));
const pad = (4 - ((4 + json.length) % 4)) % 4;
const head = Buffer.alloc(4);
head.writeUInt32LE(json.length + pad);
const body = Buffer.concat(chunks.map((c) => Buffer.from(c.buffer, c.byteOffset, c.byteLength)));
fs.writeFileSync(OUT, Buffer.concat([head, json, Buffer.alloc(pad, 0x20), body]));
console.log(`${Object.keys(index.clips).length} clips → ${path.relative(ROOT, OUT)} (${(fs.statSync(OUT).size / 1e6).toFixed(1)} MB)`);
