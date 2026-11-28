// Her *actions* as whole-body animation: *stretches*, *leans in*, *claps*,
// *hugs her knees*. app.js hands each action's text to classifyAction(), which
// picks a body clip and any face cues, and BodyActions plays the clip on top
// of the idle animation.
//
// A clip is a few key poses in time. Hands are placed by inverse kinematics
// (where the hand should be, next to her head, chest, hips or knees), so the
// same clip fits any model; the torso and hips are nudged on top of the idle
// pose, and the legs are always solved so her feet stay on the floor however
// her hips move. Directions are in her own frame: x towards the hand's own
// side (mirrored for the right hand), y up, z towards the viewer. Metres.

// ── Which clip an action means ─────────────────────────────────────────────
// Phrases from her real replies, most common first: laughs, smiles, smirks,
// rolls eyes, leans in (closer to the camera / screen), sighs, leans back,
// shrugs, waves, claps, rests chin on hand, reaches toward the screen,
// stretches, covers eyes / mouth, facepalms, crosses arms, blows a kiss...
// First match wins within one clause; across clauses ("laughs and claps")
// the more specific clip wins.
const BODY_PATTERNS = [
  ['hugKnees',   /\bhug(s|ging)?\s+(her\s+|my\s+)?knees\b|\bcurl(s|ing)?\s+up\b|\bknees\s+(up|to\s+(her\s+)?chest)\b|\bcrouch|\bsquat|\bsits?\s+(down\s+)?on\s+the\s+floor\b/],
  ['hugSelf',    /\bhug(s|ging)?\s+(her|my)self\b|\bwraps?\s+(her\s+)?arms\s+around\s+(her|my)self\b|\bshudder|\bshiver|\bshivers?\b/],
  ['hug',        /\bhug(s|ging)?\b|\bopens?\s+(her\s+)?arms\b|\barms\s+(wide|open)\b|\bembrace/],
  ['stretch',    /\bstretch/],
  ['dance',      /\bdanc(e|es|ing)\b|\bgroov|\bboogie|\bshimm(y|ies)\b|\btwirl/],
  ['cheer',      /\bjump(s|ing)?\b|\bwiggl|\bcheer|\bfist\s*pump|\bpumps?\s+(her\s+)?fists?\b|\bbounc(e|es|ing)\b|\bhops?\b|\bpumped\b/],
  ['clap',       /\bclap/],
  ['wave',       /\bwav(e|es|ing)\b/],
  ['facepalm',   /\bface\s*-?\s*palm|\bpalm\s+(to|on|against)\s+(her\s+)?(face|forehead)\b|\bhead\s+in\s+(her\s+)?hands?\b|\bdrags?\s+(a\s+)?hands?\s+down\s+(her\s+)?face/],
  ['coverEyes',  /\bcovers?\s+(her\s+)?(eyes|face)\b|\bpeeks?\s+(through|between)\b|\bhides?\s+(her\s+)?face\b/],
  ['coverMouth', /\bcovers?\s+(her\s+)?mouth\b|\bhand\s+(over|to|on)\s+(her\s+)?mouth\b|\bstifl/],
  ['rubEyes',    /\brubs?\s+(her\s+)?eyes?\b/],
  ['wipeTear',   /\bwip(e|es|ing)\s+(away\s+)?(a\s+)?tears?\b|\bdabs?\s+(at\s+)?(her\s+)?eyes?\b/],
  ['chin',       /\bchin\s+(on|in)\s+(her\s+|one\s+)?hands?\b|\b(rests?|lean(s|ing)?|props?|resting)\s+(her\s+)?(chin|head|cheek)\s+(on|in|against)\b|\bhead\s+on\s+(her\s+|one\s+)?hand/],
  ['think',      /\btaps?\s+(her\s+)?(chin|lip|cheek)s?\b|\bscratch(es|ing)?\s+(her\s+)?(chin|head|cheek)\b|\bstrok(e|es|ing)\s+(her\s+)?chin\b|\bfinger\s+to\s+(her\s+)?(chin|lips?)\b/],
  ['crossArms',  /\bcross(es|ing)?\s+(her\s+)?arms\b|\barms\s+crossed\b|\bfolds?\s+(her\s+)?arms\b|\bhands?\s+on\s+(her\s+)?hips\b/],
  ['kiss',       /\bkiss/],
  ['thumbsUp',   /\bthumbs?\s*-?\s*up\b|\bok(ay)?\s+sign\b/],
  ['salute',     /\bsalut/],
  ['peace',      /\bpeace\s+sign\b|\bv\s+sign\b/],
  ['hair',       /\bhair\b|\bear\b/],
  ['sip',        /\bsips?\b|\bsipping\b|\bdrinks?\b|\bmug\b|\bcup\s+of\b|\btea\b|\bcoffee\b|\bcocoa\b/],
  ['point',      /\bpoint(s|ing)?\b/],
  ['reach',      /\breach(es|ing)?\b|\bpokes?\b|\bboops?\b|\btouch(es|ing)?\b|\bpats?\b|\bholds?\s+out\b|\boffers?\b/],
  ['nudge',      /\bnudg|\bbumps?\b|\belbows?\b/],
  ['fidget',     /\bfidget|\btwiddl|\bnervous|\bfiddl/],
  ['bow',        /\bbow(s|ing)?\b|\bcurts(e)?y/],
  ['yawn',       /\byawn/],
  ['rubNeck',    /\brubs?\s+(the\s+back\s+of\s+)?(her\s+)?(neck|head)\b|\bsheepish/],
  ['wince',      /\bwinc|\bgrimac|\bcring|\bflinch|\bshudders?\b/],
  ['dismiss',    /\bwav(e|es|ing)\s+(it\s+|a\s+hand\s+|her\s+hand\s+)?(off|away|dismissively)|\bdismissive|\bbrush(es)?\s+it\s+off|\bswats?\b/],
  ['leanBack',   /\blean(s|ing)?\s+back\b|\bsits?\s+back\b|\breclin|\bslumps?\b|\bflops?\b/],
  ['leanIn',     /\blean(s|ing)?\s+(in|forward|closer|toward|towards|over|close)\b|\bscoots?\s+(closer|in)\b|\bmoves?\s+closer\b|\bcloser\s+to\s+the\s+(screen|camera)\b|\bleans?\b/],
  ['shrug',      /\bshrug/],
  ['headShake',  /\bshak(e|es|ing)\s+(her\s+)?head\b/],
  ['nod',        /\bnod(s|ding)?\b/],
  ['thankful',   /\bhands?\s+(on|over|to)\s+(her\s+)?(heart|chest)\b/],
  ['lookAway',   /\blook(s|ing)?\s+away\b|\baverts?\b|\bglances?\s+away\b/],
  ['shift',      /\bshift(s|ing)?\b|\badjust(s|ing)?\s+(her\s+)?(position|seat|posture)\b|\bsettl(e|es|ing)\b|\bsways?\b|\brocks?\s+(on|back)\b/],
  ['laugh',      /\blaugh|\bgiggl|\bchuckl|\bsnicker|\bsnort|\bcackl/],
  ['sighBody',   /\bsigh|\bgroan|\bexhal|\bhuff/],
  ['startle',    /\bgasp|\bstartl|\bjolt|\bjumps?\s+back\b|\beyes\s+widen|\bwidens?\s+(her\s+)?eyes/],
];

// Clips for the bridge's own animation names, for replies that arrive with no
// action text (older bridges, the idle gestures).
const ANIMATION_BODY = {
  laugh: 'laugh', shrug: 'shrug', lean: 'leanIn', yawn: 'stretch', wave: 'wave',
  sigh: 'sighBody', surprised: 'startle', emote: 'gesture', think: 'think',
};

// Clips that say less than a more specific one in the same action.
const GENERIC = new Set(['laugh', 'leanIn', 'shift', 'gesture', 'wince', 'sighBody', 'startle', 'leanBack', 'nudge', 'nod', 'headShake', 'lookAway']);

// The face and head cues app.js already has (its CUES), for the same text.
// The same order and words as the bridge's classifier (process/text_func/speech.py).
const FACE_PATTERNS = [
  ['wave',      /\bwav(e|es|ing)\b/],
  ['eyeroll',   /\broll(s|ing)?\s+(her\s+|his\s+|their\s+)?eyes\b|\beyeroll\b/],
  ['shake',     /\bshak(e|es|ing)\s+(her\s+|his\s+|their\s+)?head\b|\bshakes\b/],
  ['nod',       /\bnod(s|ding)?\b/],
  ['tilt',      /\btilt(s|ing)?\b|\bcocks?\s+(her|his|their)?\s*head\b/],
  ['shrug',     /\bshrug(s|ging)?\b/],
  ['lean',      /\blean(s|ing)?\b/],
  ['wink',      /\bwink(s|ing)?\b|\bopens?\s+one\s+eye\b/],
  ['laugh',     /\blaugh(s|ing)?\b|\bgiggl(e|es|ing)\b|\bchuckl(e|es|ing)\b|\bsnicker(s|ing)?\b|\bsnort(s|ing)?\b/],
  ['blush',     /\bblush(es|ing)?\b|\bflustered\b|\bembarrassed\b/],
  ['sigh',      /\bsigh(s|ing)?\b|\bgroan(s|ing)?\b|\bhuff(s|ing)?\b|\bexhal(e|es|ing)\b/],
  ['pout',      /\bpout(s|ing)?\b|\bfrown(s|ing)?\b|\bscowl(s|ing)?\b|\bglar(e|es|ing)\b|\bwinc(e|es|ing)\b|\bgrimac/],
  ['surprised', /\bgasp(s|ing)?\b|\bblink(s|ing)?\s+in\s+surprise\b|\bstartled\b|\bjolt(s|ing)?\b|\beyes\s+widen|\bwidens?\s+(her\s+)?eyes/],
  ['smile',     /\beyes\s+light|\bsmil(e|es|ing)\b|\bgrin(s|ning)?\b|\bsmirk(s|ing)?\b|\bbeam(s|ing)?\b|\bsoftens?\b|\bteas(e|es|ing)\b/],
  ['sad',       /\bfrowns?\s+sadly\b|\blooks?\s+(down|away)\b|\bwilts?\b|\bdroop(s|ing)?\b/],
  ['think',     /\bthink(s|ing)?\b|\bponder(s|ing)?\b|\bconsider(s|ing)?\b|\bhums?\b/],
  ['brow',      /\b(rais|arch|quirk|lift)(e[sd]|ing)?\s+(an?\s+|her\s+|his\s+|their\s+)?(eye)?brows?/],
  ['stare',     /\blooks?\s+(at|over|around|up)\b|\bwatch(es|ing)?\b|\bstar(e|es|ing)\b|\bglanc(e|es|ing)\b|\bpeer(s|ing)?\b|\bsquint(s|ing)?\b/],
  ['yawn',      /\byawn(s|ing)?\b|\bstretch(es|ing)?\b/],
  ['think',     /\bpaus(e|es|ing)\b|\btrails?\s+off\b/],
];

