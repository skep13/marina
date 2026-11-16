"""aiwsd: AIWS's one service. OpenAI-compatible gateway on /v1, the
control centre's API on /api and its UI on /ui."""
import asyncio
import glob
import os
import time
from pathlib import Path

from fastapi import Body, Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from aiws import cluster, config, gateway, jobs, models, projects, store

app = FastAPI(title="aiwsd", docs_url=None, redoc_url=None)
UI = Path(__file__).parent / "ui"

store.q("""CREATE TABLE IF NOT EXISTS tasks (
  id INTEGER PRIMARY KEY, ts REAL, project TEXT, prompt TEXT, model TEXT,
  status TEXT, result TEXT, finished REAL)""")


# ---- auth ----
def client(request: Request):
    h = request.headers.get("authorization", "")
    tok = h[7:] if h.lower().startswith("bearer ") else request.headers.get("x-api-key")
    c = store.check_token(tok)
    if not c:
        raise HTTPException(401, "missing or unknown AIWS token")
    return c


def admin(c=Depends(client)):
    if "admin" not in c["scopes"]:
        raise HTTPException(403, "needs the admin scope")
    return c


def _desktop_token():
    """The desktop session's token: readable by group `aiws`, which the
    desktop user is in. Rotated when the file is missing."""
    f = config.STATE / "desktop.token"
    if not f.exists() or not store.check_token(f.read_text().strip()):
        tok = store.new_token("desktop", ("admin", "chat", "agent"))
        f.write_text(tok + "\n")
        os.chmod(f, 0o640)
    return f


@app.on_event("startup")
def startup():
    _desktop_token()
    try:
        models.write_llama_swap_config()
    except OSError as e:
        print("aiwsd: can't write llama-swap config:", e)


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/")
def root():
    return RedirectResponse("/ui/")


# ---- OpenAI-compatible ----
@app.get("/v1/models")
async def v1_models(c=Depends(client)):
    return await gateway.list_models()


@app.post("/v1/{path:path}")
async def v1(path: str, request: Request, c=Depends(client)):
    if path not in ("chat/completions", "completions", "embeddings"):
        raise HTTPException(404)
    return await gateway.proxy(request, path, c)


# ---- status ----
def _meminfo():
    m = {}
    for line in open("/proc/meminfo"):
        k, v = line.split(":")
        m[k] = int(v.split()[0]) // 1024
    gpu = {}
    for dev in glob.glob("/sys/class/drm/card*/device"):
        try:
            for kind in ("vram", "gtt"):
                gpu[f"{kind}_used_mb"] = int(open(f"{dev}/mem_info_{kind}_used").read()) // 2**20
                gpu[f"{kind}_total_mb"] = int(open(f"{dev}/mem_info_{kind}_total").read()) // 2**20
            break
        except OSError:
            continue
    return {"total_mb": m.get("MemTotal"), "available_mb": m.get("MemAvailable"),
            "swap_used_mb": m.get("SwapTotal", 0) - m.get("SwapFree", 0), "gpu": gpu}


@app.get("/api/status")
async def status(c=Depends(client)):
    return {"time": time.time(), "running": await gateway.running(),
            "active_project": store.get("active_project"),
            "agent": store.get("agent_state", "running"),
            "memory": _meminfo() if Path("/proc/meminfo").exists() else {},
            "load": os.getloadavg(), "requests": gateway.recent()[:20]}


# ---- models ----
@app.get("/api/models")
def api_models(c=Depends(client)):
    lib, errors = models.library()
    return {"models": [{**m, "present": models.present(m), "served": models.served_names(m)}
                       for m in lib.values()],
            "roles": models.role_map(), "errors": errors}


@app.post("/api/models/roles")
def api_set_role(body: dict = Body(...), c=Depends(admin)):
    m, _ = models.resolve(body["model"])
    if not m:
        raise HTTPException(404, "unknown model")
    if body.get("project"):
        spec = projects.get(body["project"])
        if not spec:
            raise HTTPException(404, "unknown project")
        key = f"project_roles:{body['project']}"
        store.put(key, {**(store.get(key) or {}), body["role"]: body["model"]})
    else:
        models.set_role(body["role"], body["model"])
    return {"ok": True, "roles": models.role_map()}


@app.post("/api/models/unload")
async def api_unload(c=Depends(admin)):
    return {"ok": await gateway.unload()}


@app.post("/api/models/apply")
def api_apply(c=Depends(admin)):
    return {"changed": models.write_llama_swap_config()}


# ---- projects ----
@app.get("/api/projects")
def api_projects(c=Depends(client)):
    return {"projects": list(projects.registry().values()),
            "active": store.get("active_project")}


@app.get("/api/projects/{name}")
def api_project(name: str, c=Depends(client)):
    p = projects.get(name)
    if not p:
        raise HTTPException(404)
    return p


@app.post("/api/projects")
def api_add_project(body: dict = Body(...), c=Depends(admin)):
    return projects.register(body["path"], body.get("spec"))


