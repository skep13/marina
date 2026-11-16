"""`ai` — the workstation from a terminal.

  ai status
  ai models [list]                 the library, what's loaded, role choices
  ai models use ROLE MODEL [-p P]  e.g. ai models use code qwen3.6-35b-a3b@interactive
  ai models unload | apply | verify NAME
  ai init [PATH]                   make PATH a AIWS project
  ai open NAME|PATH                restore a project (repos, env, terminals, editor)
  ai ask "…" [-p P]                give the assistant a task
  ai agent log | pause | resume | stop
  ai job run CMD [--tags a,b] [--worker W] | list | log ID | cancel ID
  ai cluster                       workers and Proxmox
  ai token new NAME [--scopes chat,agent] | list | revoke NAME
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = os.environ.get("AIWS_URL", "http://127.0.0.1:7300")


def token():
    if os.environ.get("AIWS_TOKEN"):
        return os.environ["AIWS_TOKEN"]
    f = Path(os.environ.get("AIWS_TOKEN_FILE", "/var/lib/aiws/desktop.token"))
    try:
        return f.read_text().strip()
    except OSError:
        sys.exit(f"can't read {f}: is this user in the 'aiws' group?")


def api(path, payload=None, method=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(f"{BASE}/api/{path}", data,
                                 method=method or ("POST" if data is not None else "GET"),
                                 headers={"Authorization": f"Bearer {token()}",
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        sys.exit(f"aiwsd: {e.code} {e.read().decode()[:300]}")
    except urllib.error.URLError as e:
        sys.exit(f"aiwsd isn't answering at {BASE}: {e.reason}")


def gb(mb):
    return f"{mb / 1024:.1f}G" if mb is not None else "?"


def cmd_status(a):
    s = api("status")
    m = s.get("memory") or {}
    g = m.get("gpu") or {}
    print(f"project   {s['active_project'] or '-'}")
    print(f"loaded    {', '.join(r.get('model', '?') + ' (' + r.get('state', '') + ')' for r in s['running']) or 'nothing'}")
    print(f"assistant {s['agent']}")
    print(f"memory    {gb(m.get('available_mb'))} free of {gb(m.get('total_mb'))}"
          f"   swap used {gb(m.get('swap_used_mb'))}")
    if g:
        print(f"gpu       vram {gb(g['vram_used_mb'])}/{gb(g['vram_total_mb'])}"
              f"   gtt {gb(g['gtt_used_mb'])}/{gb(g['gtt_total_mb'])}")
    print(f"load      {' '.join(f'{x:.2f}' for x in s['load'])}")


def cmd_models(a):
    if a.action in (None, "list"):
        r = api("models")
        loaded = {x.get("model") for x in api("status")["running"]}
        for m in r["models"]:
            mark = "●" if any(n in loaded for n in m["served"]) else ("○" if m["present"] else "✗")
            print(f"{mark} {m['name']:<28} {','.join(m.get('roles', [])):<22} "
                  f"{m.get('runtime', 'llama.cpp'):<10} {', '.join(m['served'][1:])}")
        print("\nroles:", ", ".join(f"{k}={v}" for k, v in r["roles"].items()) or "defaults")
        for f, e in r["errors"].items():
            print(f"! {f}: {e}")
    elif a.action == "use":
        role, model = a.args
        print(api("models/roles", {"role": role, "model": model, "project": a.project}))
    elif a.action == "unload":
        print(api("models/unload", {}))
    elif a.action == "apply":
        print(api("models/apply", {}))
    elif a.action == "verify":
        from aiws import models
        lib, _ = models.library()
        m = lib[a.args[0]]
        got = models.sha256_file(models.path_of(m))
        print("ok" if got == m.get("sha256") else f"MISMATCH {got}")


def cmd_init(a):
    # Written here, as the user, then registered with aiwsd.
    p = Path(a.path or ".").resolve()
    f = p / ".aiws" / "project.yaml"
    if not f.exists():
        import yaml
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(yaml.safe_dump({
            "name": p.name, "repos": [{"path": "."}], "models": {},
            "env": {"kind": "none"}, "terminals": [{"name": "shell"}],
            "editor": "codium",
            "agent": {"tools": ["files", "terminal", "desktop", "jobs"], "paths": ["."]}},
            sort_keys=False))
    print(_register(p)["name"], "registered:", f)


def _register(root):
    import yaml
    f = Path(root) / ".aiws" / "project.yaml"
    spec = (yaml.safe_load(f.read_text()) or {}) if f.exists() else {}
    return api("projects", {"path": str(root), "spec": spec})


def cmd_open(a):
    from aiws import projects as P
    target = a.name
    if os.path.isdir(target):
        spec = _register(Path(target).resolve())
    else:
        spec = api(f"projects/{target}")
        if Path(spec["root"]).is_dir():  # pick up edits to project.yaml
            spec = _register(Path(spec["root"]))
    api(f"projects/{spec['name']}/activate", {})
    for step in P.restore(spec, attach_terminal=not a.no_terminal, open_editor=not a.no_editor):
        print("·", step)


def cmd_ask(a):
    t = api("agent/tasks", {"prompt": " ".join(a.prompt), "project": a.project, "model": a.model})
    print(f"task {t['id']} queued; following the action log (Ctrl-C leaves it running)")
    seen = 0
    try:
        while True:
            for act in reversed(api(f"agent/actions?after={seen}")["actions"]):
                if act["status"] == "running":
                    continue
                seen = max(seen, act["id"])
                print(f"  {act['tool']}({act['args'][:100]}) → {act['status']}")
            task = next((x for x in api("agent/tasks")["tasks"] if x["id"] == t["id"]), {})
            if task.get("status") in ("done", "failed", "stopped"):
                print(f"\n[{task['status']}] {task.get('result') or ''}")
                return
            time.sleep(1)
    except KeyboardInterrupt:
        pass


def cmd_agent(a):
    if a.action == "log":
        for act in reversed(api("agent/actions?limit=40")["actions"]):
            ts = time.strftime("%H:%M:%S", time.localtime(act["ts"]))
            print(f"{ts} {act['status']:<8} {act['tool']}({act['args'][:90]})")
        return
    state = {"pause": "paused", "resume": "running", "stop": "stopped"}[a.action]
    print(api("agent/state", {"state": state}))
    if a.action == "stop":
        # The hard stop: kill the agent and everything it started, then bring
        # a fresh one up for the next task.
        subprocess.run(["systemctl", "--user", "kill", "-s", "KILL", "aiws-agent.service"])
        subprocess.run(["systemctl", "--user", "restart", "aiws-agent.service"])
        api("agent/state", {"state": "running"})
        print("assistant stopped and reset")


def cmd_job(a):
    if a.action == "run":
        r = api("jobs", {"name": a.name or a.args[0][:40], "command": " ".join(a.args),
                         "tags": [t for t in (a.tags or "").split(",") if t],
                         "worker": a.worker})
        print(f"job {r['id']} on {r['worker']}")
        if a.follow:
            a.args = [str(r["id"])]
            a.action = "log"
            cmd_job(a)
    elif a.action == "list":
        for j in api("jobs")["jobs"]:
            dur = (j["finished"] or time.time()) - (j["started"] or j["ts"])
            print(f"{j['id']:>4} {j['status']:<9} {j['worker']:<8} {dur:7.1f}s  {j['command'][:60]}")
    elif a.action == "log":
        jid, shown = a.args[0], 0
        while True:
            j = api(f"jobs/{jid}")
            sys.stdout.write(j["log"][shown:])
            sys.stdout.flush()
            shown = len(j["log"])
            if j["status"] in ("done", "failed", "cancelled"):
                print(f"\n[{j['status']} exit={j['exit_code']}]")
                return
            time.sleep(1)
    elif a.action == "cancel":
        print(api(f"jobs/{a.args[0]}/cancel", {}))


def cmd_cluster(a):
    r = api("cluster")
    for w in r["workers"]:
        st = (f"{w['cpus']} cpu  load {w['load1']:.2f}  {w['mem_avail_mb']} MB free"
              if w.get("up") else f"down ({w.get('error', '')[:60]})")
        print(f"worker {w['name']:<8} {w['host']:<16} {','.join(w['tags']):<20} {st}")
    p = r["proxmox"]
    if not p.get("configured"):
        print("proxmox: not configured (proxmox.url in /etc/aiws/aiws.yaml, AIWS_PVE_TOKEN)")
    elif p.get("error"):
        print("proxmox:", p["error"])
    else:
        print(f"\nproxmox {p['cluster']} quorate={p['quorate']}")
        for n in p["nodes"]:
            print(f"  {n['name']:<6} {n['status']:<8} cpu {n['cpu']:>5}%  "
                  f"mem {n['mem_used_gb']}/{n['mem_total_gb']} GB")
        for g in p["guests"]:
            print(f"    {g['vmid']} {g['name']:<18} {g['node']:<5} {g['status']}")


def cmd_token(a):
    if a.action == "new":
        r = api("tokens", {"name": a.args[0], "scopes": (a.scopes or "chat").split(",")})
        print(r["token"])
    elif a.action == "list":
        for t in api("tokens")["tokens"]:
            print(t["name"], t["scopes"])
    elif a.action == "revoke":
        print(api(f"tokens/{a.args[0]}", method="DELETE"))


def main():
    ap = argparse.ArgumentParser(prog="ai", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status").set_defaults(fn=cmd_status)
    p = sub.add_parser("models"); p.add_argument("action", nargs="?")
    p.add_argument("args", nargs="*"); p.add_argument("-p", "--project")
    p.set_defaults(fn=cmd_models)
    p = sub.add_parser("init"); p.add_argument("path", nargs="?"); p.set_defaults(fn=cmd_init)
    p = sub.add_parser("open"); p.add_argument("name")
    p.add_argument("--no-terminal", action="store_true")
    p.add_argument("--no-editor", action="store_true"); p.set_defaults(fn=cmd_open)
    p = sub.add_parser("ask"); p.add_argument("prompt", nargs="+")
    p.add_argument("-p", "--project"); p.add_argument("-m", "--model")
    p.set_defaults(fn=cmd_ask)
    p = sub.add_parser("agent"); p.add_argument("action", choices=["log", "pause", "resume", "stop"])
    p.set_defaults(fn=cmd_agent)
    p = sub.add_parser("job"); p.add_argument("action", choices=["run", "list", "log", "cancel"])
    p.add_argument("args", nargs="*"); p.add_argument("--tags"); p.add_argument("--worker")
    p.add_argument("--name"); p.add_argument("-f", "--follow", action="store_true")
    p.set_defaults(fn=cmd_job)
    sub.add_parser("cluster").set_defaults(fn=cmd_cluster)
    p = sub.add_parser("token"); p.add_argument("action", choices=["new", "list", "revoke"])
    p.add_argument("args", nargs="*"); p.add_argument("--scopes"); p.set_defaults(fn=cmd_token)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
