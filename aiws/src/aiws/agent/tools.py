"""What the assistant can do. Runs as the desktop user, never as root:
the agent's unit sets NoNewPrivileges, so sudo fails even if asked for.

Files are confined to the project's `agent.paths`. The terminal is the
project's own tmux session, so everything the assistant types is visible
and can be taken over. The desktop is observed on demand: the
accessibility tree first (cheap, exact), a screenshot only when the tree
isn't enough or the user asks what's on screen. Display specifics
(Hyprland/Wayland or X11) live in aiws.screen.
"""
import base64
import json
import os
import re
import subprocess
import time
from pathlib import Path

from aiws import screen

CLIP = 12000


class Refused(Exception):
    pass


class Context:
    def __init__(self, project, gateway):
        self.project = project
        self.root = Path(project["root"]).resolve()
        agent = project.get("agent") or {}
        self.allowed = [(self.root / p).resolve() for p in agent.get("paths", ["."])]
        self.tools = set(agent.get("tools", ["files", "terminal", "desktop", "jobs"]))
        self.session = "ai-" + project["name"]
        self.gateway = gateway  # callable(path, json) -> json


def _clip(s, n=CLIP):
    s = s if isinstance(s, str) else str(s)
    return s if len(s) <= n else s[: n // 2] + f"\n…[{len(s) - n} chars cut]…\n" + s[-n // 2:]


def _path(ctx, p, write=False):
    full = (ctx.root / (p or ".")).resolve()
    if not any(full == a or a in full.parents for a in ctx.allowed):
        raise Refused(f"{p} is outside this project's allowed paths")
    if write and any(part in (".git",) for part in full.relative_to(ctx.root).parts):
        raise Refused("won't write inside .git")
    return full


# ---- files ----
def list_files(ctx, path=".", depth=2):
    base = _path(ctx, path)
    out = []
    for dirpath, dirs, files in os.walk(base):
        rel = Path(dirpath).relative_to(base)
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d not in
                         ("node_modules", "__pycache__", ".venv", "venv"))
        if len(rel.parts) >= depth:
            dirs[:] = []
        for f in sorted(files):
            out.append(str(rel / f))
        if len(out) > 400:
            out.append("…")
            break
    return "\n".join(out)


def read_file(ctx, path, start_line=1, end_line=None):
    lines = _path(ctx, path).read_text(errors="replace").splitlines()
    end = end_line or min(len(lines), start_line + 400)
    body = "\n".join(f"{i:>5}  {l}" for i, l in
                     enumerate(lines[start_line - 1:end], start_line))
    return _clip(body) + (f"\n… {len(lines)} lines total" if end < len(lines) else "")


def write_file(ctx, path, content):
    p = _path(ctx, path, write=True)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return f"wrote {len(content)} chars to {path}"


def edit_file(ctx, path, old_text, new_text):
    p = _path(ctx, path, write=True)
    s = p.read_text()
    n = s.count(old_text)
    if n != 1:
        return f"old_text found {n} times; it must match exactly once"
    p.write_text(s.replace(old_text, new_text))
    return f"edited {path}"


# ---- terminal (the project's tmux session) ----
_SUDO = re.compile(r"(^|[;&|]\s*)(sudo|su|pkexec|doas)\b")


def _tmux(*a):
    return subprocess.run(["tmux", *a], capture_output=True, text=True)


def terminal_run(ctx, command, window="agent", wait_seconds=20):
    if _SUDO.search(command):
        raise Refused("admin commands go through the control centre, not the assistant")
    if _tmux("has-session", "-t", ctx.session).returncode != 0:
        _tmux("new-session", "-d", "-s", ctx.session, "-n", window, "-c", str(ctx.root))
    elif window not in _tmux("list-windows", "-t", ctx.session, "-F", "#W").stdout.split():
        _tmux("new-window", "-t", ctx.session, "-n", window, "-c", str(ctx.root))
    target = f"{ctx.session}:{window}"
    marker = f"__aiws_done_{int(time.time() * 1000)}"
    _tmux("send-keys", "-t", target, f"{command}; echo {marker} $?", "Enter")
    deadline = time.time() + float(wait_seconds)
    while time.time() < deadline:
        out = _tmux("capture-pane", "-p", "-J", "-t", target, "-S", "-400").stdout
        m = re.search(rf"^{marker} (\d+)\s*$", out, re.M)
        if m:
            body = out[: m.start()]
            body = body[body.rfind(command) + len(command):] if command in body else body
            return _clip(f"exit {m.group(1)}\n{body.strip()}")
        time.sleep(0.3)
    return _clip("still running after %ss; read it later with terminal_read\n" % wait_seconds
                 + _tmux("capture-pane", "-p", "-t", target).stdout)


def terminal_read(ctx, window="agent", lines=80):
    return _clip(_tmux("capture-pane", "-p", "-J", "-t", f"{ctx.session}:{window}",
                       "-S", f"-{int(lines)}").stdout)


# ---- desktop ----
def _focused_app():
    try:
        import pyatspi
    except ImportError:
        return None, None
    desktop = pyatspi.Registry.getDesktop(0)
    for app in desktop:
        if app is None:
            continue
        for win in app:
            try:
                if win and win.getState().contains(pyatspi.STATE_ACTIVE):
                    return app, win
            except Exception:
                continue
    return None, None