@app.post("/api/projects/{name}/activate")
def api_activate(name: str, c=Depends(admin)):
    if not projects.get(name):
        raise HTTPException(404)
    projects.set_active(name)
    return {"ok": True}


# ---- jobs ----
@app.get("/api/jobs")
def api_jobs(c=Depends(client)):
    return {"jobs": jobs.list_jobs(), "workers": list(jobs.workers())}


@app.post("/api/jobs")
def api_submit(body: dict = Body(...), c=Depends(client)):
    if not ({"admin", "agent"} & c["scopes"]):
        raise HTTPException(403)
    try:
        jid = jobs.submit(body.get("name") or "job", body["command"],
                          worker=body.get("worker"), tags=body.get("tags") or (),
                          cwd=body.get("cwd"))
    except ValueError as e:
        raise HTTPException(409, str(e))
    return {"id": jid, "worker": jobs.job(jid)["worker"]}


@app.get("/api/jobs/{jid}")
def api_job(jid: int, c=Depends(client)):
    j = jobs.job(jid)
    if not j:
        raise HTTPException(404)
    return j


@app.post("/api/jobs/{jid}/cancel")
def api_cancel(jid: int, c=Depends(admin)):
    return {"ok": jobs.cancel(jid)}


@app.get("/api/cluster")
def api_cluster(c=Depends(client)):
    return cluster.overview()


# ---- assistant ----
_task_ready = asyncio.Event()


@app.get("/api/agent/state")
def agent_state(c=Depends(client)):
    return {"state": store.get("agent_state", "running")}


@app.post("/api/agent/state")
def set_agent_state(body: dict = Body(...), c=Depends(admin)):
    st = body["state"]
    if st not in ("running", "paused", "stopped"):
        raise HTTPException(400)
    store.put("agent_state", st)
    if st == "stopped":
        store.q("UPDATE tasks SET status='stopped', finished=? WHERE status IN ('queued','running')",
                time.time())
    return {"state": st}


@app.post("/api/agent/tasks")
def new_task(body: dict = Body(...), c=Depends(admin)):
    project = body.get("project") or store.get("active_project")
    if not project or not projects.get(project):
        raise HTTPException(400, "open a project first")
    store.put("agent_state", "running")
    tid = store.q("INSERT INTO tasks(ts,project,prompt,model,status) VALUES(?,?,?,?,?)",
                  time.time(), project, body["prompt"], body.get("model"), "queued").lastrowid
    _task_ready.set()
    return {"id": tid}


@app.get("/api/agent/tasks")
def list_tasks(c=Depends(client)):
    return {"tasks": store.rows("SELECT * FROM tasks ORDER BY id DESC LIMIT 30")}


@app.get("/api/agent/next")
async def next_task(c=Depends(client)):
    if "agent" not in c["scopes"]:
        raise HTTPException(403)
    for _ in range(50):
        r = store.rows("SELECT * FROM tasks WHERE status='queued' ORDER BY id LIMIT 1")
        if r and store.get("agent_state", "running") != "stopped":
            return r[0]
        _task_ready.clear()
        try:
            await asyncio.wait_for(_task_ready.wait(), 0.5)
        except asyncio.TimeoutError:
            pass
    return {}


@app.patch("/api/agent/tasks/{tid}")
def update_task(tid: int, body: dict = Body(...), c=Depends(client)):
    fields = {k: body[k] for k in ("status", "result") if k in body}
    if fields.get("status") in ("done", "failed", "stopped"):
        fields["finished"] = time.time()
    for k, v in fields.items():
        store.q(f"UPDATE tasks SET {k}=? WHERE id=?", v, tid)
    return {"ok": True}


@app.post("/api/agent/actions")
def log_action(body: dict = Body(...), c=Depends(client)):
    return {"id": store.action_start(body.get("session", ""), body["tool"], body.get("args", {}))}


@app.patch("/api/agent/actions/{aid}")
def end_action(aid: int, body: dict = Body(...), c=Depends(client)):
    store.action_end(aid, body.get("status", "ok"), body.get("result", ""))
    return {"ok": True}


@app.get("/api/agent/actions")
def get_actions(after: int = 0, limit: int = 100, c=Depends(client)):
    return {"actions": store.actions(limit, after)}


# ---- tokens ----
@app.get("/api/tokens")
def tokens(c=Depends(admin)):
    return {"tokens": store.list_tokens()}


@app.post("/api/tokens")
def make_token(body: dict = Body(...), c=Depends(admin)):
    scopes = [s for s in body.get("scopes", ["chat"]) if s in ("chat", "agent", "admin")]
    return {"name": body["name"], "token": store.new_token(body["name"], scopes)}


@app.delete("/api/tokens/{name}")
def drop_token(name: str, c=Depends(admin)):
    return {"revoked": store.revoke(name)}


app.mount("/ui", StaticFiles(directory=UI, html=True), name="ui")


def main():
    import uvicorn
    host, port = config.LISTEN.rsplit(":", 1)
    uvicorn.run(app, host=host, port=int(port), log_level="warning")


if __name__ == "__main__":
    main()