const FACE_FROM_BODY = {
  hugKnees: 'smile', hugSelf: 'sad', hug: 'smile', cheer: 'laugh', clap: 'smile', kiss: 'wink',
  thumbsUp: 'smile', peace: 'wink', coverMouth: 'surprised', facepalm: 'sigh', rubEyes: 'yawn',
  wipeTear: 'sad', crossArms: 'pout', startle: 'surprised', wince: 'pout', fidget: 'blush',
  rubNeck: 'blush', bow: 'smile', salute: 'smile',
};

function firstMatch(patterns, text) {
  for (const [name, re] of patterns) if (re.test(text)) return name;
  return null;
}

// "laughs and claps her hands" → { body: 'clap', face: ['laugh'] }.
// `animation` is the bridge's name for it, used when there's no text.
export function classifyAction(action, animation) {
  const text = String(action || '').toLowerCase().trim();
  if (!text) {
    return { body: ANIMATION_BODY[animation] || null, face: animation && animation !== 'wave' ? [animation] : [] };
  }
  const clauses = text.split(/,|;|\s+and\s+|\s+then\s+|\s+while\s+|\s+as\s+|\s+with\s+(?=a\s|her\s)/).filter((c) => c.trim());
  let body = null;
  const face = [];
  for (const clause of clauses) {
    const b = firstMatch(BODY_PATTERNS, clause);
    if (b && (!body || (GENERIC.has(body) && !GENERIC.has(b)))) body = b;
    const f = firstMatch(FACE_PATTERNS, clause);
    if (f && f !== 'wave' && f !== 'lean' && f !== 'shrug' && !face.includes(f)) face.push(f);
  }
  // Whole-phrase patterns that span clauses ("hugs her knees to her chest").
  if (!body) body = firstMatch(BODY_PATTERNS, text);
  if (body && !face.length && FACE_FROM_BODY[body]) face.push(FACE_FROM_BODY[body]);
  // Something she does that nothing here knows: a small open-hand gesture
  // rather than nothing at all.
  if (!body && !face.length) body = 'gesture';
  return { body, face: face.slice(0, 2) };
}

// ── Clips ──────────────────────────────────────────────────────────────────
// keys: [time in seconds, pose]. A pose may hold:
//   L, R: a hand: { at: anchor, p: [x,y,z], elbow: [x,y,z], fing, palm, curl }
//         at  head | face | chest | belly | hips | shoulder | knee | other
//             ('other' is the other hand, for clapping and holding hands)
//         elbow: which way the elbow points, from the shoulder
//         fing / palm: where the fingers point and the palm faces; the hand
//             follows the forearm when left out
//         curl: [thumb, index, middle, ring, little], 0 straight, 1 curled
//   torso: { hips, spine, chest, upperChest: [x, y, z] } radians on top of
//         idle (x bends forward, y turns to her left, z leans to her right)
//   hips: [x, y, z] metres moved (y down when negative)
//   face: { hx, hy, hz, gazeX, gazeY, happy, sad, angry, relaxed, surprised,
//           mouth, blink } held while the pose is
// A hand or value missing from a key goes back to idle for that key.
// `out`: seconds to ease back to idle after the last key.
// `run(t, o)`: extra motion each frame (t in seconds), added to the pose.

const FIST = [0.5, 1, 1, 1, 1];
const POINT = [0.6, 0, 1, 1, 1];
const THUMB = [-0.2, 1, 1, 1, 1];
const PEACE = [0.7, 0, 0, 1, 1];
const RELAX = [0.15, 0.15, 0.22, 0.28, 0.34];
const SOFT = [0.3, 0.35, 0.45, 0.55, 0.6];
const CUP = [0.5, 0.55, 0.65, 0.7, 0.75];

const UP = [0, 1, 0], DOWN = [0, -1, 0], FWD = [0, 0, 1], BACK = [0, 0, -1];
const IN = [-1, 0, 0], OUT = [1, 0, 0];

const wob = (t, hz, amp, phase = 0) => Math.sin((t * hz + phase) * Math.PI * 2) * amp;

// Repeat a pair of poses n times from `start`, `period` seconds apart.
function beats(start, period, n, a, b) {
  const keys = [];
  for (let i = 0; i < n; i++) {
    keys.push([start + i * period, a]);
    keys.push([start + i * period + period / 2, b]);
  }
  return keys;
}

