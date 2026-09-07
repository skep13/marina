"""Split an LLM reply into what gets spoken and what gets performed.

Small local models narrate: they emit markdown, emoji, and roleplay actions
like *tilts head*. Fed straight to TTS, all of that gets read out loud —
"asterisk tilts head asterisk". This module pulls the reply apart into:

  display - the original text, for the speech bubble
  speech  - clean prose for the TTS engine
  cues    - the actions, mapped to animations and positioned in the audio

Cue positions are recorded as a character offset into `speech`, so the frontend
can fire each one at roughly the moment it would have been spoken rather than
dumping them all at the start.
"""
import re

# ---------------------------------------------------------------------------
#  Action -> animation mapping
#
#  Only the head and shoulders are on screen, so every gesture is a head or
#  face movement. Order matters: the first pattern that matches wins, so more
#  specific phrases come first.
# ---------------------------------------------------------------------------

CUE_PATTERNS = [
    ("eyeroll",   r"\broll(s|ing)?\s+(her\s+|his\s+|their\s+)?eyes\b|\beyeroll\b"),
    ("shake",     r"\bshak(e|es|ing)\s+(her\s+|his\s+|their\s+)?head\b|\bshakes\b"),
    ("nod",       r"\bnod(s|ding)?\b"),
    ("tilt",      r"\btilt(s|ing)?\b|\bcocks?\s+(her|his|their)?\s*head\b"),
    ("shrug",     r"\bshrug(s|ging)?\b"),
    ("lean",      r"\blean(s|ing)?\b"),
    ("wink",      r"\bwink(s|ing)?\b"),
    ("laugh",     r"\blaugh(s|ing)?\b|\bgiggl(e|es|ing)\b|\bchuckl(e|es|ing)\b|\bsnicker(s|ing)?\b|\bsnort(s|ing)?\b"),
    ("blush",     r"\bblush(es|ing)?\b|\bflustered\b|\bembarrassed\b"),
    ("sigh",      r"\bsigh(s|ing)?\b|\bgroan(s|ing)?\b|\bhuff(s|ing)?\b|\bexhal(e|es|ing)\b"),
    ("pout",      r"\bpout(s|ing)?\b|\bfrown(s|ing)?\b|\bscowl(s|ing)?\b|\bglar(e|es|ing)\b|\bglow(er|ers|ering)\b"),
    ("surprised", r"\bgasp(s|ing)?\b|\bblink(s|ing)?\s+in\s+surprise\b|\bstartled\b|\bjolt(s|ing)?\b"),
    ("smile",     r"\bsmil(e|es|ing)\b|\bgrin(s|ning)?\b|\bsmirk(s|ing)?\b|\bbeam(s|ing)?\b"),
    ("sad",       r"\bfrowns?\s+sadly\b|\blooks?\s+(down|away)\b|\bwilts?\b|\bdroop(s|ing)?\b"),
    ("think",     r"\bthink(s|ing)?\b|\bponder(s|ing)?\b|\bconsider(s|ing)?\b|\bhums?\b"),
    ("brow",      r"\b(rais|arch|quirk|lift)(e[sd]|ing)?\s+(an?\s+|her\s+|his\s+|their\s+)?(eye)?brow"),
    ("stare",     r"\bstar(e|es|ing)\b|\bglanc(e|es|ing)\b|\bpeer(s|ing)?\b|\bsquint(s|ing)?\b"),
    ("yawn",      r"\byawn(s|ing)?\b|\bstretch(es|ing)?\b"),
]

_COMPILED = [(name, re.compile(pat, re.I)) for name, pat in CUE_PATTERNS]

# Emoji and pictographs. TTS reads these as their unicode names or skips them
# unpredictably; either way they don't belong in speech.
_EMOJI = re.compile(
    "["
    "\U0001F300-\U0001FAFF"
    "\U00002600-\U000027BF"
    "\U0001F1E6-\U0001F1FF"
    "\U00002190-\U000021FF"
    "\U0000FE00-\U0000FE0F"
    "\U00002B00-\U00002BFF"
    "]+",
    flags=re.UNICODE,
)

