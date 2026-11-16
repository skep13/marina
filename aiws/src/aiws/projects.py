"""Projects: a workspace AIWS can restore.

`.aiws/project.yaml` in the project's root:

    name: marina
    repos:
      - path: .                         # this repo
      - url: git@github.com:skep13/songbird-pet.git
        path: ../songbird-pet
    models:                             # role -> model; overrides the global choice
      code: qwen3.6-35b-a3b@interactive
      vision: qwen3.6-35b-a3b
    profile: coding                     # behaviour profile (prompts, tools)
    env:                                # isolated environment
      kind: distrobox                   # distrobox | podman | none
      image: docker.io/library/python:3.12
    terminals:                          # tmux windows, restored in order
      - name: shell
      - name: server
        run: ./start-bridge.sh
      - name: tests
        run: python -m pytest -q
    editor: codium                      # codium | nvim | none
    agent:
      tools: [files, terminal, desktop, jobs]
      paths: ["."]                       # where the assistant may write
"""
import os
import shlex
import subprocess
from pathlib import Path

import yaml

from aiws import store


def registry():
    return store.get("projects") or {}


def register(path, spec=None):
    """Remember a project. aiwsd runs as its own user and usually can't
    read the desktop user's home, so the CLI reads project.yaml and sends
    it here as `spec`; aiwsd keeps that copy."""
    root = Path(path).expanduser().resolve()
    spec = dict(spec) if spec else load(root)
    spec.setdefault("name", root.name)
    spec["root"] = str(root)
    reg = registry()
    reg[spec["name"]] = spec
    store.put("projects", reg)
    return spec


def load(root):
    root = Path(root)
    f = root / ".aiws" / "project.yaml"
    try:
        spec = yaml.safe_load(f.read_text()) or {}
    except OSError:
        spec = {}
    spec.setdefault("name", root.name)
    spec["root"] = str(root)
    return spec


def get(name):
    return registry().get(name)


def active():
    name = store.get("active_project")
    return get(name) if name else None


def set_active(name):
    store.put("active_project", name)


def roles_for(name):
    """Role -> model for a project: its project.yaml, then choices made
    in the control centre on top."""
    p = get(name) if name else active()
    if not p:
        return {}
    return {**(p.get("models") or {}), **(store.get(f"project_roles:{p['name']}") or {})}


# ---- restoring (runs as the desktop user, from `ai open`) ----

def _sh(cmd, **kw):
    return subprocess.run(cmd, shell=isinstance(cmd, str), **kw)


def tmux_session(spec):
    return "ai-" + spec["name"]


def restore(spec, attach_terminal=True, open_editor=True):
    """Bring a project back: repos, environment, tmux windows, editor.
    Returns the steps taken, so the caller can show them."""
    root = Path(spec["root"])
    steps = []
    for r in spec.get("repos") or []:
        p = (root / r.get("path", ".")).resolve()
        if r.get("url") and not p.exists():
            _sh(["git", "clone", r["url"], str(p)], check=False)
            steps.append(f"cloned {r['url']}")
    env = spec.get("env") or {}
    enter = ""
    if env.get("kind") == "distrobox":
        box = "ai-" + spec["name"]
        have = _sh(["distrobox", "list", "--no-color"], capture_output=True, text=True)
        if box not in (have.stdout or ""):
            _sh(["distrobox", "create", "-Y", "-n", box, "-i", env["image"]], check=False)
            steps.append(f"created distrobox {box}")
        enter = f"distrobox enter {box} -- "
    elif env.get("kind") == "podman":
        enter = (f"podman run --rm -it --userns=keep-id -v {shlex.quote(str(root))}:/work:Z "
                 f"-w /work {shlex.quote(env['image'])} ")
    sess = tmux_session(spec)
    exists = _sh(["tmux", "has-session", "-t", sess], capture_output=True).returncode == 0
    if not exists:
        terms = spec.get("terminals") or [{"name": "shell"}]
        for i, t in enumerate(terms):
            shell_cmd = enter + "bash -l" if enter else ""
            args = (["tmux", "new-session", "-d", "-s", sess, "-n", t["name"], "-c", str(root)]
                    if i == 0 else
                    ["tmux", "new-window", "-t", sess, "-n", t["name"], "-c", str(root)])
            if shell_cmd:
                args.append(shell_cmd)
            _sh(args, check=False)
            if t.get("run"):
                _sh(["tmux", "send-keys", "-t", f"{sess}:{t['name']}", t["run"], "Enter"])
        steps.append(f"tmux {sess}: {', '.join(t['name'] for t in terms)}")
    else:
        steps.append(f"tmux {sess} already running")
    if attach_terminal and os.environ.get("DISPLAY"):
        subprocess.Popen(["x-terminal-emulator", "-T", spec["name"],
                          "-e", "tmux", "attach", "-t", sess], start_new_session=True)
    ed = spec.get("editor", "codium")
    if open_editor and ed == "codium" and os.environ.get("DISPLAY"):
        subprocess.Popen(["codium", str(root)], start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        steps.append("opened VSCodium")
    set_active(spec["name"])
    steps.append(f"models: {spec.get('models') or 'global defaults'}")
    return steps