export const CLIPS = {
  // *leans in closer to the camera*: forward from the hips, chin up to keep
  // looking at you, hands clasped behind her back.
  leanIn: { out: 0.7, keys: [
    [0.55, { torso: { hips: [0.1, 0, 0], spine: [0.12, 0, 0], chest: [0.12, 0, 0], upperChest: [0.06, 0, 0] },
      hips: [0, 0, -0.05],
      L: { at: 'hips', p: [0.06, -0.02, -0.17], elbow: [0.6, -0.5, -0.6], palm: BACK, fing: IN, curl: RELAX },
      R: { at: 'hips', p: [0.06, -0.02, -0.17], elbow: [0.6, -0.5, -0.6], palm: BACK, fing: IN, curl: RELAX },
      face: { hx: -0.2, happy: 0.25, gazeY: -0.05 } }],
    [2.2, { torso: { hips: [0.11, 0, 0], spine: [0.13, 0.03, 0.02], chest: [0.13, 0.02, 0], upperChest: [0.06, 0, 0] },
      hips: [0, 0, -0.05],
      L: { at: 'hips', p: [0.06, -0.02, -0.17], elbow: [0.6, -0.5, -0.6], palm: BACK, fing: IN, curl: RELAX },
      R: { at: 'hips', p: [0.06, -0.02, -0.17], elbow: [0.6, -0.5, -0.6], palm: BACK, fing: IN, curl: RELAX },
      face: { hx: -0.2, hz: 0.12, happy: 0.3 } }],
  ] },

  // *leans back*: weight back, hands laced behind her head.
  leanBack: { out: 0.8, keys: [
    [0.7, { torso: { hips: [-0.05, 0, 0], spine: [-0.08, 0, 0], chest: [-0.1, 0, 0], upperChest: [-0.05, 0, 0] },
      hips: [0, 0, 0.03],
      L: { at: 'head', p: [0.11, 0.08, -0.1], elbow: [1, 0.35, 0.1], palm: FWD, fing: IN, curl: SOFT },
      R: { at: 'head', p: [0.11, 0.08, -0.1], elbow: [1, 0.35, 0.1], palm: FWD, fing: IN, curl: SOFT },
      face: { hx: -0.08, relaxed: 0.45, happy: 0.2 } }],
    [2.6, { torso: { hips: [-0.06, 0, 0], spine: [-0.09, 0.03, 0], chest: [-0.11, 0, 0], upperChest: [-0.05, 0, 0] },
      hips: [0, 0, 0.03],
      L: { at: 'head', p: [0.11, 0.08, -0.1], elbow: [1, 0.35, 0.1], palm: FWD, fing: IN, curl: SOFT },
      R: { at: 'head', p: [0.11, 0.08, -0.1], elbow: [1, 0.35, 0.1], palm: FWD, fing: IN, curl: SOFT },
      face: { hx: -0.1, hz: -0.06, relaxed: 0.5, happy: 0.25, blink: 0.25 } }],
  ] },

  // *stretches*: arms up over her head, fingers laced, up on her toes, a
  // lean to each side, then a yawn as it lets go.
  stretch: { out: 0.9, keys: [
    [0.45, { L: { at: 'chest', p: [0.05, 0.02, 0.16], elbow: [0.6, -0.6, 0.1], palm: BACK, fing: IN, curl: SOFT },
      R: { at: 'chest', p: [0.05, 0.02, 0.16], elbow: [0.6, -0.6, 0.1], palm: BACK, fing: IN, curl: SOFT } }],
    [1.1, { torso: { spine: [-0.06, 0, 0], chest: [-0.08, 0, 0] }, hips: [0, 0.025, 0],
      L: { at: 'head', p: [0.03, 0.42, 0.02], elbow: [1, 0.3, 0], palm: UP, fing: IN, curl: SOFT },
      R: { at: 'head', p: [0.03, 0.42, 0.02], elbow: [1, 0.3, 0], palm: UP, fing: IN, curl: SOFT },
      face: { hx: -0.22, relaxed: 0.4, blink: 1, mouth: 0.25 } }],
    [1.9, { torso: { spine: [-0.05, 0, -0.12], chest: [-0.06, 0, -0.1] }, hips: [0.02, 0.025, 0],
      L: { at: 'head', p: [0.03, 0.4, 0.02], elbow: [1, 0.3, 0], palm: UP, fing: IN, curl: SOFT },
      R: { at: 'head', p: [0.03, 0.4, 0.02], elbow: [1, 0.3, 0], palm: UP, fing: IN, curl: SOFT },
      face: { hx: -0.18, hz: -0.12, relaxed: 0.4, blink: 1, mouth: 0.55 } }],
    [2.7, { torso: { spine: [-0.05, 0, 0.12], chest: [-0.06, 0, 0.1] }, hips: [-0.02, 0.025, 0],
      L: { at: 'head', p: [0.03, 0.4, 0.02], elbow: [1, 0.3, 0], palm: UP, fing: IN, curl: SOFT },
      R: { at: 'head', p: [0.03, 0.4, 0.02], elbow: [1, 0.3, 0], palm: UP, fing: IN, curl: SOFT },
      face: { hx: -0.18, hz: 0.12, relaxed: 0.4, blink: 0.9, mouth: 0.4 } }],
    [3.3, { face: { relaxed: 0.5, happy: 0.2, blink: 0.3 } }],
  ] },

  // *claps her hands together*: four claps in front of her chest.
  clap: { out: 0.6, keys: [
    [0.35, { L: { at: 'chest', p: [0.07, -0.03, 0.22], elbow: [0.7, -0.6, -0.1], palm: IN, fing: [-0.3, 0.6, 0.6], curl: RELAX },
      R: { at: 'chest', p: [0.07, -0.03, 0.22], elbow: [0.7, -0.6, -0.1], palm: IN, fing: [-0.3, 0.6, 0.6], curl: RELAX },
      face: { happy: 0.6, surprised: 0.2 } }],
    ...beats(0.5, 0.32, 4,
      { L: { at: 'chest', p: [0.012, -0.03, 0.24], elbow: [0.7, -0.6, -0.1], palm: IN, fing: [-0.2, 0.6, 0.6], curl: RELAX },
        R: { at: 'chest', p: [0.012, -0.03, 0.24], elbow: [0.7, -0.6, -0.1], palm: IN, fing: [-0.2, 0.6, 0.6], curl: RELAX },
        face: { happy: 0.8, hx: 0.04 } },
      { L: { at: 'chest', p: [0.08, -0.03, 0.22], elbow: [0.7, -0.6, -0.1], palm: IN, fing: [-0.3, 0.6, 0.6], curl: RELAX },
        R: { at: 'chest', p: [0.08, -0.03, 0.22], elbow: [0.7, -0.6, -0.1], palm: IN, fing: [-0.3, 0.6, 0.6], curl: RELAX },
        face: { happy: 0.8 } }),
    [1.9, { L: { at: 'chest', p: [0.012, -0.03, 0.24], elbow: [0.7, -0.6, -0.1], palm: IN, fing: [-0.2, 0.6, 0.6], curl: RELAX },
      R: { at: 'chest', p: [0.012, -0.03, 0.24], elbow: [0.7, -0.6, -0.1], palm: IN, fing: [-0.2, 0.6, 0.6], curl: RELAX },
      face: { happy: 0.8 } }],
    [2.3, { L: { at: 'chest', p: [0.012, -0.05, 0.22], elbow: [0.7, -0.6, -0.1], palm: IN, fing: [-0.2, 0.6, 0.6], curl: RELAX },
      R: { at: 'chest', p: [0.012, -0.05, 0.22], elbow: [0.7, -0.6, -0.1], palm: IN, fing: [-0.2, 0.6, 0.6], curl: RELAX },
      face: { happy: 0.7, hz: 0.08 } }],
  ] },

  // *rests her chin on her hand*: right hand under her chin, left arm across
  // her middle holding the right elbow, head tipped into the hand.
  chin: { out: 0.8, keys: [
    [0.7, { torso: { spine: [0.05, 0, 0.02], chest: [0.05, 0, 0] },
      R: { at: 'face', p: [0.0, -0.13, 0.05], elbow: [0.1, -1, 0.4], palm: UP, fing: [0.25, 0.4, -0.2], curl: SOFT },
      L: { at: 'belly', p: [-0.06, 0.02, 0.15], elbow: [0.9, -0.5, 0.2], palm: UP, fing: [-1, 0, 0.2], curl: RELAX },
      face: { hz: -0.14, hx: 0.06, relaxed: 0.3 } }],
    [3.4, { torso: { spine: [0.05, 0.02, 0.03], chest: [0.05, 0, 0] },
      R: { at: 'face', p: [0.0, -0.13, 0.05], elbow: [0.1, -1, 0.4], palm: UP, fing: [0.25, 0.4, -0.2], curl: SOFT },
      L: { at: 'belly', p: [-0.06, 0.02, 0.15], elbow: [0.9, -0.5, 0.2], palm: UP, fing: [-1, 0, 0.2], curl: RELAX },
      face: { hz: -0.17, hx: 0.08, relaxed: 0.35, happy: 0.15, gazeX: 0.1 } }],
  ] },

  // *taps her chin*: finger to chin, tapping, eyes up.
  think: { out: 0.7, keys: [
    [0.6, { R: { at: 'face', p: [-0.01, -0.1, 0.07], elbow: [0.3, -1, 0.1], palm: IN, fing: [0.1, 1, 0.3], curl: POINT },
      L: { at: 'belly', p: [-0.07, 0.03, 0.14], elbow: [0.9, -0.5, 0.2], palm: UP, fing: [-1, 0, 0.2], curl: RELAX },
      face: { gazeY: 0.35, gazeX: 0.25, hz: 0.1 } }],
    ...beats(0.9, 0.5, 4,
      { R: { at: 'face', p: [-0.01, -0.09, 0.07], elbow: [0.3, -1, 0.1], palm: IN, fing: [0.1, 1, 0.3], curl: POINT },
        L: { at: 'belly', p: [-0.07, 0.03, 0.14], elbow: [0.9, -0.5, 0.2], palm: UP, fing: [-1, 0, 0.2], curl: RELAX },
        face: { gazeY: 0.35, gazeX: 0.25, hz: 0.1 } },
      { R: { at: 'face', p: [-0.01, -0.105, 0.075], elbow: [0.3, -1, 0.1], palm: IN, fing: [0.1, 1, 0.3], curl: POINT },
        L: { at: 'belly', p: [-0.07, 0.03, 0.14], elbow: [0.9, -0.5, 0.2], palm: UP, fing: [-1, 0, 0.2], curl: RELAX },
        face: { gazeY: 0.35, gazeX: 0.25, hz: 0.12 } }),
  ] },

  // *shrugs*: palms up and out, elbows in, shoulders up.
  shrug: { out: 0.6, keys: [
    [0.4, { L: { at: 'hips', p: [0.3, 0.1, 0.16], elbow: [0.3, -1, -0.3], palm: UP, fing: [0.5, 0, 1], curl: RELAX },
      R: { at: 'hips', p: [0.3, 0.1, 0.16], elbow: [0.3, -1, -0.3], palm: UP, fing: [0.5, 0, 1], curl: RELAX },
      face: { hz: 0.12, hx: 0.04, relaxed: 0.2, surprised: 0.25 } }],
    [1.2, { L: { at: 'hips', p: [0.31, 0.11, 0.16], elbow: [0.3, -1, -0.3], palm: UP, fing: [0.5, 0, 1], curl: RELAX },
      R: { at: 'hips', p: [0.31, 0.11, 0.16], elbow: [0.3, -1, -0.3], palm: UP, fing: [0.5, 0, 1], curl: RELAX },
      face: { hz: 0.14, hx: 0.05, relaxed: 0.25, surprised: 0.2 } }],
  ], run: (t, o) => { o.shoulder = 0.16 * Math.min(1, t / 0.35) * Math.max(0, Math.min(1, (1.5 - t) / 0.4)); } },

  // *reaches toward the screen*: right hand out to you, leaning in.
  reach: { out: 0.8, keys: [
    [0.7, { torso: { hips: [0.06, 0, 0], spine: [0.08, -0.06, 0], chest: [0.08, -0.04, 0] }, hips: [0, 0, -0.03],
      R: { at: 'shoulder', p: [0.03, 0.02, 0.5], elbow: [0.5, -1, 0], palm: [0, 0.1, 1], fing: [0, 1, 0.3], curl: RELAX },
      face: { hx: -0.1, happy: 0.25 } }],
    [2.0, { torso: { hips: [0.07, 0, 0], spine: [0.09, -0.06, 0], chest: [0.09, -0.04, 0] }, hips: [0, 0, -0.03],
      R: { at: 'shoulder', p: [0.05, 0.03, 0.52], elbow: [0.5, -1, 0], palm: [0, 0.1, 1], fing: [0, 1, 0.3], curl: RELAX },
      face: { hx: -0.1, hz: 0.1, happy: 0.35 } }],
  ] },

  // *points at the screen*.
  point: { out: 0.6, keys: [
    [0.5, { R: { at: 'shoulder', p: [0.1, 0.0, 0.45], elbow: [0.6, -1, 0], palm: IN, fing: [0, 0.1, 1], curl: POINT },
      face: { hx: -0.04, happy: 0.2, brow: 0.3 } }],
    [1.5, { R: { at: 'shoulder', p: [0.1, 0.01, 0.46], elbow: [0.6, -1, 0], palm: IN, fing: [0, 0.1, 1], curl: POINT },
      face: { happy: 0.25 } }],
  ] },

  // *facepalms*: palm over her eyes, head bowed.
  facepalm: { out: 0.8, keys: [
    [0.45, { torso: { chest: [0.05, 0, 0] },
      R: { at: 'face', p: [-0.01, -0.03, 0.1], elbow: [0.4, -1, 0.1], palm: BACK, fing: [0.2, 1, 0], curl: SOFT },
      face: { hx: 0.18, sad: 0.4, blink: 1 } }],
    [2.2, { torso: { chest: [0.06, 0, 0] },
      R: { at: 'face', p: [-0.01, -0.03, 0.1], elbow: [0.4, -1, 0.1], palm: BACK, fing: [0.2, 1, 0], curl: SOFT },
      face: { hx: 0.22, hy: 0.08, sad: 0.45, blink: 1 } }],
  ], run: (t, o) => { o.hy += wob(t, 1.1, 0.06) * Math.min(1, Math.max(0, t - 0.6)); } },

  // *covers her eyes*: both hands, then a peek through her fingers.
  coverEyes: { out: 0.7, keys: [
    [0.4, { L: { at: 'face', p: [0.035, -0.035, 0.1], elbow: [0.6, -1, 0.1], palm: BACK, fing: [-0.25, 1, 0], curl: RELAX },
      R: { at: 'face', p: [0.035, -0.035, 0.1], elbow: [0.6, -1, 0.1], palm: BACK, fing: [-0.25, 1, 0], curl: RELAX },
      face: { hx: 0.12, blink: 1, happy: 0.4 } }],
    [1.4, { L: { at: 'face', p: [0.035, -0.035, 0.1], elbow: [0.6, -1, 0.1], palm: BACK, fing: [-0.25, 1, 0], curl: RELAX },
      R: { at: 'face', p: [0.035, -0.035, 0.1], elbow: [0.6, -1, 0.1], palm: BACK, fing: [-0.25, 1, 0], curl: RELAX },
      face: { hx: 0.14, hy: 0.05, blink: 1, happy: 0.4 } }],
    [1.9, { L: { at: 'face', p: [0.035, -0.035, 0.1], elbow: [0.6, -1, 0.1], palm: BACK, fing: [-0.25, 1, 0], curl: RELAX },
      R: { at: 'face', p: [0.1, -0.06, 0.1], elbow: [0.6, -1, 0.1], palm: BACK, fing: [-0.1, 1, 0], curl: RELAX },
      face: { hx: 0.1, happy: 0.5 } }],
    [2.6, { L: { at: 'face', p: [0.035, -0.035, 0.1], elbow: [0.6, -1, 0.1], palm: BACK, fing: [-0.25, 1, 0], curl: RELAX },
      R: { at: 'face', p: [0.1, -0.06, 0.1], elbow: [0.6, -1, 0.1], palm: BACK, fing: [-0.1, 1, 0], curl: RELAX },
      face: { hx: 0.1, happy: 0.55 } }],
  ] },

  // *covers her mouth*: right hand over her mouth, a little startled.
  coverMouth: { out: 0.7, keys: [
    [0.35, { torso: { chest: [-0.04, 0, 0] },
      R: { at: 'face', p: [0.0, -0.1, 0.1], elbow: [0.4, -1, 0], palm: BACK, fing: [0.3, 1, 0], curl: RELAX },
      face: { hx: -0.06, surprised: 0.7 } }],
    [1.8, { R: { at: 'face', p: [0.0, -0.1, 0.1], elbow: [0.4, -1, 0], palm: BACK, fing: [0.3, 1, 0], curl: RELAX },
      face: { hx: 0.03, surprised: 0.4, happy: 0.3 } }],
  ] },

  // *rubs her eyes*: both fists, sleepy.
  rubEyes: { out: 0.8, keys: [
    [0.5, { L: { at: 'face', p: [0.03, -0.06, 0.09], elbow: [0.5, -1, 0.2], palm: BACK, fing: [-0.4, 1, 0], curl: FIST },
      R: { at: 'face', p: [0.03, -0.06, 0.09], elbow: [0.5, -1, 0.2], palm: BACK, fing: [-0.4, 1, 0], curl: FIST },
      face: { hx: 0.1, blink: 1, relaxed: 0.4 } }],
    ...beats(0.7, 0.36, 4,
      { L: { at: 'face', p: [0.045, -0.055, 0.09], elbow: [0.5, -1, 0.2], palm: BACK, fing: [-0.4, 1, 0], curl: FIST },
        R: { at: 'face', p: [0.02, -0.065, 0.09], elbow: [0.5, -1, 0.2], palm: BACK, fing: [-0.4, 1, 0], curl: FIST },
        face: { hx: 0.1, blink: 1, relaxed: 0.4 } },
      { L: { at: 'face', p: [0.02, -0.065, 0.09], elbow: [0.5, -1, 0.2], palm: BACK, fing: [-0.4, 1, 0], curl: FIST },
        R: { at: 'face', p: [0.045, -0.055, 0.09], elbow: [0.5, -1, 0.2], palm: BACK, fing: [-0.4, 1, 0], curl: FIST },
        face: { hx: 0.1, blink: 1, relaxed: 0.4 } }),
    [2.3, { face: { blink: 0.4, relaxed: 0.4 } }],
  ] },

  // *wipes a tear from her eye*.
  wipeTear: { out: 0.7, keys: [
    [0.6, { R: { at: 'face', p: [0.035, -0.06, 0.09], elbow: [0.5, -1, 0], palm: BACK, fing: [-0.6, 0.8, 0], curl: POINT },
      face: { hx: 0.08, sad: 0.35, happy: 0.3, blink: 0.5 } }],
    [1.2, { R: { at: 'face', p: [0.06, -0.055, 0.08], elbow: [0.5, -1, 0], palm: BACK, fing: [-0.6, 0.8, 0], curl: POINT },
      face: { hx: 0.08, sad: 0.3, happy: 0.35, blink: 0.4 } }],
    [1.8, { face: { happy: 0.4 } }],
  ] },

  // *crosses her arms*.
  crossArms: { out: 0.8, keys: [
    [0.6, { torso: { chest: [-0.03, 0, 0] },
      L: { at: 'chest', p: [-0.1, -0.08, 0.13], elbow: [0.7, -0.7, 0.2], palm: [0, -0.3, -1], fing: [-1, 0.15, 0], curl: SOFT },
      R: { at: 'chest', p: [-0.1, -0.05, 0.16], elbow: [0.7, -0.7, 0.3], palm: [0, -0.3, -1], fing: [-1, 0.2, 0], curl: SOFT },
      face: { hx: -0.05, hz: 0.08, angry: 0.3 } }],
    [2.8, { torso: { chest: [-0.03, 0.04, 0] },
      L: { at: 'chest', p: [-0.1, -0.08, 0.13], elbow: [0.7, -0.7, 0.2], palm: [0, -0.3, -1], fing: [-1, 0.15, 0], curl: SOFT },
      R: { at: 'chest', p: [-0.1, -0.05, 0.16], elbow: [0.7, -0.7, 0.3], palm: [0, -0.3, -1], fing: [-1, 0.2, 0], curl: SOFT },
      face: { hx: -0.05, hz: 0.1, hy: -0.1, angry: 0.35 } }],
  ] },

  // *blows a kiss*: fingers to her lips, then out to you.
  kiss: { out: 0.7, keys: [
    [0.5, { R: { at: 'face', p: [-0.01, -0.09, 0.1], elbow: [0.4, -1, 0], palm: BACK, fing: [0.1, 1, 0.1], curl: SOFT },
      face: { blink: 0.6, happy: 0.4, mouth: 0.0 } }],
    [0.9, { R: { at: 'face', p: [-0.01, -0.09, 0.1], elbow: [0.4, -1, 0], palm: BACK, fing: [0.1, 1, 0.1], curl: SOFT },
      face: { blink: 0.8, happy: 0.45 } }],
    [1.35, { R: { at: 'shoulder', p: [0.1, 0.12, 0.42], elbow: [0.6, -1, 0], palm: [0, 0.4, 1], fing: [0.2, 1, 0.3], curl: RELAX },
      face: { happy: 0.75 } }],
    [2.0, { R: { at: 'shoulder', p: [0.12, 0.1, 0.42], elbow: [0.6, -1, 0], palm: [0, 0.4, 1], fing: [0.2, 1, 0.3], curl: RELAX },
      face: { happy: 0.6 } }],
  ] },

  // *gives a thumbs up*.
  thumbsUp: { out: 0.6, keys: [
    [0.45, { R: { at: 'chest', p: [0.12, 0.0, 0.3], elbow: [0.6, -1, 0], palm: IN, fing: FWD, curl: THUMB },
      face: { happy: 0.6, hz: 0.06 } }],
    [1.6, { R: { at: 'chest', p: [0.13, 0.01, 0.31], elbow: [0.6, -1, 0], palm: IN, fing: FWD, curl: THUMB },
      face: { happy: 0.65, hz: 0.08 } }],
  ] },

  // *peace sign*.
  peace: { out: 0.6, keys: [
    [0.45, { R: { at: 'face', p: [0.12, -0.05, 0.12], elbow: [0.7, -1, 0], palm: FWD, fing: [0.2, 1, 0], curl: PEACE },
      face: { happy: 0.7, hz: -0.1 } }],
    [1.8, { R: { at: 'face', p: [0.12, -0.04, 0.12], elbow: [0.7, -1, 0], palm: FWD, fing: [0.2, 1, 0], curl: PEACE },
      face: { happy: 0.7, hz: -0.12 } }],
  ] },

  // *salutes*.
  salute: { out: 0.6, keys: [
    [0.4, { R: { at: 'face', p: [0.07, 0.06, 0.05], elbow: [1, -0.4, 0.2], palm: [0, -0.2, -1], fing: IN, curl: [0, 0, 0, 0, 0] },
      face: { happy: 0.5 } }],
    [1.4, { R: { at: 'face', p: [0.08, 0.06, 0.05], elbow: [1, -0.4, 0.2], palm: [0, -0.2, -1], fing: IN, curl: [0, 0, 0, 0, 0] },
      face: { happy: 0.55 } }],
  ] },

  // *tucks her hair behind her ear*.
  hair: { out: 0.7, keys: [
    [0.5, { R: { at: 'face', p: [0.06, -0.02, 0.06], elbow: [0.6, -1, 0.2], palm: [-1, 0, 0.3], fing: [0, 1, -0.2], curl: RELAX },
      face: { hz: -0.1, happy: 0.3 } }],
    [1.1, { R: { at: 'face', p: [0.09, 0.01, -0.03], elbow: [0.6, -1, 0.2], palm: [-1, 0, 0], fing: [0, 0.6, -1], curl: RELAX },
      face: { hz: -0.12, happy: 0.35, gazeX: -0.1 } }],
    [1.6, { R: { at: 'face', p: [0.09, -0.02, -0.03], elbow: [0.6, -1, 0.2], palm: [-1, 0, 0], fing: [0, 0.6, -1], curl: RELAX },
      face: { hz: -0.08, happy: 0.35 } }],
  ] },

  // *sips her tea*: an (invisible) mug in both hands.
  sip: { out: 0.8, keys: [
    [0.6, { R: { at: 'chest', p: [0.02, -0.02, 0.2], elbow: [0.7, -1, 0], palm: IN, fing: [-0.2, 0.3, 1], curl: CUP },
      L: { at: 'chest', p: [0.02, -0.07, 0.18], elbow: [0.7, -1, 0], palm: UP, fing: [-1, 0, 0.3], curl: SOFT },
      face: { relaxed: 0.3 } }],
    [1.2, { R: { at: 'face', p: [0.01, -0.1, 0.14], elbow: [0.6, -1, 0], palm: IN, fing: [-0.2, 0.3, 1], curl: CUP },
      L: { at: 'chest', p: [0.03, -0.04, 0.2], elbow: [0.7, -1, 0], palm: UP, fing: [-1, 0, 0.3], curl: SOFT },
      face: { hx: -0.08, blink: 0.9, relaxed: 0.5 } }],
    [2.1, { R: { at: 'face', p: [0.01, -0.1, 0.14], elbow: [0.6, -1, 0], palm: IN, fing: [-0.2, 0.3, 1], curl: CUP },
      L: { at: 'chest', p: [0.03, -0.04, 0.2], elbow: [0.7, -1, 0], palm: UP, fing: [-1, 0, 0.3], curl: SOFT },
      face: { hx: -0.08, blink: 0.9, relaxed: 0.5 } }],
    [2.7, { R: { at: 'chest', p: [0.02, -0.02, 0.2], elbow: [0.7, -1, 0], palm: IN, fing: [-0.2, 0.3, 1], curl: CUP },
      L: { at: 'chest', p: [0.02, -0.07, 0.18], elbow: [0.7, -1, 0], palm: UP, fing: [-1, 0, 0.3], curl: SOFT },
      face: { relaxed: 0.45, happy: 0.2 } }],
  ] },

  // *hugs her knees*: down into a crouch, arms round her knees, chin on top.
  hugKnees: { out: 1.2, keys: [
    [0.9, { torso: { hips: [0.35, 0, 0], spine: [0.15, 0, 0], chest: [0.1, 0, 0] }, hips: [0, -0.46, -0.08],
      L: { at: 'knee', p: [0.0, 0.0, 0.1], elbow: [0.9, 0, 0.2], palm: BACK, fing: IN, curl: SOFT },
      R: { at: 'knee', p: [0.0, 0.0, 0.1], elbow: [0.9, 0, 0.2], palm: BACK, fing: IN, curl: SOFT },
      face: { hx: -0.25, relaxed: 0.3, happy: 0.2 } }],
    [4.2, { torso: { hips: [0.36, 0, 0], spine: [0.16, 0, 0.03], chest: [0.1, 0, 0] }, hips: [0, -0.47, -0.08],
      L: { at: 'knee', p: [0.0, 0.0, 0.1], elbow: [0.9, 0, 0.2], palm: BACK, fing: IN, curl: SOFT },
      R: { at: 'knee', p: [0.0, 0.0, 0.1], elbow: [0.9, 0, 0.2], palm: BACK, fing: IN, curl: SOFT },
      face: { hx: -0.2, hz: 0.14, relaxed: 0.35, happy: 0.3 } }],
  ] },

  // *hugs herself* / *shivers*: arms wrapped round her, a shiver.
  hugSelf: { out: 0.8, keys: [
    [0.5, { torso: { chest: [0.06, 0, 0] },
      L: { at: 'chest', p: [-0.13, -0.03, 0.1], elbow: [0.6, -1, 0.3], palm: BACK, fing: [-0.3, 0.2, -1], curl: SOFT },
      R: { at: 'chest', p: [-0.12, -0.08, 0.12], elbow: [0.6, -1, 0.3], palm: BACK, fing: [-0.3, 0.2, -1], curl: SOFT },
      face: { hx: 0.06, sad: 0.3 } }],
    [2.2, { torso: { chest: [0.06, 0, 0] },
      L: { at: 'chest', p: [-0.13, -0.03, 0.1], elbow: [0.6, -1, 0.3], palm: BACK, fing: [-0.3, 0.2, -1], curl: SOFT },
      R: { at: 'chest', p: [-0.12, -0.08, 0.12], elbow: [0.6, -1, 0.3], palm: BACK, fing: [-0.3, 0.2, -1], curl: SOFT },
      face: { hx: 0.08, sad: 0.35 } }],
  ], run: (t, o) => { const s = Math.max(0, Math.min(1, (t - 0.4) * 3)) * Math.max(0, Math.min(1, (2.2 - t) * 2)); o.torso.chest[1] += wob(t, 9, 0.025) * s; o.hy += wob(t, 9, 0.03, 0.25) * s; } },

  // *hugs you*: arms open wide, then closing round you.
  hug: { out: 0.9, keys: [
    [0.6, { L: { at: 'shoulder', p: [0.42, -0.05, 0.25], elbow: [0.6, -1, -0.2], palm: [0, 0, 1], fing: [0.6, 0.3, 0.5], curl: RELAX },
      R: { at: 'shoulder', p: [0.42, -0.05, 0.25], elbow: [0.6, -1, -0.2], palm: [0, 0, 1], fing: [0.6, 0.3, 0.5], curl: RELAX },
      face: { happy: 0.7 } }],
    [1.3, { L: { at: 'shoulder', p: [0.44, -0.04, 0.26], elbow: [0.6, -1, -0.2], palm: [0, 0, 1], fing: [0.6, 0.3, 0.5], curl: RELAX },
      R: { at: 'shoulder', p: [0.44, -0.04, 0.26], elbow: [0.6, -1, -0.2], palm: [0, 0, 1], fing: [0.6, 0.3, 0.5], curl: RELAX },
      face: { happy: 0.8, hz: 0.06 } }],
    [2.0, { torso: { spine: [0.08, 0, 0], chest: [0.06, 0, 0] },
      L: { at: 'chest', p: [0.0, 0.0, 0.32], elbow: [1, -0.6, 0], palm: BACK, fing: IN, curl: SOFT },
      R: { at: 'chest', p: [0.0, 0.05, 0.34], elbow: [1, -0.6, 0], palm: BACK, fing: IN, curl: SOFT },
      face: { happy: 0.8, blink: 1, hz: 0.12 } }],
    [3.1, { torso: { spine: [0.08, 0, 0], chest: [0.06, 0, 0] },
      L: { at: 'chest', p: [0.0, 0.0, 0.32], elbow: [1, -0.6, 0], palm: BACK, fing: IN, curl: SOFT },
      R: { at: 'chest', p: [0.0, 0.05, 0.34], elbow: [1, -0.6, 0], palm: BACK, fing: IN, curl: SOFT },
      face: { happy: 0.85, blink: 1, hz: 0.14 } }],
  ] },

  // *jumps up and cheers*: both fists up and a little hop.
  cheer: { out: 0.7, keys: [
    [0.3, { hips: [0, -0.07, 0], torso: { spine: [0.06, 0, 0] },
      L: { at: 'chest', p: [0.14, -0.05, 0.15], elbow: [0.5, -1, 0], palm: IN, fing: UP, curl: FIST },
      R: { at: 'chest', p: [0.14, -0.05, 0.15], elbow: [0.5, -1, 0], palm: IN, fing: UP, curl: FIST },
      face: { happy: 0.6 } }],
    [0.6, { hips: [0, 0.09, 0],
      L: { at: 'head', p: [0.22, 0.3, 0.06], elbow: [1, -0.2, 0], palm: FWD, fing: UP, curl: FIST },
      R: { at: 'head', p: [0.22, 0.3, 0.06], elbow: [1, -0.2, 0], palm: FWD, fing: UP, curl: FIST },
      face: { happy: 1, mouth: 0.5, hx: -0.12 } }],
    [0.9, { hips: [0, -0.04, 0],
      L: { at: 'head', p: [0.22, 0.28, 0.06], elbow: [1, -0.2, 0], palm: FWD, fing: UP, curl: FIST },
      R: { at: 'head', p: [0.22, 0.28, 0.06], elbow: [1, -0.2, 0], palm: FWD, fing: UP, curl: FIST },
      face: { happy: 1, mouth: 0.4 } }],
    [1.2, { hips: [0, 0.07, 0],
      L: { at: 'head', p: [0.2, 0.32, 0.06], elbow: [1, -0.2, 0], palm: FWD, fing: UP, curl: FIST },
      R: { at: 'head', p: [0.2, 0.32, 0.06], elbow: [1, -0.2, 0], palm: FWD, fing: UP, curl: FIST },
      face: { happy: 1, mouth: 0.5, hx: -0.1 } }],
    [1.6, { hips: [0, 0, 0],
      L: { at: 'head', p: [0.24, 0.25, 0.06], elbow: [1, -0.2, 0], palm: FWD, fing: UP, curl: FIST },
      R: { at: 'head', p: [0.24, 0.25, 0.06], elbow: [1, -0.2, 0], palm: FWD, fing: UP, curl: FIST },
      face: { happy: 0.9 } }],
  ] },

  // *nudges you with her shoulder*.
  nudge: { out: 0.6, keys: [
    [0.35, { torso: { hips: [0, -0.1, 0.06], spine: [0, -0.12, 0.1], chest: [0, -0.06, 0.06] }, hips: [-0.04, 0, 0],
      face: { happy: 0.5, hz: -0.1 } }],
    [0.65, { torso: { hips: [0, 0.04, -0.03], spine: [0, 0.05, -0.04] }, hips: [0.02, 0, 0], face: { happy: 0.6 } }],
    [1.0, { torso: { hips: [0, -0.06, 0.04], spine: [0, -0.08, 0.06] }, hips: [-0.02, 0, 0], face: { happy: 0.6, hz: -0.06 } }],
  ] },

  // *fidgets*: fingers twiddling in front of her.
  fidget: { out: 0.6, keys: [
    [0.5, { L: { at: 'belly', p: [0.01, 0.0, 0.17], elbow: [0.6, -1, 0], palm: [0, 0, -1], fing: [-0.6, 0.4, 0], curl: SOFT },
      R: { at: 'belly', p: [0.01, 0.0, 0.17], elbow: [0.6, -1, 0], palm: [0, 0, -1], fing: [-0.6, 0.4, 0], curl: SOFT },
      face: { hx: 0.1, gazeY: -0.2, gazeX: 0.15, happy: 0.2 } }],
    ...beats(0.7, 0.45, 4,
      { L: { at: 'belly', p: [0.0, 0.01, 0.18], elbow: [0.6, -1, 0], palm: [0, 0, -1], fing: [-0.6, 0.4, 0], curl: CUP },
        R: { at: 'belly', p: [0.02, -0.01, 0.17], elbow: [0.6, -1, 0], palm: [0, 0, -1], fing: [-0.6, 0.4, 0], curl: SOFT },
        face: { hx: 0.1, gazeY: -0.2, gazeX: 0.15, happy: 0.2 } },
      { L: { at: 'belly', p: [0.02, -0.01, 0.17], elbow: [0.6, -1, 0], palm: [0, 0, -1], fing: [-0.6, 0.4, 0], curl: SOFT },
        R: { at: 'belly', p: [0.0, 0.01, 0.18], elbow: [0.6, -1, 0], palm: [0, 0, -1], fing: [-0.6, 0.4, 0], curl: CUP },
        face: { hx: 0.1, gazeY: -0.2, gazeX: -0.1, happy: 0.2 } }),
  ] },

  // *bows*.
  bow: { out: 0.8, keys: [
    [0.6, { torso: { hips: [0.35, 0, 0], spine: [0.12, 0, 0], chest: [0.05, 0, 0] }, hips: [0, 0, -0.08],
      L: { at: 'hips', p: [-0.02, -0.1, 0.12], elbow: [0.6, -1, 0], palm: BACK, fing: [-0.4, -1, 0], curl: RELAX },
      R: { at: 'hips', p: [-0.02, -0.12, 0.11], elbow: [0.6, -1, 0], palm: BACK, fing: [-0.4, -1, 0], curl: RELAX },
      face: { hx: 0.2, blink: 1, happy: 0.4 } }],
    [1.3, { torso: { hips: [0.35, 0, 0], spine: [0.12, 0, 0], chest: [0.05, 0, 0] }, hips: [0, 0, -0.08],
      L: { at: 'hips', p: [-0.02, -0.1, 0.12], elbow: [0.6, -1, 0], palm: BACK, fing: [-0.4, -1, 0], curl: RELAX },
      R: { at: 'hips', p: [-0.02, -0.12, 0.11], elbow: [0.6, -1, 0], palm: BACK, fing: [-0.4, -1, 0], curl: RELAX },
      face: { hx: 0.2, blink: 1, happy: 0.4 } }],
  ] },

  // *yawns*: a hand over her mouth, shoulders up.
  yawn: { out: 0.8, keys: [
    [0.6, { torso: { chest: [-0.05, 0, 0] },
      R: { at: 'face', p: [0.0, -0.1, 0.11], elbow: [0.4, -1, 0], palm: BACK, fing: [0.3, 1, 0], curl: RELAX },
      face: { hx: -0.15, blink: 1, mouth: 0.7, relaxed: 0.3 } }],
    [1.7, { torso: { chest: [-0.05, 0, 0] },
      R: { at: 'face', p: [0.0, -0.1, 0.11], elbow: [0.4, -1, 0], palm: BACK, fing: [0.3, 1, 0], curl: RELAX },
      face: { hx: -0.12, blink: 1, mouth: 0.6, relaxed: 0.3 } }],
    [2.2, { face: { blink: 0.4, relaxed: 0.4 } }],
  ], run: (t, o) => { o.shoulder = 0.1 * Math.max(0, Math.sin(Math.min(1, t / 2) * Math.PI)); } },

  // *rubs the back of her neck*, sheepish.
  rubNeck: { out: 0.7, keys: [
    [0.6, { R: { at: 'head', p: [0.05, -0.04, -0.08], elbow: [0.8, 0.1, 0.6], palm: FWD, fing: [-0.4, 0.4, -0.3], curl: RELAX },
      face: { hz: 0.1, hx: 0.06, happy: 0.35, gazeX: 0.2 } }],
    ...beats(0.8, 0.5, 3,
      { R: { at: 'head', p: [0.03, -0.04, -0.08], elbow: [0.8, 0.1, 0.6], palm: FWD, fing: [-0.4, 0.4, -0.3], curl: RELAX },
        face: { hz: 0.1, hx: 0.06, happy: 0.35, gazeX: 0.2 } },
      { R: { at: 'head', p: [0.07, -0.05, -0.08], elbow: [0.8, 0.1, 0.6], palm: FWD, fing: [-0.4, 0.4, -0.3], curl: RELAX },
        face: { hz: 0.12, hx: 0.06, happy: 0.35, gazeX: 0.2 } }),
  ] },

  // *winces*: a flinch away, shoulders up, hands half up.
  wince: { out: 0.7, keys: [
    [0.2, { torso: { spine: [-0.03, 0.06, 0], chest: [-0.04, 0.05, 0] },
      L: { at: 'chest', p: [0.14, -0.02, 0.18], elbow: [0.5, -1, 0], palm: FWD, fing: UP, curl: SOFT },
      R: { at: 'chest', p: [0.14, -0.02, 0.18], elbow: [0.5, -1, 0], palm: FWD, fing: UP, curl: SOFT },
      face: { hx: -0.06, hy: 0.14, angry: 0.5, blink: 0.7 } }],
    [1.0, { torso: { spine: [-0.03, 0.05, 0], chest: [-0.03, 0.04, 0] },
      L: { at: 'chest', p: [0.14, -0.04, 0.16], elbow: [0.5, -1, 0], palm: FWD, fing: UP, curl: SOFT },
      R: { at: 'chest', p: [0.14, -0.04, 0.16], elbow: [0.5, -1, 0], palm: FWD, fing: UP, curl: SOFT },
      face: { hy: 0.1, angry: 0.4, blink: 0.5 } }],
  ], run: (t, o) => { o.shoulder = 0.12 * Math.max(0, 1 - Math.abs(t - 0.4) / 0.8); } },

  // *waves it off*: a quick flick of the hand.
  dismiss: { out: 0.5, keys: [
    [0.3, { R: { at: 'chest', p: [0.18, 0.0, 0.2], elbow: [0.6, -1, 0], palm: FWD, fing: UP, curl: RELAX }, face: { relaxed: 0.3, happy: 0.3 } }],
    [0.55, { R: { at: 'chest', p: [0.05, 0.02, 0.22], elbow: [0.6, -1, 0], palm: [-1, 0, 0.3], fing: [-0.4, 1, 0], curl: RELAX }, face: { relaxed: 0.3, happy: 0.35 } }],
    [0.8, { R: { at: 'chest', p: [0.2, 0.0, 0.2], elbow: [0.6, -1, 0], palm: FWD, fing: UP, curl: RELAX }, face: { relaxed: 0.3, happy: 0.35 } }],
  ] },

  // *shifts her weight*: hips over to one side, one knee bent.
  shift: { out: 0.9, keys: [
    [0.8, { torso: { hips: [0, 0.06, -0.06], spine: [0, -0.03, 0.05], chest: [0, -0.02, 0.03] }, hips: [0.035, -0.012, 0],
      face: { hz: 0.05 } }],
    [2.0, { torso: { hips: [0, 0.07, -0.06], spine: [0, -0.03, 0.05], chest: [0, -0.02, 0.03] }, hips: [0.04, -0.014, 0],
      face: { hz: 0.06 } }],
  ] },

  // *laughs*: a bounce in the shoulders and chest, a lean back and in.
  laugh: { out: 0.6, keys: [
    [0.25, { torso: { spine: [-0.05, 0, 0], chest: [-0.05, 0, 0] },
      L: { at: 'belly', p: [0.06, 0.0, 0.15], elbow: [0.7, -1, 0], palm: BACK, fing: IN, curl: RELAX },
      face: { hx: -0.1, happy: 0.9, mouth: 0.35 } }],
    [1.0, { torso: { spine: [0.08, 0, 0], chest: [0.06, 0, 0] },
      L: { at: 'belly', p: [0.06, 0.0, 0.15], elbow: [0.7, -1, 0], palm: BACK, fing: IN, curl: RELAX },
      face: { hx: 0.08, happy: 0.9, mouth: 0.3 } }],
    [1.6, { torso: { spine: [0.03, 0, 0] }, face: { happy: 0.6 } }],
  ], run: (t, o) => { const s = Math.max(0, Math.min(1, (1.8 - t) * 1.5)); o.torso.chest[0] += wob(t, 4.2, 0.03) * s; o.torso.upperChest[0] += wob(t, 4.2, 0.025, 0.2) * s; o.shoulder = Math.abs(wob(t, 4.2, 0.07)) * s; } },

  // *sighs*: shoulders drop, a slump.
  sighBody: { out: 0.8, keys: [
    [0.4, { torso: { spine: [-0.03, 0, 0], chest: [-0.05, 0, 0] }, face: { hx: -0.06, relaxed: 0.2 } }],
    [1.3, { torso: { spine: [0.06, 0, 0], chest: [0.08, 0, 0], upperChest: [0.04, 0, 0] }, hips: [0, -0.01, 0], face: { hx: 0.12, sad: 0.3 } }],
  ], run: (t, o) => { o.shoulder = 0.08 * Math.max(0, Math.sin(Math.min(1, t / 0.6) * Math.PI)) - 0.08 * Math.max(0, Math.min(1, (t - 0.6) / 0.5)); } },

  // *gasps*: a small jump back, hands up near her chest.
  startle: { out: 0.6, keys: [
    [0.15, { torso: { spine: [-0.06, 0, 0], chest: [-0.06, 0, 0] }, hips: [0, 0.005, 0.02],
      L: { at: 'chest', p: [0.06, 0.02, 0.15], elbow: [0.6, -1, 0], palm: BACK, fing: UP, curl: SOFT },
      R: { at: 'chest', p: [0.06, 0.02, 0.15], elbow: [0.6, -1, 0], palm: BACK, fing: UP, curl: SOFT },
      face: { hx: -0.12, surprised: 0.9, mouth: 0.4 } }],
    [0.9, { torso: { spine: [-0.03, 0, 0], chest: [-0.03, 0, 0] },
      L: { at: 'chest', p: [0.06, 0.01, 0.15], elbow: [0.6, -1, 0], palm: BACK, fing: UP, curl: SOFT },
      R: { at: 'chest', p: [0.06, 0.01, 0.15], elbow: [0.6, -1, 0], palm: BACK, fing: UP, curl: SOFT },
      face: { surprised: 0.6 } }],
  ] },

  // Anything else she does: one hand opens, palm up, as if explaining.
  gesture: { out: 0.6, keys: [
    [0.45, { R: { at: 'belly', p: [0.18, 0.05, 0.22], elbow: [0.6, -1, -0.1], palm: [0, 1, 0.3], fing: [0.4, 0, 1], curl: RELAX },
      face: { hz: 0.06 } }],
    [1.2, { R: { at: 'belly', p: [0.2, 0.06, 0.22], elbow: [0.6, -1, -0.1], palm: [0, 1, 0.3], fing: [0.4, 0, 1], curl: RELAX },
      face: { hz: 0.08 } }],
  ] },
};