_FENCE = re.compile(r"```.*?```", re.S)
_INLINE_CODE = re.compile(r"`([^`]*)`")
_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_BULLET = re.compile(r"^\s*[-*+]\s+", re.M)
_HEADING = re.compile(r"^\s*#{1,6}\s*", re.M)
_QUOTE = re.compile(r"^\s*>\s*", re.M)
_WS = re.compile(r"\s+")

# Every delimiter a model might wrap a stage direction in, in priority order.
# The last alternative catches an asterisk that is never closed — models drop
# the trailing one often, and without this the action gets read out loud.
_SPAN = re.compile(
    r"\*\*(?P<bold>[^\n]+?)\*\*"
    r"|\*(?P<italic>[^*\n]+?)\*"
    r"|\((?P<paren>[^)\n]{1,80})\)"
    r"|\[(?P<bracket>[^\]\n]{1,80})\]"
    r"|\*(?P<unclosed>[^\n]+)",
    re.M,
)

# Anything left over that TTS would pronounce as a symbol name.
_RESIDUAL = str.maketrans({c: " " for c in "*_#`~<>|"})


def classify(action):
    """Map an action phrase to an animation name."""
    for name, pattern in _COMPILED:
        if pattern.search(action):
            return name
    return "emote"


def _is_action(inner, kind):
    """Decide whether a delimited span is a stage direction or just emphasis.

    A cue match settles it. Otherwise the tell is length: stage directions are
    phrases ("walks off slowly"), emphasis is usually a single word ("*that*"),
    and removing an emphasised word would put a hole in the sentence.
    """
    if classify(inner) != "emote":
        return True
    if kind == "bracket":
        return True            # brackets are never dialogue
    if kind == "paren":
        return False           # parentheses usually are dialogue
    return len(inner.split()) >= 2


def split_reply(text):
    """Return {display, speech, cues} for an LLM reply."""
    display = (text or "").strip()

    if not display:
        return {"display": "", "speech": "", "cues": []}

    body = _FENCE.sub(" ", display)
    body = _INLINE_CODE.sub(r"\1", body)
    body = _LINK.sub(r"\1", body)
    body = _BULLET.sub("", body)
    body = _HEADING.sub("", body)
    body = _QUOTE.sub("", body)

    speech_parts = []
    cues = []
    cursor = 0
    length = 0

    for match in _SPAN.finditer(body):
        kind = match.lastgroup
        inner = _WS.sub(" ", match.group(kind) or "").strip()
        if not inner:
            continue

        before = body[cursor:match.start()]
        speech_parts.append(before)
        length += len(before)
        cursor = match.end()

        if _is_action(inner, kind):
            cues.append({
                "action": inner,
                "animation": classify(inner),
                "at": length,          # char offset into the spoken text
            })
        else:
            # Emphasis, not an action — keep the words, drop the markers.
            speech_parts.append(inner)
            length += len(inner)

    speech_parts.append(body[cursor:])
    speech = "".join(speech_parts)

    speech = _EMOJI.sub(" ", speech)
    speech = speech.translate(_RESIDUAL)
    speech = _WS.sub(" ", speech).strip()

    # Tidy punctuation left stranded by a removed action.
    speech = re.sub(r"\s+([,.!?;:])", r"\1", speech)
    speech = re.sub(r"([,.!?;:])\1+", r"\1", speech)
    speech = re.sub(r"^[\s,.;:]+", "", speech)

    total = max(len(speech), 1)
    for cue in cues:
        cue["fraction"] = min(1.0, max(0.0, cue["at"] / total))

    # What the speech bubble shows. Normally just the spoken words — the
    # actions are performed, so printing them too is redundant. A reply that is
    # nothing BUT actions would otherwise leave the bubble empty, so fall back
    # to the action text with the markers stripped. Never the raw string.
    if speech:
        shown = speech
    elif cues:
        shown = " ".join(c["action"] for c in cues).strip()
    else:
        shown = _WS.sub(" ", display.translate(_RESIDUAL)).strip()

    return {"display": shown, "speech": speech, "cues": cues}