def desktop_tree(ctx, max_nodes=250):
    """The focused window as an accessibility tree: role, name, position.
    Exact and cheap; prefer it over a screenshot."""
    try:
        import pyatspi
    except ImportError:
        return "accessibility (pyatspi) isn't available"
    app, win = _focused_app()
    if not win:
        return "no focused window found over AT-SPI"
    out, n = [], 0
    # Wayland doesn't give apps their global position, so ask for window
    # coordinates and add where the compositor says the window is.
    wayland = screen.backend() in ("hyprland", "wayland")
    coords = pyatspi.WINDOW_COORDS if wayland else pyatspi.DESKTOP_COORDS
    w = screen.active_window() if wayland else {}
    ox, oy = w.get("x", 0), w.get("y", 0)

    def walk(node, depth):
        nonlocal n
        if n >= max_nodes or node is None:
            return
        try:
            role = node.getRoleName()
            name = (node.name or "").strip()
            st = node.getState()
            if not st.contains(pyatspi.STATE_SHOWING):
                return
            ext = node.queryComponent().getExtents(coords)
        except Exception:
            return
        if name or role in ("push button", "text", "entry", "menu item", "link", "check box"):
            out.append(f"{'  ' * depth}{role} {name[:80]!r} @({ox + ext.x + ext.width // 2},"
                       f"{oy + ext.y + ext.height // 2})")
            n += 1
        for i in range(min(node.childCount, 60)):
            walk(node.getChildAtIndex(i), depth + 1)

    walk(win, 0)
    return f"app: {app.name}\n" + "\n".join(out)


def screenshot(ctx, question="Describe what's on screen.", window_only=False):
    """Capture now and ask the vision model about it."""
    png = screen.capture(window_only)
    b64 = base64.b64encode(png).decode()
    r = ctx.gateway("chat/completions", {
        "model": "ai:vision", "max_tokens": 600, "temperature": 0.2,
        "chat_template_kwargs": {"enable_thinking": False},
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": question},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}]}],
    })
    return r["choices"][0]["message"]["content"]


def click(ctx, x, y, button=1):
    screen.click(x, y, button)
    return f"clicked {x},{y}"


def type_text(ctx, text):
    screen.type_text(text)
    return f"typed {len(text)} chars"


def key(ctx, combo):
    screen.key(combo)
    return f"pressed {combo}"


def open_app(ctx, command):
    allowed = {"firefox", "zen-browser", "codium", "foot", "alacritty", "x-terminal-emulator",
               "thunar", "mousepad"}
    exe = command.split()[0]
    if exe not in allowed:
        raise Refused(f"{exe} isn't in the assistant's app list")
    subprocess.Popen(command.split(), start_new_session=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return f"started {command}"


# ---- jobs on other machines ----
def submit_job(ctx, command, tags=None, worker=None, name="agent job"):
    r = ctx.gateway("../api/jobs", {"name": name, "command": command,
                                    "tags": tags or [], "worker": worker})
    return json.dumps(r)


def job_status(ctx, job_id):
    r = ctx.gateway(f"../api/jobs/{int(job_id)}", None)
    r["log"] = _clip(r.get("log") or "", 4000)
    return json.dumps(r)


TOOLS = {
    "files": [list_files, read_file, write_file, edit_file],
    "terminal": [terminal_run, terminal_read],
    "desktop": [desktop_tree, screenshot, click, type_text, key, open_app],
    "jobs": [submit_job, job_status],
}

SCHEMAS = {
    "list_files": ("List files in the project.", {"path": "string", "depth": "integer"}, []),
    "read_file": ("Read a file with line numbers.",
                  {"path": "string", "start_line": "integer", "end_line": "integer"}, ["path"]),
    "write_file": ("Create or overwrite a file.", {"path": "string", "content": "string"},
                   ["path", "content"]),
    "edit_file": ("Replace text that occurs exactly once in a file.",
                  {"path": "string", "old_text": "string", "new_text": "string"},
                  ["path", "old_text", "new_text"]),
    "terminal_run": ("Run a shell command in the project's visible tmux terminal and "
                     "return its output.",
                     {"command": "string", "window": "string", "wait_seconds": "integer"},
                     ["command"]),
    "terminal_read": ("Read what a terminal window shows.",
                      {"window": "string", "lines": "integer"}, []),
    "desktop_tree": ("The focused window's controls (accessibility tree) with "
                     "click coordinates. Prefer this to a screenshot.", {}, []),
    "screenshot": ("Take a screenshot and ask a question about it.",
                   {"question": "string", "window_only": "boolean"}, []),
    "click": ("Click at screen coordinates.", {"x": "integer", "y": "integer"}, ["x", "y"]),
    "type_text": ("Type text into the focused control.", {"text": "string"}, ["text"]),
    "key": ("Press a key combination, e.g. ctrl+s.", {"combo": "string"}, ["combo"]),
    "open_app": ("Start an app (firefox, zen-browser, codium, foot, thunar, mousepad).",
                 {"command": "string"}, ["command"]),
    "submit_job": ("Run a command on another machine in the homelab.",
                   {"command": "string", "tags": "array", "worker": "string",
                    "name": "string"}, ["command"]),
    "job_status": ("A job's status and log.", {"job_id": "integer"}, ["job_id"]),
}


def available(ctx):
    fns = {f.__name__: f for group, fs in TOOLS.items() if group in ctx.tools for f in fs}
    schemas = []
    for name in fns:
        desc, props, req = SCHEMAS[name]
        schemas.append({"type": "function", "function": {
            "name": name, "description": desc,
            "parameters": {"type": "object", "required": req, "properties": {
                k: ({"type": t, "items": {"type": "string"}} if t == "array" else {"type": t})
                for k, t in props.items()}}}})
    return fns, schemas