// ── How she stands ─────────────────────────────────────────────────────────
// Nobody stands with their arms hanging straight down. At rest she holds one
// of these, weight on one hip and the other knee eased, and every so often
// drifts into another: hands clasped in front, behind her back, a hand on
// her hip, holding her other arm. (Her cardigan's pockets have no opening in
// the mesh, so hands "in pockets" just sat on the hem: STANCE_POCKETS isn't used.) Clips play on
// top and hand her back to the stance when they finish.
const STANCE_EASY = {
  torso: { hips: [0, 0.05, -0.05], spine: [0.01, -0.03, 0.05], chest: [0, -0.015, 0.02] }, hips: [0.03, -0.012, 0],
  L: { at: 'hips', p: [0.16, -0.18, 0.06], elbow: [0.5, -1, -0.5], palm: [-1, 0, 0.1], fing: [0, -1, 0.12], curl: RELAX },
  R: { at: 'hips', p: [0.165, -0.17, 0.045], elbow: [0.5, -1, -0.5], palm: [-1, 0, 0.15], fing: [0, -1, 0.08], curl: RELAX },
};
const STANCE_CLASPED = {
  torso: { hips: [0, -0.03, 0.04], spine: [0.015, 0.02, -0.04], chest: [0, 0.01, -0.015] }, hips: [-0.025, -0.01, 0],
  L: { at: 'hips', p: [0.015, -0.11, 0.15], elbow: [0.7, -1, -0.3], palm: [-0.3, 0.2, -1], fing: [-0.7, -0.7, 0], curl: SOFT },
  R: { at: 'hips', p: [0.005, -0.13, 0.16], elbow: [0.7, -1, -0.3], palm: [-0.2, 0, -1], fing: [-0.8, -0.6, 0], curl: SOFT },
};
const STANCE_BEHIND = {
  torso: { hips: [0, 0.04, -0.04], spine: [-0.02, -0.02, 0.04], chest: [-0.025, 0, 0.015] }, hips: [0.025, -0.01, 0],
  L: { at: 'hips', p: [0.06, -0.06, -0.15], elbow: [0.6, -0.5, -0.6], palm: BACK, fing: IN, curl: SOFT },
  R: { at: 'hips', p: [0.05, -0.05, -0.15], elbow: [0.6, -0.5, -0.6], palm: BACK, fing: IN, curl: SOFT },
};
const STANCE_POCKETS = {
  torso: { hips: [0, -0.05, -0.05], spine: [0, 0.03, 0.05], chest: [0.01, 0.01, 0.02] }, hips: [0.03, -0.012, 0],
  L: { at: 'hips', p: [0.15, -0.01, 0.1], elbow: [0.8, -0.8, -0.4], palm: [-1, 0, 0], fing: [0, -1, 0.2], curl: CUP },
  R: { at: 'hips', p: [0.15, -0.01, 0.1], elbow: [0.8, -0.8, -0.4], palm: [-1, 0, 0], fing: [0, -1, 0.2], curl: CUP },
};
const STANCE_HIP = {
  torso: { hips: [0, 0.06, 0.06], spine: [0, -0.04, -0.06], chest: [0, -0.02, -0.02] }, hips: [0.035, -0.014, 0],
  L: { at: 'hips', p: [0.16, 0.03, 0.01], elbow: [1, -0.2, -0.4], palm: [-1, 0, 0], fing: [0.1, -0.5, 1], curl: SOFT },
  R: { at: 'hips', p: [0.19, -0.16, 0.06], elbow: [0.5, -1, -0.5], palm: [-1, 0, 0.2], fing: [0.05, -1, 0.1], curl: RELAX },
};
const STANCE_HOLD_ARM = {
  torso: { hips: [0, -0.04, -0.05], spine: [0.02, 0.03, 0.05], chest: [0.01, 0.02, 0.02] }, hips: [0.03, -0.012, 0],
  L: { at: 'hips', p: [0.1, -0.13, 0.13], elbow: [0.6, -1, -0.2], palm: [-1, 0.2, 0], fing: [-0.2, -1, 0.3], curl: RELAX },
  R: { at: 'hips', p: [-0.07, -0.05, 0.15], elbow: [0.6, -1, 0.1], palm: [-0.3, 0, -1], fing: [-1, -0.3, 0], curl: SOFT },
};

