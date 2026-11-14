"""Small things she has to keep between replies that aren't memories: her
mood, what she has already asked about, how they seemed a minute ago.

Like her memory, they live on the home bridge when there is one (see
process.shared), so the desktop and Telegram agree; otherwise, or when the
home can't be reached, in state.json next to her memory.
"""
import json
import threading
import time

from process import shared
from process.config import resolve_data

CACHE_SECONDS = 5.0   # her face asks for her mood on every sentence

_lock = threading.Lock()
_cache = {}           # key -> (read at, value)


def _path():
    return resolve_data("state.json")


def _load():
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def local_get(key, default=None):
    with _lock:
        return _load().get(key, default)


def local_put(key, value):
    with _lock:
        data = _load()
        data[key] = value
        try:
            tmp = _path().with_suffix(".json.tmp")
            tmp.write_text(json.dumps(data), encoding="utf-8")
            tmp.replace(_path())
        except OSError:
            pass
    return value


def get(key, default=None):
    now = time.time()
    hit = _cache.get(key)
    if hit and now - hit[0] < CACHE_SECONDS:
        return hit[1] if hit[1] is not None else default
    value = None
    if shared.enabled():
        out = shared.call("GET", f"/shared/state/{key}")
        if isinstance(out, dict) and "value" in out:
            value = out["value"]
            if value is not None:
                local_put(key, value)   # the copy used if the home is down
        else:
            value = local_get(key)
    else:
        value = local_get(key)
    _cache[key] = (now, value)
    return value if value is not None else default


_rehearsal = threading.local()


class rehearsal:
    """While this is open on a thread, nothing she does there is kept: no
    mood, no memories, no counting. For trying her out (the "marina-test"
    model) without the try-out becoming part of her."""

    def __enter__(self):
        _rehearsal.on = True

    def __exit__(self, *exc):
        _rehearsal.on = False


def rehearsing():
    return bool(getattr(_rehearsal, "on", False))


def put(key, value):
    if rehearsing():
        return value
    _cache[key] = (time.time(), value)
    if shared.enabled():
        shared.call("POST", f"/shared/state/{key}", {"value": value})
    return local_put(key, value)


def forget():
    """Drop what has been read, for tests."""
    _cache.clear()
