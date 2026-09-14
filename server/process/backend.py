"""Which LLM backend to use.

  auto    the server, falling back to local if it can't be reached
  server  the server only
  local   this Mac only
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

_last_used = "local" if _mode == "local" else "server"

_models = {
    "server": _llm.get("model"),
    "local": _llm.get("fallback_model") or _llm.get("model"),
}


def mode():
    return _mode


def set_mode(new):
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
    global _last_used
    if which in ("server", "local"):
        _last_used = which


def model_for(which=None):
    return _models.get(which or current())


def set_model(which, name):
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
    return _last_used if _mode == "auto" else _mode


def describe():
    cur = current()
    return cur + (" (auto)" if _mode == "auto" else "")
