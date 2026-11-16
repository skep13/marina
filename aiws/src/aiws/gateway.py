"""One OpenAI-compatible endpoint in front of every model, local or remote.

* auth: a per-client token (`ai token new`), sent as a Bearer key;
* routing: `model` may be a served name, `name@profile` or a role
  (`ai:code`); the project in `X-AIWS-Project` (or the active project)
  picks which model a role means;
* priority: requests marked `X-AIWS-Priority: background` wait while an
  interactive one is running, so a batch job never delays typing.
"""
import asyncio
import json
import time

import httpx
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from aiws import config, models, projects, store

_client = httpx.AsyncClient(timeout=httpx.Timeout(900, connect=5))
_interactive = 0
_idle = asyncio.Event()
_idle.set()
BACKGROUND_MAX_WAIT = 300
_stats = []  # recent request timings for the control centre


def _target(m, served):
    if m.get("runtime") == "remote":
        key = models.secret(m["key_env"]) if m.get("key_env") else ""
        return m["base_url"].rstrip("/"), m.get("remote_model", served), key
    return config.LLAMA_SWAP_URL, served, ""


async def proxy(request: Request, path: str, client: dict):
    body = await request.json() if request.method == "POST" else {}
    proj = request.headers.get("x-aiws-project") or store.get("active_project")
    requested = body.get("model")
    m, served = models.resolve(requested, projects.roles_for(proj))
    if not m:
        raise HTTPException(404, f"no model for {body.get('model')!r}; see /v1/models")
    base, upstream_model, key = _target(m, served)
    body["model"] = upstream_model
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"

    background = request.headers.get("x-aiws-priority") == "background"
    if background:
        try:
            await asyncio.wait_for(_idle.wait(), BACKGROUND_MAX_WAIT)
        except asyncio.TimeoutError:
            pass
    else:
        _enter()
    t0 = time.perf_counter()
    rec = {"ts": time.time(), "client": client["name"], "model": served,
           "requested": requested, "lane": "bg" if background else "fg"}
    try:
        req = _client.build_request("POST", f"{base}/v1/{path}", json=body, headers=headers)
        resp = await _client.send(req, stream=True)
    except httpx.HTTPError as e:
        if not background:
            _leave()
        raise HTTPException(502, f"{served}: {e}")

    if not body.get("stream"):
        data = await resp.aread()
        await resp.aclose()
        if not background:
            _leave()
        rec["wall_s"] = round(time.perf_counter() - t0, 3)
        _note(rec, data)
        return JSONResponse(json.loads(data or b"{}"), status_code=resp.status_code)

    async def relay():
        first = None
        try:
            async for chunk in resp.aiter_raw():
                if first is None:
                    first = time.perf_counter() - t0
                yield chunk
        finally:
            await resp.aclose()
            if not background:
                _leave()
            rec["ttft_s"] = round(first, 3) if first else None
            rec["wall_s"] = round(time.perf_counter() - t0, 3)
            _note(rec)

    return StreamingResponse(relay(), status_code=resp.status_code,
                             media_type=resp.headers.get("content-type", "text/event-stream"))


def _enter():
    global _interactive
    _interactive += 1
    _idle.clear()


def _leave():
    global _interactive
    _interactive = max(0, _interactive - 1)
    if _interactive == 0:
        _idle.set()


def _note(rec, data=None):
    if data:
        try:
            t = json.loads(data).get("timings") or {}
            rec["gen_tps"] = t.get("predicted_per_second")
        except Exception:
            pass
    _stats.append(rec)
    del _stats[:-200]


def recent():
    return list(reversed(_stats))


async def list_models():
    lib, _ = models.library()
    data = []
    for m in lib.values():
        for n in models.served_names(m):
            data.append({"id": n, "object": "model", "owned_by": "aiws",
                         "roles": m.get("roles", []), "present": models.present(m),
                         "runtime": m.get("runtime", "llama.cpp")})
    for r in models.ROLES:
        mm, served = models.resolve(f"ai:{r}", projects.roles_for(None))
        if mm:
            data.append({"id": f"ai:{r}", "object": "model", "owned_by": "aiws",
                         "alias_of": served})
    return {"object": "list", "data": data}


async def running():
    """What llama-swap has loaded right now."""
    try:
        r = await _client.get(f"{config.LLAMA_SWAP_URL}/running", timeout=3)
        return r.json().get("running", [])
    except Exception:
        return []


async def unload():
    try:
        await _client.get(f"{config.LLAMA_SWAP_URL}/unload", timeout=10)
        return True
    except Exception:
        return False
