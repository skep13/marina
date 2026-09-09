"""Let Marina look at a screenshot.

The chat model is text-only, so this uses a separate vision model over the same
OpenAI-compatible endpoint. Ollama swaps models in and out as needed, which
costs a few seconds on the first look but keeps memory bounded.

Screenshots are held in memory and passed straight to the model — nothing is
written to disk here.
"""
import base64

from openai import OpenAI

from process.config import load_config

_config = load_config()
_vision = _config.get("vision") or {}
_llm = _config.get("llm") or {}

ENABLED = bool(_vision.get("enabled", True))
MODEL = _vision.get("model", "qwen2.5vl:3b")
MAX_TOKENS = int(_vision.get("max_tokens", 300))

# Vision models charge tokens by pixel area — qwen2.5-VL is roughly one token
# per 28x28 patch. A raw Retina screenshot is ~6,500 tokens and blows a 4,096
# context on its own, so the long edge is clamped here rather than trusting the
# caller to have done it. 1024px keeps a screenshot near ~800 tokens while
# still leaving UI text readable.
MAX_EDGE = int(_vision.get("max_edge", 1024))

DEFAULT_QUESTION = "What is on my screen right now?"

# Kept deliberately terse: the answer is going to be spoken aloud, and a vision
# model left unguided will narrate every pixel.
SYSTEM = """You are looking at a screenshot of the user's screen.

Answer their question about it in one to three short sentences, in a casual
spoken register — your reply is read aloud by a text-to-speech voice.

Describe only what is actually visible. Never guess at content you cannot see,
and say so plainly if the screen is unclear. No markdown, no lists, no emoji.
If you notice something sensitive like a password or private message, say that
you would rather not read it out."""


class VisionError(RuntimeError):
    pass


_client = None


# The vision model is a second llama-server rather than the chat one — a
# projector has to be loaded alongside the weights, and the chat model is not
# going to be evicted every time she glances at the screen. Falls back to the
# chat endpoint so an Ollama setup, which swaps models itself, still works
# with nothing configured.
BASE_URL = (_vision.get("base_url") or _llm.get("base_url") or "").strip() or None
API_KEY = _vision.get("api_key") or _llm.get("api_key") or "not-needed"


def client():
    global _client
    if _client is None:
        _client = OpenAI(api_key=API_KEY, base_url=BASE_URL, timeout=90.0)
    return _client


def describe_endpoint():
    return BASE_URL or "https://api.openai.com/v1"


def _shrink(image_bytes):
    """Clamp the long edge so the image can't overflow the model's context."""
    try:
        import io

        from PIL import Image
    except ImportError:
        return image_bytes, "image/jpeg"

    try:
        img = Image.open(io.BytesIO(image_bytes))
        img.load()
    except Exception:
        return image_bytes, "image/jpeg"

    if max(img.size) > MAX_EDGE:
        scale = MAX_EDGE / max(img.size)
        img = img.resize(
            (max(1, int(img.width * scale)), max(1, int(img.height * scale))),
            Image.LANCZOS,
        )

    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=78)
    return buf.getvalue(), "image/jpeg"


def describe(image_bytes, question=None, mime="image/png"):
    """Return a spoken-style answer about the screenshot."""
    if not ENABLED:
        raise VisionError("Screen vision is disabled in character_config.yaml.")
    if not image_bytes:
        raise VisionError("No screenshot was captured.")

    image_bytes, mime = _shrink(image_bytes)
    b64 = base64.b64encode(image_bytes).decode("ascii")
    question = (question or "").strip() or DEFAULT_QUESTION

    try:
        completion = client().chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": SYSTEM},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": question},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{mime};base64,{b64}"},
                        },
                    ],
                },
            ],
            temperature=0.4,
            max_tokens=MAX_TOKENS,
            stream=False,
        )
    except Exception as e:
        msg = str(e)
        if "context size" in msg or "exceed_context" in msg:
            raise VisionError(
                "The screenshot was too large for the model's context. "
                "Lower vision.max_edge in character_config.yaml."
            ) from e
        if "not found" in msg or "404" in msg:
            raise VisionError(
                f"Vision model '{MODEL}' isn't installed. Run: ollama pull {MODEL}"
            ) from e
        raise VisionError(f"Vision call failed: {type(e).__name__}: {msg[:200]}") from e

    return (completion.choices[0].message.content or "").strip()
