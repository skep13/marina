"""Jobs on registered workers.

/etc/aiws/workers.d/lab2.yaml:

    name: lab2
    host: 192.168.1.229          # an SSH-reachable box (VM, container or host)
    user: aiws
    tags: [cpu, build, podman]
    max_mem: 1G                  # each job is capped with systemd-run
    cpu_weight: 50

A job is a shell command plus optional files to send. It runs as a
transient systemd scope on the worker (`systemd-run --user --scope`, or
plain `nice` where there's no user manager), so it can't take the
worker's memory. Output is streamed into the job's log as it arrives.
`local` is always a worker, so jobs work with every remote box down.
"""
import json
import shlex
import socket
import subprocess
import threading
import time

from aiws import config, store

SSH_KEY = config.STATE / "ssh" / "id_ed25519"
_procs = {}


def workers():
    w, _ = config.read_yaml_dir(config.ETC / "workers.d")
    w.setdefault("local", {"name": "local", "host": None, "tags": ["cpu", "local"],
                           "max_mem": "2G"})
    return w


def _ssh(w, extra=()):
    base = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5",
            "-o", "StrictHostKeyChecking=accept-new"]
    if SSH_KEY.exists():
        base += ["-i", str(SSH_KEY)]
    return base + list(extra) + [f"{w.get('user', 'aiws')}@{w['host']}"]


def probe(w):
    """Reachability and load, for the homelab view and for picking a worker."""
    if not w.get("host"):
        cmd = ["sh", "-c", "nproc; cat /proc/loadavg; grep MemAvailable /proc/meminfo"]
    else:
        try:
            socket.create_connection((w["host"], 22), timeout=2).close()
        except OSError as e:
            return {"up": False, "error": str(e)}
        cmd = _ssh(w) + ["nproc; cat /proc/loadavg; grep MemAvailable /proc/meminfo"]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=8)
    except subprocess.TimeoutExpired:
        return {"up": False, "error": "timeout"}
    if out.returncode != 0:
        return {"up": False, "error": out.stderr.strip()[-200:]}
    lines = out.stdout.split("\n")
    return {"up": True, "cpus": int(lines[0]), "load1": float(lines[1].split()[0]),
            "mem_avail_mb": int(lines[2].split()[1]) // 1024}


def pick(tags=()):
    """The reachable worker with all `tags` and the most free memory per load."""
    best, best_score = None, -1
    for w in workers().values():
        if not set(tags) <= set(w.get("tags") or []):
            continue
        p = probe(w)
        if not p.get("up"):
            continue
        score = p["mem_avail_mb"] / (1 + p["load1"] / max(p["cpus"], 1))
        if w["name"] != "local":
            score *= 1.5  # prefer offloading
        if score > best_score:
            best, best_score = w, score
    return best


def submit(name, command, worker=None, tags=(), cwd=None):
    w = workers().get(worker) if worker else pick(tags)
    if not w:
        raise ValueError(f"no reachable worker for tags {list(tags)}")
    spec = {"cwd": cwd, "tags": list(tags)}
    jid = store.q("INSERT INTO jobs(ts,name,worker,command,status,log,spec) VALUES(?,?,?,?,?,?,?)",
                  time.time(), name, w["name"], command, "queued", "", json.dumps(spec)).lastrowid
    threading.Thread(target=_run, args=(jid, w, command, cwd), daemon=True).start()
    return jid


def _wrap(w, command, cwd):
    mem = w.get("max_mem", "1G")
    inner = (f"cd {shlex.quote(cwd)} && " if cwd else "") + command
    # A scope gives a hard memory cap; fall back to nice where user systemd
    # isn't available (e.g. a container without lingering).
    return (f"if systemd-run --user --scope -q true 2>/dev/null; then "
            f"exec systemd-run --user --scope -q -p MemoryMax={mem} "
            f"-p CPUWeight={w.get('cpu_weight', 50)} nice -n 10 bash -lc {shlex.quote(inner)}; "
            f"else exec nice -n 10 bash -lc {shlex.quote(inner)}; fi")


def _run(jid, w, command, cwd):
    script = _wrap(w, command, cwd)
    cmd = ["bash", "-c", script] if not w.get("host") else _ssh(w) + [script]
    store.q("UPDATE jobs SET status='running', started=? WHERE id=?", time.time(), jid)
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True, bufsize=1, start_new_session=True)
    _procs[jid] = p
    buf, last = [], time.time()
    for line in p.stdout:
        buf.append(line)
        if time.time() - last > 1:
            store.q("UPDATE jobs SET log=log||? WHERE id=?", "".join(buf), jid)
            buf, last = [], time.time()
    code = p.wait()
    _procs.pop(jid, None)
    status = "done" if code == 0 else ("cancelled" if code in (-15, 143) else "failed")
    store.q("UPDATE jobs SET log=log||?, status=?, exit_code=?, finished=? WHERE id=?",
            "".join(buf), status, code, time.time(), jid)


def cancel(jid):
    p = _procs.get(jid)
    if p:
        p.terminate()
        return True
    return False


def list_jobs(limit=50):
    return store.rows("SELECT id,ts,name,worker,command,status,exit_code,started,finished "
                      "FROM jobs ORDER BY id DESC LIMIT ?", limit)


def job(jid):
    r = store.rows("SELECT * FROM jobs WHERE id=?", jid)
    return r[0] if r else None