// The same stance the other way round: swap hands, the other hip.
function mirror(pose) {
  const m = { torso: {}, hips: [-pose.hips[0], pose.hips[1], pose.hips[2]], L: pose.R, R: pose.L };
  for (const [k, r] of Object.entries(pose.torso)) m.torso[k] = [r[0], -r[1], -r[2]];
  return m;
}

export const STANCES = {
  easy: STANCE_EASY, easyR: mirror(STANCE_EASY),
  clasped: STANCE_CLASPED, claspedR: mirror(STANCE_CLASPED),
  behind: STANCE_BEHIND, behindR: mirror(STANCE_BEHIND),
  hip: STANCE_HIP, hipR: mirror(STANCE_HIP),
  holdArm: STANCE_HOLD_ARM, holdArmR: mirror(STANCE_HOLD_ARM),
};
// In front of strangers (the presentation personality) she stands politely.
const POLITE = ['clasped', 'claspedR', 'easy', 'easyR', 'behind', 'behindR'];

// Clips that play while she's still standing, for the idle bag.
export const IDLE_BODY = ['shift', 'stretch', 'hair'];

// ── Player ─────────────────────────────────────────────────────────────────

const TORSO = ['hips', 'spine', 'chest', 'upperChest'];
const FINGERS = ['Thumb', 'Index', 'Middle', 'Ring', 'Little'];
const JOINTS = { Thumb: ['Metacarpal', 'Proximal', 'Distal'], other: ['Proximal', 'Intermediate', 'Distal'] };
const FACE_KEYS = ['hx', 'hy', 'hz', 'gazeX', 'gazeY', 'happy', 'sad', 'angry', 'relaxed', 'surprised', 'mouth', 'blink'];
const EXPR = new Set(['happy', 'sad', 'angry', 'relaxed', 'surprised']);

