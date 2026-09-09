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
    ("think",     r"\bpaus(e|es|ing)\b|\btrails?\s+off\b"),
    ("emote",     r"\bsnap(s|ping)?\b|\bwav(e|es|ing)\b|\bgestur(e|es|ing)\b"),
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


# Words that look like verbs but are almost always emphasis, not action.
# The -ing ones matter most: *nothing*, *everything* would otherwise be read
# as stage directions and silently dropped from her speech.
_NOT_ACTION = {
    "yes", "no", "this", "that", "these", "those", "his", "hers", "theirs",
    "its", "us", "was", "is", "as", "less", "plus", "always", "perhaps",
    "nothing", "everything", "anything", "something", "everyone", "anyone",
    "someone", "please", "really", "actually", "very", "just", "never",
    "ever", "all", "none", "obviously", "literally", "definitely",
}

# Third person, gerund or past tense — what a stage direction opens with.
_VERBISH = re.compile(r"^[a-z]+(?:s|es|ing|ed)$", re.I)


def _is_action(inner, kind):
    """Decide whether a delimited span is a stage direction or just emphasis.

    A cue match settles it. Otherwise the tell is grammatical, not length: a
    stage direction opens with a verb ("snaps", "walks off slowly"), emphasis
    does not ("so annoying", "that").

    Length was the old rule and it failed both ways — it spoke a one-word
    "*snaps*" out loud as if it were emphasis, and swallowed a two-word
    "*so annoying*" as if it were an action.
    """
    if classify(inner) != "emote":
        return True
    if kind == "bracket":
        return True            # brackets are never dialogue
    if kind == "paren":
        return False           # parentheses usually are dialogue

    words = inner.split()
    if not words:
        return False
    first = words[0].strip(".,!?;:'\"").lower()
    if first in _NOT_ACTION:
        return False
    return bool(_VERBISH.match(first))


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


# ---------------------------------------------------------------------------
#  Streaming segmentation
#
#  Streaming exists to get the first word out early, and the only way to do
#  that is to synthesize a sentence at a time instead of waiting for the whole
#  reply. Cutting a token stream into sentences is where that gets awkward:
#
#    - A cut inside *tilts her head* leaves a lone asterisk on each side, so
#      both halves get read out loud as emphasis instead of performed.
#    - "3.5" and "Mr." are not sentence ends.
#    - A three-character first segment technically streams sooner, but Kokoro
#      gives every segment its own intonation contour, so a run of fragments
#      reads as someone reading a list.
#
#  So: never cut inside an open delimiter, never cut a decimal, and hold a
#  minimum length — a short one for the opening segment, where latency is the
#  whole point, and a longer one after, where prosody is.
# ---------------------------------------------------------------------------

# The opening segment is what the user is waiting on, so it goes out small.
FIRST_MIN_CHARS = 12
# After that, nothing is waiting: prefer whole thoughts over more round trips.
LATER_MIN_CHARS = 70
# Beyond this, cut at the next comma or space rather than hold the audio back
# for a model that has forgotten how to end a sentence.
MAX_CHARS = 320

_SENTENCE_END = re.compile(r"[.!?…]['\")\]]*(\s|$)|[\n]+")
_SOFT_BREAK = re.compile(r"[,;:—–]\s|\s")

# Openers whose closer we must wait for before cutting.
_PAIRS = {"(": ")", "[": "]"}


def _open_spans(text):
    """True while a delimiter is open, so a cut here would orphan a marker."""
    if text.count("```") % 2:
        return True
    # Asterisks: an odd count means a span is still open. Bold is two of them,
    # which stays even, so a single counter handles both.
    if text.count("*") % 2:
        return True
    for opener, closer in _PAIRS.items():
        if text.count(opener) > text.count(closer):
            return True
    return False


def _decimal_point(text, index):
    """A '.' between two digits ends a number, not a sentence."""
    if text[index] != ".":
        return False
    before = text[index - 1] if index else ""
    after = text[index + 1] if index + 1 < len(text) else ""
    return before.isdigit() and after.isdigit()


class SentenceSplitter:
    """Accumulates streamed deltas and hands back speakable segments.

    `feed` returns zero or more complete segments; `flush` returns whatever is
    left at the end of the stream. Segments are raw reply text — run each one
    through `split_reply` to get its speech and cues.
    """

    def __init__(self, first_min=FIRST_MIN_CHARS, later_min=LATER_MIN_CHARS):
        self._buf = ""
        self._first_min = first_min
        self._later_min = later_min
        self._emitted = 0

    @property
    def minimum(self):
        return self._first_min if self._emitted == 0 else self._later_min

    def feed(self, delta):
        self._buf += delta or ""
        out = []
        while True:
            cut = self._find_cut()
            if cut is None:
                break
            segment, self._buf = self._buf[:cut].strip(), self._buf[cut:].lstrip()
            if segment:
                out.append(segment)
                self._emitted += 1
        return out

    def _find_cut(self):
        buf = self._buf
        minimum = self.minimum

        for match in _SENTENCE_END.finditer(buf):
            end = match.end()
            if end < minimum:
                continue
            # A match that runs to the end of the buffer has not been read in
            # full yet. Deltas can be a single character, and "3." looks
            # exactly like the end of a sentence right up until the "5"
            # arrives. One more character settles it, and there is always
            # another one coming — or `flush` takes it.
            if end >= len(buf):
                continue
            if _decimal_point(buf, match.start()):
                continue
            if _open_spans(buf[:end]):
                continue
            return end

        # A model that runs on without punctuation would otherwise hold the
        # whole reply back to the end, which is the exact failure streaming is
        # here to fix. Past MAX_CHARS, take the last safe soft break instead.
        if len(buf) >= MAX_CHARS:
            last = None
            for match in _SOFT_BREAK.finditer(buf):
                if match.end() < minimum:
                    continue
                if match.end() > MAX_CHARS:
                    break
                if _open_spans(buf[:match.end()]):
                    continue
                last = match.end()
            if last:
                return last
        return None

    def flush(self):
        segment, self._buf = self._buf.strip(), ""
        if segment:
            self._emitted += 1
        return segment or None
