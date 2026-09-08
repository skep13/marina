"""Which brain she's using.

Two are available: `server` (the GPU box) and `local` (this Mac). Switching
between them changes only where inference happens — her conversation history
and long-term memory always live here on the Mac, in one place, and are never
stored on the server.

Mode:
  auto    prefer the server, fall back to local when it is unreachable
  server  server only; report an error rather than quietly falling back
  local   local only; nothing leaves this Mac
"""
import threading

from process.config import load_config

_config = load_config()
_llm = _config.get("llm") or {}

VALID = ("auto", "server", "local")

_lock = threading.Lock()
_mode = (_llm.get("mode") or "auto").strip().lower()
if _mode not in VALID:
    _mode = "auto"

# Set by the LLM layer when a call actually lands somewhere, so `current()`
# reports reality rather than intent.
_last_used = "local" if _mode == "local" else "server"

# Chosen model per backend. Defaults come from the config; the UI can override
# either at runtime without restarting.
_models = {
    "server": _llm.get("model"),
    "local": _llm.get("fallback_model") or _llm.get("model"),
}


def mode():
    return _mode


def set_mode(new):
    """Switch backend. Returns the mode actually set."""
    global _mode, _last_used
    new = (new or "").strip().lower()
    if new not in VALID:
        raise ValueError(f"mode must be one of {', '.join(VALID)}")
    with _lock:
        _mode = new
        if new != "auto":
            _last_used = new
    return _mode


def note_used(which):
    """Called after a successful call, with 'server' or 'local'."""
    global _last_used
    if which in ("server", "local"):
        _last_used = which


def model_for(which=None):
    """The model name selected for a backend."""
    return _models.get(which or current())


def set_model(which, name):
    """Pin a model for one backend."""
    which = (which or "").strip().lower()
    if which not in ("server", "local"):
        raise ValueError("backend must be 'server' or 'local'")
    if not name or not str(name).strip():
        raise ValueError("model name required")
    with _lock:
        _models[which] = str(name).strip()
    return _models[which]


def models():
    return dict(_models)


def current():
    """The backend actually in use right now."""
    return _last_used if _mode == "auto" else _mode


def describe():
    cur = current()
    return cur + (" (auto)" if _mode == "auto" else "")