const smooth = (x) => (x <= 0 ? 0 : x >= 1 ? 1 : x * x * (3 - 2 * x));

export class BodyActions {
  constructor(THREE) {
    this.T = THREE;
    this.vrm = null;
    this.playing = [];          // { clip, t, fade, fadeT }
    this.freeze = null;         // { name, t } for tests and screenshots
    this.time = 0;
    this.stance = { cur: 'easy', next: null, s: 0, timer: 10 + Math.random() * 10 };
    this.polite = false;        // set by app.js while presenting
    this.holdStance = null;     // a stance name to stay in (tests)
    // Something else (stance.js) stands her: no resting stance here, the hips
    // and feet are left where it put them, and clips play on top of that.
    this.standing = false;
    this.fingersTouched = false;
    const V = () => new THREE.Vector3();
    this._v = Array.from({ length: 16 }, V);
    this._q = Array.from({ length: 6 }, () => new THREE.Quaternion());
    this._m = new THREE.Matrix4();
    this.frame = { out: V(), up: V(), fwd: V() };
  }

  // A clip is playing (the stance underneath doesn't count).
  get active() { return this.playing.length > 0 || !!this.freeze; }

  mount(vrm) {
    this.vrm = vrm;
    this.playing = [];
    const h = vrm.humanoid;
    const b = (n) => h?.getNormalizedBoneNode(n) || null;
    this.b = {};
    for (const n of ['hips', 'spine', 'chest', 'upperChest', 'neck', 'head',
      'leftUpperArm', 'leftLowerArm', 'leftHand', 'rightUpperArm', 'rightLowerArm', 'rightHand',
      'leftUpperLeg', 'leftLowerLeg', 'leftFoot', 'rightUpperLeg', 'rightLowerLeg', 'rightFoot']) this.b[n] = b(n);
    this.fingers = { left: {}, right: {} };
    for (const side of ['left', 'right']) {
      for (const f of FINGERS) {
        this.fingers[side][f] = (f === 'Thumb' ? JOINTS.Thumb : JOINTS.other)
          .map((j) => b(`${side}${f}${j}`)).filter(Boolean);
      }
    }
    // Where her feet and hips are at rest, in her own space, so the legs can
    // be solved back onto the same spots.
    vrm.scene.updateWorldMatrix(true, true);
    const inv = new this.T.Matrix4().copy(vrm.scene.matrixWorld).invert();
    this.rest = {};
    for (const n of ['leftFoot', 'rightFoot', 'hips']) {
      if (this.b[n]) this.rest[n] = this.b[n].getWorldPosition(new this.T.Vector3()).applyMatrix4(inv);
    }
    this.restFootQ = {};
    for (const n of ['leftFoot', 'rightFoot']) {
      if (this.b[n]) this.restFootQ[n] = this.b[n].getWorldQuaternion(new this.T.Quaternion())
        .premultiply(vrm.scene.getWorldQuaternion(new this.T.Quaternion()).invert());
    }
    this.hipsBase = this.b.hips ? this.b.hips.position.clone() : null;
  }

  play(name) {
    const clip = CLIPS[name];
    if (!clip || !this.vrm) return false;
    for (const p of this.playing) if (!p.fade) { p.fade = true; p.fadeT = 0; }
    this.playing.push({ name, clip, t: 0, fade: false, fadeT: 0 });
    return true;
  }

  stop() {
    for (const p of this.playing) if (!p.fade) { p.fade = true; p.fadeT = 0; }
  }

  // Hold one clip at one moment (tests, screenshots). null lets go.
  hold(name, t) { this.freeze = name ? { name, t } : null; }

  // Pick and blend the resting stance.
  stancePose(dt) {
    const st = this.stance;
    const allowed = this.polite ? POLITE : Object.keys(STANCES);
    if (this.holdStance) { st.cur = this.holdStance; st.next = null; }
    else {
      if (!allowed.includes(st.cur) && !st.next) st.timer = 0;
      st.timer -= dt;
      if (st.timer <= 0 && !st.next && !this.playing.length) {
        const choices = allowed.filter((n) => n !== st.cur && n.replace(/R$/, '') !== st.cur.replace(/R$/, ''));
        st.next = choices[(Math.random() * choices.length) | 0];
        st.s = 0;
      }
      if (st.next) {
        st.s += dt / 1.9;
        if (st.s >= 1) { st.cur = st.next; st.next = null; st.s = 0; st.timer = 14 + Math.random() * 22; }
      }
    }
    const a = STANCES[st.cur], b = STANCES[st.next || st.cur];
    const pose = sample({ keys: [[1, a], [2, b]], out: 1 }, 1 + Math.min(0.999, st.s));
    // Hands never hold perfectly still.
    const t = this.time;
    pose.L.sway = [Math.sin(t * 0.37) * 0.006, Math.sin(t * 0.29 + 1) * 0.007, Math.sin(t * 0.23 + 2) * 0.006];
    pose.R.sway = [Math.sin(t * 0.33 + 3) * 0.006, Math.sin(t * 0.27 + 4) * 0.007, Math.sin(t * 0.21 + 5) * 0.006];
    pose.gain = 1;
    pose.stance = true;
    return pose;
  }

  // Advance time. Fills `o` (app.js cueOut) with the face and head part.
  update(dt, o) {
    this.time += dt;
    for (let i = this.playing.length - 1; i >= 0; i--) {
      const p = this.playing[i];
      p.t += dt;
      if (p.fade) p.fadeT += dt;
      const end = lastKey(p.clip) + (p.clip.out ?? 0.7);
      if (p.t >= end || (p.fade && p.fadeT >= 0.35)) this.playing.splice(i, 1);
    }
    this.layers = [];
    if (this.freeze && CLIPS[this.freeze.name]) {
      this.layers.push({ clip: CLIPS[this.freeze.name], t: this.freeze.t, gain: 1 });
    } else {
      for (const p of this.playing) {
        this.layers.push({ clip: p.clip, t: p.t, gain: p.fade ? 1 - smooth(p.fadeT / 0.35) : 1 });
      }
    }
    const clipPoses = this.layers.map((l) => {
      const pose = sample(l.clip, l.t);
      pose.gain = l.gain;
      if (l.clip.run) l.clip.run(l.t, pose);
      return pose;
    });
    this.poses = this.vrm && (!this.standing || this.holdStance) ? [this.stancePose(dt), ...clipPoses] : clipPoses;
    for (const pose of this.poses) {
      const g = pose.gain;
      o.hx += (pose.face.hx || 0) * g;
      o.hy += (pose.face.hy || 0) * g;
      o.hz += (pose.face.hz || 0) * g;
      o.gazeX += (pose.face.gazeX || 0) * g;
      o.gazeY += (pose.face.gazeY || 0) * g;
      o.shoulder += (pose.shoulder || 0) * g;
      for (const k of EXPR) o.expr[k] = Math.max(o.expr[k] || 0, (pose.face[k] || 0) * g);
      o.mouth = Math.max(o.mouth || 0, (pose.face.mouth || 0) * g);
      o.blinkBoth = Math.max(o.blinkBoth || 0, (pose.face.blink || 0) * g);
      // Arms a clip holds don't take the resting pose underneath.
      o.lArm = Math.max(o.lArm || 0, (pose.L.w || 0) * g);
      o.rArm = Math.max(o.rArm || 0, (pose.R.w || 0) * g);
    }
  }

  // After app.js has posed the idle body: torso and hips, then hands, then legs.
  apply() {
    const vrm = this.vrm;
    if (!vrm) return;
    const poses = this.poses || [];
    const T = this.T;

    if (this.standing) {
      if (!poses.length) return;
      // Keep her feet on the spots she's standing on.
      vrm.scene.updateMatrixWorld(true);
      const inv = this._m.copy(vrm.scene.matrixWorld).invert();
      this.feetNow = this.feetNow || {};
      for (const n of ['leftFoot', 'rightFoot']) {
        if (this.b[n]) this.feetNow[n] = this.b[n].getWorldPosition(this.feetNow[n] || new T.Vector3()).applyMatrix4(inv);
      }
    } else if (this.b.hips && this.hipsBase) this.b.hips.position.copy(this.hipsBase);
    if (poses.length) {
      vrm.scene.getWorldQuaternion(this._q[0]);
      const { out, up, fwd } = this.frame;
      out.set(1, 0, 0).applyQuaternion(this._q[0]);
      up.set(0, 1, 0).applyQuaternion(this._q[0]);
      fwd.set(0, 0, 1).applyQuaternion(this._q[0]);

      for (const pose of poses) {
        const g = pose.gain;
        for (const n of TORSO) {
          const node = this.b[n];
          const r = pose.torso[n];
          if (!node || !r) continue;
          node.rotation.x += r[0] * g;
          node.rotation.y += r[1] * g;
          node.rotation.z += r[2] * g;
        }
        if (this.b.hips && this.hipsBase) {
          // The hips node's parent has no rotation of its own in a normalized
          // rig, so her frame's axes are its axes too (up to the root's turn,
          // which the rig shares).
          this.b.hips.position.x += pose.hips[0] * g;
          this.b.hips.position.y += pose.hips[1] * g;
          this.b.hips.position.z += pose.hips[2] * g;
        }
      }
      vrm.scene.updateMatrixWorld(true);

      for (const pose of poses) {
        for (const side of ['L', 'R']) {
          const hand = pose[side];
          if (!hand.w) continue;
          this.placeHand(side, hand, hand.w * pose.gain);
        }
      }
    }
    this.solveLegs();
    this.applyFingers(poses);
  }

  anchor(name, side, out) {
    const s = side === 'L' ? 'left' : 'right';
    const b = this.b;
    switch (name) {
      case 'head': return b.head.getWorldPosition(out);
      case 'face': return b.head.getWorldPosition(out)
        .addScaledVector(this.frame.up, 0.06).addScaledVector(this.frame.fwd, 0.03);
      case 'chest': return (b.upperChest || b.chest).getWorldPosition(out);
      case 'belly': return (b.spine || b.hips).getWorldPosition(out);
      case 'hips': return b.hips.getWorldPosition(out);
      case 'shoulder': return b[`${s}UpperArm`].getWorldPosition(out);
      case 'knee': return b[`${s}LowerLeg`].getWorldPosition(out);
      default: return b.hips.getWorldPosition(out);
    }
  }

  // A body-frame direction, mirrored for the right hand.
  dir(v, side, out) {
    const m = side === 'L' ? 1 : -1;
    const { out: x, up, fwd } = this.frame;
    return out.set(0, 0, 0).addScaledVector(x, v[0] * m).addScaledVector(up, v[1]).addScaledVector(fwd, v[2]);
  }

  placeHand(side, hand, weight) {
    const s = side === 'L' ? 'left' : 'right';
    const upper = this.b[`${s}UpperArm`], lower = this.b[`${s}LowerArm`], wrist = this.b[`${s}Hand`];
    if (!upper || !lower || !wrist) return;
    const [target, pole, tmp] = [this._v[0], this._v[1], this._v[2]];
    // Two anchors when a hand is between keys that hang it off different parts.
    this.anchor(hand.at, side, target).add(this.dir(hand.p, side, tmp));
    if (hand.sway) target.add(this.dir(hand.sway, side, tmp));
    if (hand.at2) {
      const t2 = this.anchor(hand.at2, side, this._v[3]).add(this.dir(hand.p2, side, tmp));
      target.lerp(t2, hand.mix);
    }
    upper.getWorldPosition(pole).add(this.dir(hand.elbow || [0.5, -1, -0.1], side, tmp).multiplyScalar(0.5));
    solveArm(this, upper, lower, wrist, target, pole, weight);

    if (hand.fing && hand.palm) {
      const fing = this.dir(hand.fing, side, this._v[4]).normalize();
      const palm = this.dir(hand.palm, side, this._v[5]);
      palm.addScaledVector(fing, -palm.dot(fing)).normalize();
      const negPalm = this._v[6].copy(palm).negate();
      if (side === 'L') {
        const z = this._v[7].crossVectors(fing, negPalm);
        this._m.makeBasis(fing, negPalm, z);
      } else {
        const x = this._v[8].copy(fing).negate();
        const z = this._v[7].crossVectors(x, negPalm);
        this._m.makeBasis(x, negPalm, z);
      }
      this._q[1].setFromRotationMatrix(this._m);
      setWorldQuat(this, wrist, this._q[1], weight * (hand.rotW ?? 1));
    }
  }

  // Feet back on the spots they rest on, knees forward, whatever the hips do.
  solveLegs() {
    const vrm = this.vrm, T = this.T;
    vrm.scene.updateMatrixWorld(true);
    const rootQ = vrm.scene.getWorldQuaternion(this._q[2]);
    const fwd = this._v[9].set(0, 0, 1).applyQuaternion(rootQ);
    for (const s of ['left', 'right']) {
      const up = this.b[`${s}UpperLeg`], low = this.b[`${s}LowerLeg`], foot = this.b[`${s}Foot`];
      const rest = (this.standing && this.feetNow?.[`${s}Foot`]) || this.rest[`${s}Foot`];
      if (!up || !low || !foot || !rest) continue;
      const target = this._v[10].copy(rest).applyMatrix4(vrm.scene.matrixWorld);
      const hip = up.getWorldPosition(this._v[11]);
      const knee = low.getWorldPosition(this._v[12]);
      const ankle = foot.getWorldPosition(this._v[13]);
      // Already there (standing still): leave the leg alone.
      if (ankle.distanceToSquared(target) < 1e-8) continue;
      // Knees go the way they already point, forward of the hip-ankle line.
      const pole = this._v[14].copy(hip).lerp(target, 0.5).addScaledVector(fwd, 0.6);
      pole.add(knee.sub(hip).multiplyScalar(0.0));
      // (Standing via stance.js the foot keeps its own turn and heel.)
      const keep = this.standing ? foot.getWorldQuaternion(new T.Quaternion()) : null;
      solveArm(this, up, low, foot, target, pole, 1);
      const fq = keep || this._q[3].copy(rootQ).multiply(this.restFootQ[`${s}Foot`]);
      setWorldQuat(this, foot, fq, 1);
    }
  }

  applyFingers(poses) {
    let any = false;
    const curl = { L: [0, 0, 0, 0, 0], R: [0, 0, 0, 0, 0] };
    for (const pose of poses) {
      for (const side of ['L', 'R']) {
        const h = pose[side];
        if (!h.w || !h.curl) continue;
        any = true;
        const w = h.w * pose.gain;
        for (let i = 0; i < 5; i++) curl[side][i] += h.curl[i] * w;
      }
    }
    if (!any && !this.fingersTouched) return;
    this.fingersTouched = any;
    for (const side of ['L', 'R']) {
      const s = side === 'L' ? 'left' : 'right';
      const m = side === 'L' ? -1 : 1;
      FINGERS.forEach((f, i) => {
        const c = curl[side][i];
        const joints = this.fingers[s][f];
        joints.forEach((node, j) => {
          if (f === 'Thumb') {
            // The thumb folds across the palm, about its own forward axis.
            const a = [0.35, 0.45, 0.55][j] * c;
            node.rotation.set(0, -m * a * 1.2, m * a * 0.4);
          } else {
            const a = [1.25, 1.45, 0.95][j] * c;
            node.rotation.set(0, 0, m * a);
          }
        });
      });
    }
  }
}

function lastKey(clip) { return clip.keys[clip.keys.length - 1][0]; }

function emptyPose() {
  return {
    torso: { hips: [0, 0, 0], spine: [0, 0, 0], chest: [0, 0, 0], upperChest: [0, 0, 0] },
    hips: [0, 0, 0], face: {}, shoulder: 0, hx: 0, hy: 0, L: { w: 0 }, R: { w: 0 },
  };
}

// The pose a clip has at time t: between its two nearest keys, eased, and
// to and from idle before its first key and after its last.
function sample(clip, t) {
  const keys = clip.keys;
  const out = emptyPose();
  let a = null, b = null, s = 0;
  if (t <= keys[0][0]) {
    b = keys[0][1];
    s = smooth(t / keys[0][0]);
  } else if (t >= lastKey(clip)) {
    a = keys[keys.length - 1][1];
    s = smooth((t - lastKey(clip)) / (clip.out ?? 0.7));
  } else {
    for (let i = 0; i < keys.length - 1; i++) {
      if (t >= keys[i][0] && t < keys[i + 1][0]) {
        a = keys[i][1]; b = keys[i + 1][1];
        s = smooth((t - keys[i][0]) / (keys[i + 1][0] - keys[i][0]));
        break;
      }
    }
  }
  const mix = (x, y) => x * (1 - s) + y * s;
  for (const n of TORSO) {
    const ra = a?.torso?.[n] || [0, 0, 0], rb = b?.torso?.[n] || [0, 0, 0];
    out.torso[n] = [mix(ra[0], rb[0]), mix(ra[1], rb[1]), mix(ra[2], rb[2])];
  }
  const ha = a?.hips || [0, 0, 0], hb = b?.hips || [0, 0, 0];
  out.hips = [mix(ha[0], hb[0]), mix(ha[1], hb[1]), mix(ha[2], hb[2])];
  for (const k of FACE_KEYS) out.face[k] = mix(a?.face?.[k] || 0, b?.face?.[k] || 0);
  out.hx = out.face.hx; out.hy = out.face.hy;
  for (const side of ['L', 'R']) {
    const A = a?.[side], B = b?.[side];
    if (!A && !B) continue;
    const from = A || B, to = B || A;
    const w = A && B ? 1 : A ? 1 - s : s;
    const h = {
      w, at: from.at, p: from.p, elbow: lerp3(from.elbow, to.elbow, A && B ? s : 0),
      fing: from.fing && to.fing ? lerp3(from.fing, to.fing, A && B ? s : 0) : null,
      palm: from.palm && to.palm ? lerp3(from.palm, to.palm, A && B ? s : 0) : null,
      curl: lerpN(from.curl || RELAX, to.curl || RELAX, A && B ? s : 0),
    };
    if (A && B) {
      if (from.at === to.at) h.p = lerp3(from.p, to.p, s);
      else { h.at2 = to.at; h.p2 = to.p; h.mix = s; }
    }
    out[side] = h;
  }
  // Face keys feed app.js through update(); run() may add to these.
  out.face.hx = out.face.hx || 0;
  return new Proxy(out, {
    get(target, prop) {
      if (prop === 'hx' || prop === 'hy') return target.face[prop];
      return target[prop];
    },
    set(target, prop, value) {
      if (prop === 'hx' || prop === 'hy') target.face[prop] = value;
      else target[prop] = value;
      return true;
    },
  });
}

function lerp3(a, b, s) {
  if (!a) return b; if (!b) return a;
  return [a[0] + (b[0] - a[0]) * s, a[1] + (b[1] - a[1]) * s, a[2] + (b[2] - a[2]) * s];
}
function lerpN(a, b, s) { return a.map((x, i) => x + (b[i] - x) * s); }

// ── IK, the same method app.js uses for the wave ───────────────────────────
function setWorldQuat(self, node, worldQuat, weight) {
  const qp = self._q[4], q = self._q[5];
  node.parent.getWorldQuaternion(qp);
  q.copy(qp).invert().multiply(worldQuat);
  node.quaternion.slerp(q, weight);
  node.updateMatrixWorld(true);
}

function aimBone(self, node, child, target, weight) {
  const a = node.getWorldPosition(new self.T.Vector3());
  const b = child.getWorldPosition(new self.T.Vector3());
  const d = b.sub(a).normalize();
  const v = target.clone().sub(a).normalize();
  const q = new self.T.Quaternion().setFromUnitVectors(d, v);
  const w = node.getWorldQuaternion(new self.T.Quaternion()).premultiply(q);
  setWorldQuat(self, node, w, weight);
}

function solveArm(self, upper, lower, end, target, pole, weight) {
  const T = self.T;
  const A = upper.getWorldPosition(new T.Vector3());
  const B = lower.getWorldPosition(new T.Vector3());
  const C = end.getWorldPosition(new T.Vector3());
  const l1 = A.distanceTo(B), l2 = B.distanceTo(C);
  const D = target.clone().sub(A);
  const d = Math.max(0.01, Math.min(D.length(), (l1 + l2) * 0.999));
  D.normalize();
  const along = (l1 * l1 - l2 * l2 + d * d) / (2 * d);
  const off = Math.sqrt(Math.max(0, l1 * l1 - along * along));
  const P = pole.clone().sub(A);
  P.addScaledVector(D, -P.dot(D)).normalize();
  const E = A.clone().addScaledVector(D, along).addScaledVector(P, off);
  const Tg = A.clone().addScaledVector(D, d);
  aimBone(self, upper, lower, E, weight);
  aimBone(self, lower, end, Tg, weight);
}

// Shared with stance.js and collide.js.
export { setWorldQuat, aimBone, solveArm };
