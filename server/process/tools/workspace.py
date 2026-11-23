"""A Linux machine she can use: tools for running commands and editing files there.

Two kinds, set by `workspace.desktop`:
  xfce      her own machine (marina-workspace), with a shared tmux terminal
            and a desktop tool for its looks.
  cinnamon  their PC, lab2 (Linux Mint), which she uses as their own account
            with sudo: commands, files, apps, the mouse and keyboard, and
            screenshots of both screens.

Everything goes over SSH with a key of its own (`workspace.key`), so what she
can touch is exactly what that account on that machine can touch, and
revoking her access is deleting one line from its authorized_keys. Scripts
and file contents travel over stdin, never through the shell, so nothing
needs quoting.

Every command she runs is also appended to ~/.marina/terminal.log on that
machine, which the shared tmux session (`marina-tmux` there) shows live
above a shell of your own. read_terminal lets her read that shell back.
"""
import json
import os
import re
import shlex
import subprocess
from pathlib import Path

from process.config import load_config, resolve_data

_cfg = load_config().get("workspace") or {}

ENABLED = bool(_cfg.get("enabled", False))
HOST = str(_cfg.get("host") or "").strip()
USER = str(_cfg.get("user") or "marina").strip()
PORT = int(_cfg.get("port", 22))
ROOT = str(_cfg.get("root") or "~/projects").rstrip("/")
TIMEOUT = float(_cfg.get("timeout_seconds", 120))
OUTPUT_CHARS = int(_cfg.get("output_chars", 6000))
READ_LINES = int(_cfg.get("read_lines", 400))
DESKTOP = str(_cfg.get("desktop") or "xfce").strip().lower()
THEIRS = DESKTOP != "xfce"     # their PC, not her own machine
NAME = str(_cfg.get("name") or ("lab2" if THEIRS else "marina-workspace")).strip()

# So what she starts can reach their desktop session: open windows, show
# notifications, control the music player.
_SESSION_ENV = ("export DISPLAY=:0 XDG_RUNTIME_DIR=/run/user/$(id -u) "
                "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$(id -u)/bus; ")


def _key():
    raw = str(_cfg.get("key") or "workspace_key")
    p = Path(raw).expanduser()
    return p if p.is_absolute() else resolve_data(raw)


def available():
    return ENABLED and bool(HOST)


def _ssh(command, stdin=None, timeout=None):
    """Run a shell command on the workspace. Returns (exit code, output)."""
    # Socket paths are capped at 104 bytes on macOS, which Application
    # Support plus the 40-character %C hash would overrun.
    control = f"/tmp/marina-ws-{os.getuid()}-%C"
    args = [
        "ssh", "-T",
        "-i", str(_key()),
        "-p", str(PORT),
        "-o", "BatchMode=yes",
        "-o", "IdentitiesOnly=yes",
        "-o", "ConnectTimeout=6",
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", f"UserKnownHostsFile={resolve_data('workspace_known_hosts')}",
        # One connection reused across calls, so a run of small tool calls
        # doesn't pay for a handshake each time.
        "-o", "ControlMaster=auto",
        "-o", f"ControlPath={control}",
        "-o", "ControlPersist=300",
        f"{USER}@{HOST}",
        command,
    ]
    try:
        # No stdin unless there is something to send, so a command that
        # waits for input gets EOF instead of hanging until the timeout.
        feed = {"input": stdin} if stdin is not None else {"stdin": subprocess.DEVNULL}
        out = subprocess.run(args, capture_output=True, text=True,
                             timeout=timeout or TIMEOUT, **feed)
    except subprocess.TimeoutExpired:
        return 124, f"Timed out after {int(timeout or TIMEOUT)} seconds."
    except FileNotFoundError:
        return 127, "ssh is not installed here."
    text = (out.stdout or "") + (out.stderr or "")
    if out.returncode == 255 and not out.stdout:
        return 255, f"Could not reach the workspace at {HOST}: {text.strip()[:300]}"
    return out.returncode, text


def _clip(text):
    text = text.rstrip()
    if len(text) <= OUTPUT_CHARS:
        return text
    half = OUTPUT_CHARS // 2
    dropped = len(text) - OUTPUT_CHARS
    return f"{text[:half]}\n… ({dropped} characters cut) …\n{text[-half:]}"


def _path(path):
    """Relative paths are relative to the projects folder. Returned quoted
    for the shell, except for a leading ~ which the shell has to expand."""
    path = (path or "").strip() or "."
    if not path.startswith(("/", "~")):
        path = f"{ROOT}/{path}"
    if path.startswith("~/"):
        return "~/" + shlex.quote(path[2:])
    return shlex.quote(path)


# Killing any of these from a command takes part of the desktop down with
# it: whatever she starts again from the same command dies when it ends.
_SESSION = (r"(xfdesktop|xfwm4|xfce4-panel|xfce4-session|xfsettingsd|xfconfd|xfce4-terminal"
            r"|cinnamon|cinnamon-session|muffin|nemo-desktop|csd-\w+|Xorg|lightdm|tmux)")
_KILLS = re.compile(
    rf"\b(?:pkill|killall)\b[^|;&]*\b{_SESSION}\b"
    rf"|\b{_SESSION}\s+(?:--quit|-q)\b"
    r"|\btmux\s+kill-(?:server|session)\b"
    r"|\bsystemctl\s+(?:stop|restart)\s+lightdm\b", re.I)

# On lab2, plain xrandr mode changes leave Cinnamon drawing at the old size,
# zoomed and cropped. Setting an output property (Broadcast RGB) is fine.
_XRANDR = re.compile(r"\bxrandr\b[^|;&\n]*--(?:auto|mode|rotate|scale|pos|off|primary"
                     r"|brightness|transform|fb|left-of|right-of|above|below)\b")

_APT = re.compile(r"\bapt(?:-get)?\s+(?:-\S+\s+)*install\b([^;&|\n]*)")


def refused(command):
    """Why a command mustn't run, or None."""
    m = _KILLS.search(command)
    if m:
        return (f"Not running that: it would kill {m.group(0).split()[-1]}, part of "
                "the desktop you share with them, and anything you restart from "
                "a command dies when the command ends. "
                + ("Use the desktop tool: action restart with component desktop, panel or wm."
                   if not THEIRS else
                   "If Cinnamon really needs restarting: cinnamon-dbus-command RestartCinnamon 1"))
    if THEIRS and _XRANDR.search(command):
        return ("Not running that: changing screen modes with xrandr leaves Cinnamon "
                "drawing at the old size, zoomed and cropped. Their layout lives in "
                "~/.config/cinnamon-monitors.xml and /usr/local/sbin/lab2-screens; leave "
                "it alone unless they ask, and then tell them what you'd change first.")
    return None


def apt_packages(command):
    """Package names in any apt install in the command."""
    names = []
    for m in _APT.finditer(command):
        for word in m.group(1).split():
            if word.startswith("-") or "/" in word or word.endswith(".deb") or "=" in word:
                continue
            if re.fullmatch(r"[a-z0-9][a-z0-9.+-]+", word):
                names.append(word)
    return names


def _missing_packages(names):
    if not names:
        return []
    check = " ".join(shlex.quote(n) for n in names)
    code, out = _ssh(f"for p in {check}; do apt-cache show \"$p\" >/dev/null 2>&1 || "
                     f"echo \"MISSING $p\"; done", timeout=30)
    return re.findall(r"^MISSING (\S+)", out, re.M)


_GENERIC = {"ttf", "otf", "font", "fonts", "lib", "dev", "data", "common", "theme",
            "themes", "icon", "icons", "python3", "gtk", "x11", "the"}


def _suggest(name):
    """Real packages close to a name that doesn't exist: all its distinctive
    words together first, then each on its own."""
    words = [w for w in re.split(r"[-.+]", name) if len(w) > 2 and w not in _GENERIC] or [name]
    for terms in [words] + [[w] for w in sorted(words, key=len, reverse=True)]:
        q = " ".join(shlex.quote(t) for t in terms)
        code, out = _ssh(f"apt-cache search --names-only {q} | head -6", timeout=30)
        if out.strip():
            return out.strip()
    return ""


def run_command(command, cwd="", timeout_seconds=None):
    command = (command or "").strip()
    if not command:
        return "No command given."
    why = refused(command)
    if why:
        print(f"[workspace] refused: {command[:100]}", flush=True)
        return why
    missing = _missing_packages(apt_packages(command))
    if missing:
        _log("command", command.splitlines()[0], False, f"no such package: {', '.join(missing)}")
        print(f"[workspace] refused apt install of {', '.join(missing)}", flush=True)
        hints = "\n".join(f"Closest to {m}:\n{_suggest(m) or '(nothing similar)'}" for m in missing)
        return (f"Nothing was run: {', '.join(missing)} "
                f"{'is' if len(missing) == 1 else 'are'} not a package on this machine, and "
                f"one wrong name fails the whole install. Use real names.\n{hints}")
    try:
        limit = min(float(timeout_seconds or TIMEOUT), 1800.0)
    except (TypeError, ValueError):
        limit = TIMEOUT
    where = _path(cwd) if cwd else _path(".")
    env = _SESSION_ENV if THEIRS else ""
    script = f"{env}mkdir -p {_path('.')} && cd {where} && {{ {command}\n}}\n"
    lines = command.splitlines()
    title = lines[0][:200] + (" …" if len(lines) > 1 or len(lines[0]) > 200 else "")
    print(f"[workspace] $ {command}", flush=True)
    # The timeout runs over there too, so a command that overruns is
    # actually stopped rather than left running after ssh gives up.
    runner = _RUNNER.format(title=shlex.quote(title), limit=int(limit))
    before = _maybe_restore_point(command)
    code, out = _ssh(f"bash -c {shlex.quote(runner)}", stdin=script, timeout=limit + 15)
    body = _clip(out) or "(no output)"
    if code == 124:
        body += (f"\n(stopped after {int(limit)} seconds. For anything that takes longer than "
                 "a couple of minutes, use start_job: it keeps going and tells you when it's done.)")
    _log("command", title, code == 0, "" if code == 0 else f"exit {code}: {_last_line(out)}")
    return f"{before}exit code {code}\n{body}"


# Runs the script on stdin, teeing it into the log the shared terminal shows.
_RUNNER = r"""set -o pipefail
log=~/.marina/terminal.log; mkdir -p ~/.marina
job=$(mktemp ~/.marina/job.XXXXXX); cat > "$job"
printf '\n\033[1;35mmarina\033[0m \033[2m%s\033[0m  \033[36m$\033[0m %s\n' "$(date +%H:%M:%S)" {title} >> "$log"
timeout --kill-after=5 {limit} bash -l "$job" < /dev/null 2>&1 | tee -a "$log"
code=${{PIPESTATUS[0]}}
rm -f "$job"
printf '\033[2m(exit %s)\033[0m\n' "$code" >> "$log"
if [ "$(stat -c %s "$log")" -gt 4000000 ]; then
  tail -c 1000000 "$log" > "$log.tmp" && mv "$log.tmp" "$log"
fi
exit "$code"
"""


def read_terminal(lines=60):
    """What is on screen in their half of the shared terminal."""
    try:
        lines = max(5, min(int(lines or 60), 400))
    except (TypeError, ValueError):
        lines = 60
    code, out = _ssh(f"tmux capture-pane -p -J -S -{lines} -t marina:work.1 2>&1")
    if code != 0:
        return ("The shared terminal isn't open. They can start it with "
                "marina-tmux on your machine.")
    print("[workspace] read their terminal", flush=True)
    return _clip(out.rstrip()) or "(their terminal is empty)"


def read_file(path, start_line=1, end_line=None):
    try:
        start = max(1, int(start_line or 1))
        end = int(end_line) if end_line else start + READ_LINES - 1
    except (TypeError, ValueError):
        return "start_line and end_line have to be numbers."
    code, out = _ssh(
        f"f={_path(path)}; test -f \"$f\" || {{ echo \"no such file: $f\"; exit 1; }}; "
        f"echo \"($(wc -l < \"$f\") lines)\"; "
        f"awk 'NR>={start} && NR<={end} {{ printf \"%5d  %s\\n\", NR, $0 }}' \"$f\"")
    print(f"[workspace] read {path} {start}-{end}", flush=True)
    return _clip(out) if code == 0 else out.strip()


def write_file(path, content):
    content = content if isinstance(content, str) else str(content or "")
    code, out = _ssh(f"f={_path(path)}; mkdir -p \"$(dirname \"$f\")\" && cat > \"$f\"",
                     stdin=content)
    if code != 0:
        return f"Could not write {path}: {out.strip()[:400]}"
    print(f"[workspace] wrote {path} ({len(content)} chars)", flush=True)
    return f"Wrote {path} ({len(content.splitlines())} lines)."


def edit_file(path, old_text, new_text):
    """Replace one exact, unique piece of a file."""
    code, current = _ssh(f"cat {_path(path)}")
    if code != 0:
        return f"Could not read {path}: {current.strip()[:400]}"
    count = current.count(old_text or "")
    if not old_text or count == 0:
        return "old_text was not found in the file. Read it again and copy the text exactly."
    if count > 1:
        return f"old_text appears {count} times. Include more surrounding lines so it is unique."
    result = write_file(path, current.replace(old_text, new_text or "", 1))
    return result.replace("Wrote", "Edited", 1) if result.startswith("Wrote") else result


LOOK_PROMPT_THEIRS = """This is a screenshot of {name}, their Linux Mint (Cinnamon)
PC, with both its screens side by side: the vertical Dell on the left and the
Acer on the right. Describe what is on it as plainly and accurately as you
can, for your own use: which windows are open on which screen and what is in
them, any dialogs or prompts waiting for an answer, and any text that
matters. Only describe what you can actually see. Plain sentences, no
markdown, under 150 words.{question}"""

LOOK_PROMPT = """This is a screenshot of your own Linux desktop (XFCE).
Describe what is on it as plainly and accurately as you can, for your own
use: which windows are open and what is in them, the theme, colours, panel,
icons, wallpaper and fonts, and any text that matters. Say what looks off
or unfinished. Only describe what you can actually see. Plain sentences,
no markdown, under 150 words.{question}"""


def screen_jpeg(full=False):
    """A fresh screenshot of the machine's screen as JPEG bytes, for the app
    to show what she is doing. Scaled to 40% unless full. None if it fails."""
    import base64

    thumb = "" if full else " -t 40"
    shot = "/tmp/marina-view.jpg" if full else "/tmp/marina-view-thumb.jpg"
    code, out = _ssh(f"export DISPLAY=:0; scrot -o -q 60{thumb} /tmp/marina-view.jpg >/dev/null 2>&1 && "
                     f"echo IMAGE-BEGIN && base64 -w0 {shot} && echo && echo IMAGE-END", timeout=20)
    if code != 0 or "IMAGE-BEGIN\n" not in out:
        return None
    try:
        return base64.b64decode(out.split("IMAGE-BEGIN\n", 1)[1].split("\nIMAGE-END", 1)[0].strip(),
                                validate=True)
    except Exception:
        return None


def stop_running():
    """Kill whatever command she has running there, for the app's Stop."""
    code, _ = _ssh("pkill -f '[.]marina/job[.]' || true", timeout=10)
    return code == 0


def look_at_desktop(question="", hide_windows=False):
    """Screenshot the desktop and have the model describe it."""
    import base64

    # Minimise every window for the shot and bring them back after, so the
    # wallpaper and panels can be seen past the maximised terminal.
    # Only ordinary app windows: the desktop, panels and window manager
    # are windows too, and minimising those derails the rest.
    hide = ("W=; for w in $(xprop -root _NET_CLIENT_LIST | grep -o '0x[0-9a-f]*'); do "
            "xprop -id $w _NET_WM_WINDOW_TYPE | grep -q _NET_WM_WINDOW_TYPE_NORMAL && "
            "{ W=\"$W $w\"; xdotool windowminimize $w; }; done; sleep 1; "
            if hide_windows else "")
    show = ("; for w in $W; do xdotool windowactivate $w 2>/dev/null; done; "
            "xdotool search --name '^Marina$' windowactivate 2>/dev/null; true"
            if hide_windows else "")
    code, out = _ssh(f"export DISPLAY=:0; {hide}scrot -o -q 80 /tmp/marina-screen.jpg 2>&1{show} && "
                     "echo; echo IMAGE-BEGIN; base64 -w0 /tmp/marina-screen.jpg; "
                     "echo; echo IMAGE-END", timeout=30)
    # Marked, because ssh's own warnings come back mixed in with the output.
    if code != 0 or "IMAGE-BEGIN\n" not in out:
        return f"Couldn't take a screenshot: {out.strip()[:300]}"
    image = out.split("IMAGE-BEGIN\n", 1)[1].split("\nIMAGE-END", 1)[0].strip()
    try:
        base64.b64decode(image, validate=True)
    except Exception:
        return "The screenshot came back garbled."
    ask = f"\n\nIn particular: {question.strip()}" if (question or "").strip() else ""

    # Imported here because the chat client imports this module.
    from process.llm_funcs import llm_scr

    try:
        reply = llm_scr.chat_completion(
            [{"role": "user", "content": [
                {"type": "text", "text": (LOOK_PROMPT_THEIRS.format(name=NAME, question=ask)
                                          if THEIRS else LOOK_PROMPT.format(question=ask))},
                {"type": "image_url",
                 "image_url": {"url": f"data:image/jpeg;base64,{image}"}},
            ]}],
            temperature=0.2, max_tokens=300)
    except Exception as e:
        msg = str(e).lower()
        if "image" in msg or "multimodal" in msg or "vision" in msg or "mmproj" in msg:
            return "Your current brain can't see images, so you can't look right now."
        return f"Looking failed: {type(e).__name__}: {str(e)[:200]}"
    print("[workspace] looked at the desktop", flush=True)
    return (reply.choices[0].message.content or "").strip() or "You couldn't make anything out."


_DESKTOP_SCRIPT = Path(__file__).resolve().parents[2] / "workspace" / "marina_desktop.py"


def desktop(action="status", settings=None, component=""):
    """Look up or change how the desktop looks, through a script that checks
    everything before applying it and keeps an undo point."""
    action = (action or "status").strip().lower()
    if action not in ("status", "set", "restart", "undo"):
        return "action must be status, set, restart or undo."
    args = settings if isinstance(settings, dict) else {}
    if action == "restart":
        args = {"component": component or args.get("component", "")}
    if action == "set" and not args:
        return "Nothing to set: pass settings, e.g. {\"gtk_theme\": \"Arc-Dark\"}."
    try:
        script = _DESKTOP_SCRIPT.read_text()
    except OSError as e:
        return f"The desktop script is missing: {e}"
    code, out = _ssh(f"DISPLAY=:0 python3 - {shlex.quote(action)} {shlex.quote(json.dumps(args))}",
                     stdin=script, timeout=90)
    print(f"[workspace] desktop {action} {json.dumps(args)[:120]}", flush=True)
    start = out.find("{")
    return _clip(out[start:] if start >= 0 else out) or "(no output)"


def list_files(path="", depth=2):
    try:
        depth = max(1, min(int(depth or 2), 5))
    except (TypeError, ValueError):
        depth = 2
    code, out = _ssh(
        f"cd {_path(path)} 2>/dev/null || {{ echo 'no such folder'; exit 1; }}; "
        f"find . -maxdepth {depth} -not -path '*/.git/*' -not -path '*/node_modules/*' "
        f"-not -path '*/.venv/*' -not -name '.git' | sort | head -300")
    return _clip(out) if code == 0 else out.strip()


# ---- what she did there, so she doesn't repeat what failed ---------------

_LOG_KEY = f"workspace_log_{NAME}"
_LOG_KEEP = 40


def _log(kind, what, ok, note=""):
    from process import state
    import time as _t
    try:
        entries = state.get(_LOG_KEY, []) or []
        entries.append({"at": _t.time(), "kind": kind, "what": str(what)[:160],
                        "ok": bool(ok), "note": str(note or "")[:160]})
        state.put(_LOG_KEY, entries[-_LOG_KEEP:])
    except Exception as e:
        print(f"[workspace] couldn't log: {e}", flush=True)


def _last_line(text):
    lines = [l.strip() for l in (text or "").splitlines() if l.strip()]
    return lines[-1] if lines else ""


def recent_note(limit=10):
    """Rides on her message when she's asked to do something on the machine:
    what she did there lately and whether it worked."""
    from process import state
    from datetime import datetime
    if not available():
        return ""
    entries = (state.get(_LOG_KEY, []) or [])[-limit:]
    if not entries:
        return ""
    lines = []
    for e in entries:
        when = datetime.fromtimestamp(e.get("at", 0)).strftime("%a %H:%M")
        mark = "ok" if e.get("ok") else "FAILED"
        note = f" ({e['note']})" if e.get("note") else ""
        lines.append(f"- {when} {e.get('kind')}: {e.get('what')} -> {mark}{note}")
    return (f"\n\n(What you did on {NAME} recently, newest last. Don't repeat something "
            "that already failed the same way; try something different or ask:\n"
            + "\n".join(lines) + ")")


# ---- mouse, keyboard, windows and apps (lab2) ----------------------------

_CONTROL_SCRIPT = Path(__file__).resolve().parents[2] / "workspace" / "lab2_control.py"


def _control(action, args=None, timeout=60):
    try:
        script = _CONTROL_SCRIPT.read_text()
    except OSError as e:
        return {"ok": False, "error": f"The control script is missing: {e}"}
    code, out = _ssh(f"python3 - {shlex.quote(action)} {shlex.quote(json.dumps(args or {}))}",
                     stdin=script, timeout=timeout)
    start = out.find('{"ok"')
    if start < 0:
        return {"ok": False, "error": (out.strip() or f"exit {code}")[:300]}
    try:
        return json.loads(out[start:].splitlines()[0])
    except ValueError:
        return {"ok": False, "error": out[start:start + 300]}


# Gemma finds things in images as boxes on a 0-1000 scale, so ask in that form.
LOCATE_PROMPT = """This is {what}. Detect: {target}

Output a JSON list with box_2d [ymin, xmin, ymax, xmax] normalised to 0-1000,
and label. Output [] if it isn't there."""


def _ask_where(shot, target, what):
    from process.llm_funcs import llm_scr
    try:
        reply = llm_scr.chat_completion(
            [{"role": "user", "content": [
                {"type": "text", "text": LOCATE_PROMPT.format(what=what, target=target)},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{shot['image']}"}},
            ]}], temperature=0.0, max_tokens=120)
        text = reply.choices[0].message.content or ""
    except Exception as e:
        return None, f"couldn't look: {type(e).__name__}"
    m = re.search(r"\[\s*(\d+(?:\.\d+)?)\s*,\s*(\d+(?:\.\d+)?)\s*,\s*(\d+(?:\.\d+)?)\s*,\s*(\d+(?:\.\d+)?)\s*\]", text)
    if not m:
        return None, "couldn't see it"
    y0, x0, y1, x1 = (float(v) for v in m.groups())
    if not (0 <= x0 <= x1 <= 1000 and 0 <= y0 <= y1 <= 1000):
        return None, "the box it gave doesn't make sense"
    cx = (x0 + x1) / 2000 * shot["image_width"]
    cy = (y0 + y1) / 2000 * shot["image_height"]
    # back to real screen pixels
    return (int(shot.get("left", 0) + cx / shot["scale"]), int(shot.get("top", 0) + cy / shot["scale"])), ""


def _locate(target):
    """Where something is on screen: its accessible name if the app says, else
    by eye, first on the whole screen and then close up around that spot."""
    found = _control("find", {"target": target})
    matches = found.get("matches") or []
    if matches:
        best = matches[0]
        return best["x"], best["y"], f"{best['role']} \"{best['name']}\""
    whole = _control("shot", {"scale": 0.4})
    if not whole.get("ok"):
        return None, None, whole.get("error", "no screenshot")
    spot, why = _ask_where(whole, target, f"a screenshot of {NAME}'s two screens side by side, shrunk")
    if not spot:
        return None, None, why
    close = _control("shot", {"scale": 1.0, "crop": [spot[0], spot[1], 200]})
    if close.get("ok"):
        fine, _ = _ask_where(close, target, f"a close-up of part of {NAME}'s screen, actual size")
        if fine:
            return fine[0], fine[1], "by eye"
    return spot[0], spot[1], "by eye, roughly"


def use_screen(action, x=None, y=None, target="", text="", keys="", direction="down",
               amount=5, button="left", double=False, to_x=None, to_y=None, window="",
               look=True):
    """One mouse or keyboard step on their desktop, then a look at the result."""
    import time as _t
    action = (action or "").strip().lower()
    simple = {"type": {"text": text}, "key": {"keys": keys},
              "scroll": {"direction": direction, "amount": amount, "x": x, "y": y},
              "focus": {"window": window or target},
              "move": {"x": x, "y": y},
              "drag": {"x": x, "y": y, "to_x": to_x, "to_y": to_y}}
    if action in ("screens", "windows"):
        res = _control(action)
        return json.dumps(res.get(action) if res.get("ok") else res)[:OUTPUT_CHARS]
    how = ""
    if action == "click":
        if (x is None or y is None) and target:
            x, y, how = _locate(target)
            if x is None:
                _log("click", target, False, how)
                return (f"Couldn't find {target!r} on screen ({how}). Look at the desktop, "
                        "then click by x and y, or focus the right window first.")
        if x is None or y is None:
            return "click needs x and y, or a target to find by name."
        res = _control("click", {"x": x, "y": y, "button": button, "double": double})
        what = f"{'double-' if double else ''}{button} click at {x},{y}" + (f" on {target}" if target else "")
    elif action in simple:
        res = _control(action, simple[action], timeout=150 if action == "type" else 60)
        what = {"type": f"typed {len(text or '')} characters", "key": f"pressed {keys}",
                "scroll": f"scrolled {direction}", "focus": f"focused {window or target}",
                "move": f"moved the mouse to {x},{y}", "drag": f"dragged {x},{y} to {to_x},{to_y}"}[action]
    else:
        return "action must be click, type, key, scroll, move, drag, focus, windows or screens."
    if not res.get("ok"):
        _log(action, what, False, res.get("error", ""))
        return f"That didn't work: {res.get('error')}" + (
            "\nOpen windows: " + "; ".join(res["windows"]) if res.get("windows") else "")
    print(f"[workspace] {what}{' (' + how + ')' if how else ''}", flush=True)
    _log(action, what, True, how)
    if not look or action in ("move",):
        return f"Done: {what}."
    _t.sleep(0.8)
    seen = look_at_desktop(f"I just did this: {what}. Did it work, and what is on screen now?")
    return f"Done: {what}{' (found ' + how + ')' if how else ''}.\nNow on screen: {seen}"


def open_app(name, screen=""):
    name = (name or "").strip()
    if not name:
        return "Say which app."
    res = _control("open_app", {"name": name, "screen": screen}, timeout=60)
    if not res.get("ok"):
        _log("open_app", name, False, res.get("error", ""))
        extra = f" Closest: {', '.join(res['suggestions'])}." if res.get("suggestions") else ""
        return f"Couldn't open {name}: {res.get('error')}{extra}"
    _log("open_app", f"{res['opened']}" + (f" on the {screen} screen" if screen else ""), True,
         res.get("note", ""))
    print(f"[workspace] opened {res['opened']}", flush=True)
    bits = [f"Opened {res['opened']}"]
    if res.get("screen"):
        bits.append(f"on the {res['screen']} screen")
    msg = " ".join(bits) + "."
    if res.get("note"):
        msg += " " + res["note"]
    if res.get("other_matches"):
        msg += f" (Other apps matching that name: {', '.join(res['other_matches'])}.)"
    return msg


def list_apps(query=""):
    res = _control("apps", {"query": query})
    if not res.get("ok"):
        return f"Couldn't list apps: {res.get('error')}"
    apps = res.get("apps") or []
    return "\n".join(f"{a['name']} ({a['id']})" for a in apps) or "No installed app matches that."


def place_window(window, screen, maximize=True):
    res = _control("place", {"window": window, "screen": screen, "maximize": maximize})
    if not res.get("ok"):
        return f"Couldn't move it: {res.get('error')}"
    _log("place", f"{res['placed']} to the {res['screen']} screen", True)
    return f"Moved {res['placed']} to the {res['screen']} screen."


# ---- long jobs that keep going after she replies --------------------------

_JOBS_KEY = f"workspace_jobs_{NAME}"
on_job_done = None          # set by the tool registry: how she gets told

_JOB_START = r"""d=~/.marina/jobs; mkdir -p "$d"
id=$(date +%m%d-%H%M%S)-$RANDOM
cat > "$d/$id.sh"
setsid -f bash -c 'echo $$ > "$4"; bash -l "$1" > "$2" 2>&1 < /dev/null; echo $? > "$3"' _ \
  "$d/$id.sh" "$d/$id.log" "$d/$id.exit" "$d/$id.pid" < /dev/null > /dev/null 2>&1
echo "JOB $id"
"""

_JOB_STATUS = r"""d=~/.marina/jobs
for id in "$@"; do
  if [ -f "$d/$id.exit" ]; then echo "=== $id done $(cat "$d/$id.exit")"; tail -n 12 "$d/$id.log"
  elif [ -f "$d/$id.pid" ] && kill -0 "$(cat "$d/$id.pid")" 2>/dev/null; then
    echo "=== $id running"; tail -n 4 "$d/$id.log"
  elif [ -f "$d/$id.sh" ]; then echo "=== $id starting"
  else echo "=== $id gone"; fi
done
"""


def _jobs():
    from process import state
    return [j for j in (state.get(_JOBS_KEY, []) or []) if isinstance(j, dict)]


def _save_jobs(jobs):
    from process import state
    state.put(_JOBS_KEY, jobs[-30:])


def _status(ids):
    if not ids:
        return {}
    code, out = _ssh(f"bash -s -- {' '.join(shlex.quote(i) for i in ids)}", stdin=_JOB_STATUS, timeout=30)
    result = {}
    for block in out.split("=== ")[1:]:
        head, _, body = block.partition("\n")
        parts = head.split()
        if len(parts) >= 2:
            result[parts[0]] = {"state": parts[1], "exit": parts[2] if len(parts) > 2 else None,
                                "tail": body.strip()}
    return result


def start_job(command, name="", cwd=""):
    """Start something long on the machine and come back to it later."""
    command = (command or "").strip()
    if not command:
        return "No command given."
    why = refused(command)
    if why:
        return why
    _maybe_restore_point(command)
    where = _path(cwd) if cwd else _path(".")
    env = _SESSION_ENV if THEIRS else ""
    script = f"{env}mkdir -p {_path('.')} && cd {where} && {{ {command}\n}}\n"
    code, out = _ssh(f"bash -c {shlex.quote(_JOB_START)}", stdin=script, timeout=30)
    m = re.search(r"JOB (\S+)", out)
    if not m:
        _log("job", name or command, False, _last_line(out))
        return f"Couldn't start it: {out.strip()[:300]}"
    import time as _t
    job = {"id": m.group(1), "name": (name or command.splitlines()[0])[:120],
           "command": command[:300], "started": _t.time(), "done": False}
    jobs = _jobs() + [job]
    _save_jobs(jobs)
    _watch()
    print(f"[workspace] started job {job['id']}: {job['name']}", flush=True)
    return (f"Started it in the background as job {job['id']} ({job['name']}). It keeps "
            "going after you reply; you'll be told when it finishes, and job_status "
            "shows how it's doing.")


def job_status(job_id=""):
    jobs = _jobs()
    if job_id:
        jobs = [j for j in jobs if j["id"] == job_id]
        if not jobs:
            return f"No job {job_id}."
    else:
        jobs = jobs[-6:]
    if not jobs:
        return "No jobs started yet."
    st = _status([j["id"] for j in jobs])
    lines = []
    for j in jobs:
        s = st.get(j["id"], {})
        state_ = s.get("state", "unknown")
        head = f"{j['id']} {j['name']}: {state_}" + (f", exit {s['exit']}" if s.get("exit") else "")
        lines.append(head + (f"\n{s['tail']}" if s.get("tail") else ""))
    return _clip("\n\n".join(lines))


def stop_job(job_id):
    jobs = _jobs()
    if not any(j["id"] == job_id for j in jobs):
        return f"No job {job_id}."
    code, out = _ssh(f"p=$(cat ~/.marina/jobs/{shlex.quote(job_id)}.pid 2>/dev/null) && "
                     f"kill -TERM -- -$p 2>/dev/null; sleep 1; kill -0 $p 2>/dev/null && kill -KILL -- -$p; "
                     f"echo 143 > ~/.marina/jobs/{shlex.quote(job_id)}.exit; echo stopped", timeout=20)
    for j in jobs:
        if j["id"] == job_id:
            j["done"] = True
            j["stopped"] = True
    _save_jobs(jobs)
    _log("job", f"stopped {job_id}", True)
    return f"Stopped job {job_id}."


def check_jobs():
    """Look at running jobs once; say so for each that has finished.
    Returns how many are still running."""
    import time as _t
    jobs = _jobs()
    running = [j for j in jobs if not j.get("done")]
    if not running:
        return 0
    st = _status([j["id"] for j in running])
    changed = False
    for j in running:
        s = st.get(j["id"])
        if not s or s["state"] not in ("done", "gone"):
            continue
        j["done"] = True
        j["exit"] = s.get("exit")
        changed = True
        ok = s.get("exit") == "0"
        took = max(1, round((_t.time() - j.get("started", _t.time())) / 60))
        _log("job", j["name"], ok, f"exit {s.get('exit')}, {took} min"
             + ("" if ok else f": {_last_line(s.get('tail'))}"))
        print(f"[workspace] job {j['id']} finished: exit {s.get('exit')}", flush=True)
        if on_job_done:
            on_job_done(
                f"A job you started on {NAME} in the background just finished: "
                f"{j['name']}. It took about {took} minute{'s' if took != 1 else ''} and "
                f"exited with {s.get('exit')} ({'worked' if ok else 'something went wrong'}). "
                f"Its last output:\n{(s.get('tail') or '(nothing)')[-1200:]}\n"
                "Tell them how it went in a sentence or two, in your own words: "
                "what finished, and if it failed, what failed.")
    if changed:
        _save_jobs(jobs)
    return sum(1 for j in jobs if not j.get("done"))


_watching = False


def _watch():
    """One thread that checks on running jobs and says when each finishes."""
    global _watching
    import threading
    import time as _t
    if _watching:
        return
    _watching = True

    def loop():
        global _watching
        while True:
            _t.sleep(20)
            try:
                if not check_jobs():
                    _watching = False
                    return
            except Exception as e:
                print(f"[workspace] job watch: {type(e).__name__}: {e}", flush=True)

    threading.Thread(target=loop, daemon=True).start()


def resume_watching():
    """After a restart, keep watching jobs that were still running."""
    if available() and any(not j.get("done") for j in _jobs()):
        _watch()


# ---- restore points (Timeshift) ------------------------------------------

_RISKY = re.compile(
    r"\bapt(?:-get)?\s+(?:-\S+\s+)*(?:full-upgrade|dist-upgrade|upgrade|remove|purge|autoremove)\b"
    r"|\bdpkg\s+(?:-r|-P|--remove|--purge)\b|\bupdate-grub\b|\bgrub-install\b|\bmintupgrade\b"
    r"|\bdo-release-upgrade\b|\bsystemctl\s+(?:disable|mask)\b|\bmkinitramfs|\bupdate-initramfs\b"
    r"|\brm\s+-\w*r\w*\s+/(?:etc|usr|boot|var|opt|lib)\b"
    r"|\btee\s+(?:-a\s+)?/etc/|\bsed\s+-i\S*\s[^|;&]*\s/etc/|>>?\s*/etc/", re.I)
_RP_KEY = f"workspace_restore_point_{NAME}"
RP_EVERY = float(_cfg.get("restore_point_hours", 3)) * 3600
RP_KEEP = int(_cfg.get("restore_points_kept", 5))


def restore_points():
    code, out = _ssh("sudo -n timeshift --list 2>&1", timeout=60)
    if code != 0:
        return f"Couldn't list restore points: {out.strip()[:300]}"
    rows = [l for l in out.splitlines() if re.match(r"^\d+\s+>", l)]
    return "Restore points (Timeshift), oldest first:\n" + ("\n".join(rows) or "(none)")


def make_restore_point(comment=""):
    """A Timeshift snapshot of the system, to roll back to if something breaks."""
    import time as _t
    if not THEIRS:
        return "Restore points are for lab2."
    comment = re.sub(r"[^\w .,:/+-]", "", (comment or "before changes"))[:80]
    print(f"[workspace] taking a restore point: {comment}", flush=True)
    code, out = _ssh(f"sudo -n timeshift --create --comments {shlex.quote('marina: ' + comment)} --tags O 2>&1",
                     timeout=1800)
    ok = code == 0 and "error" not in out.lower()[-300:]
    _log("restore point", comment, ok, "" if ok else _last_line(out))
    if not ok:
        return f"The restore point failed: {_clip(out)[-600:]}"
    from process import state
    state.put(_RP_KEY, _t.time())
    _prune_restore_points()
    name = re.search(r"Tagged snapshot '([^']+)'|Snapshot saved successfully.*?\(?(\d{4}-\d\d-\d\d_\d\d-\d\d-\d\d)", out)
    return ("Took a restore point" + (f" ({next(g for g in name.groups() if g)})" if name else "")
            + f": {comment}. To roll back, they run Timeshift (or sudo timeshift --restore) and pick it.")


def _prune_restore_points():
    """Only hers, and only past the newest few: theirs are never touched."""
    code, out = _ssh("sudo -n timeshift --list 2>&1", timeout=60)
    mine = re.findall(r"^\d+\s+>\s+(\S+)\s+\S*\s+marina: ", out, re.M)
    for snap in mine[:-RP_KEEP] if len(mine) > RP_KEEP else []:
        _ssh(f"sudo -n timeshift --delete --snapshot {shlex.quote(snap)} 2>&1", timeout=600)
        print(f"[workspace] removed her old restore point {snap}", flush=True)


def _maybe_restore_point(command):
    """Before anything that changes the system, a fresh restore point."""
    import time as _t
    from process import state
    if not THEIRS or not _RISKY.search(command):
        return ""
    last = float(state.get(_RP_KEY, 0) or 0)
    if _t.time() - last < RP_EVERY:
        return ""
    first = command.strip().splitlines()[0][:60]
    result = make_restore_point(f"before {first}")
    return result + "\n\n"


def describe(name, args):
    """A few words on what a call is about to do, for the app to show."""
    def path():
        return args.get("path") or "projects"
    if name == "use_screen":
        a = args.get("action", "")
        return {"click": f"clicking {args.get('target') or 'on the screen'}",
                "type": "typing", "key": f"pressing {args.get('keys', 'a key')}",
                "scroll": "scrolling", "focus": f"switching to {args.get('window') or args.get('target')}",
                "drag": "dragging"}.get(a, "using the mouse and keyboard")
    if name == "open_app":
        return f"opening {args.get('name', 'an app')}"
    if name == "start_job":
        return f"starting {args.get('name') or 'a long job'} in the background"
    if name == "make_restore_point":
        return "taking a restore point"
    if name == "run_command":
        line = (args.get("command") or "").strip().splitlines()
        return f"running `{line[0][:70]}`" if line else "running a command"
    if name == "desktop":
        action = args.get("action", "status")
        if action == "set":
            return "changing her desktop: " + ", ".join((args.get("settings") or {}).keys())
        if action == "restart":
            return f"restarting her {args.get('component') or 'desktop'}"
        if action == "undo":
            return "undoing her last desktop change"
        return "checking her desktop settings"
    return {
        "read_file": f"reading {path()}",
        "write_file": f"writing {path()}",
        "edit_file": f"editing {path()}",
        "list_files": f"looking through {path()}",
        "look_at_desktop": f"looking at {NAME}'s screen" if THEIRS else "looking at her screen",
        "read_terminal": "reading your shell in her terminal",
    }.get(name)


SPECS = [
    ("run_command", run_command, {
        "description": "Run a bash command on your own Linux machine (Debian, "
                       "with git, python3, node, ripgrep and passwordless sudo). "
                       "It starts in your projects folder unless you give cwd. "
                       "Use it to actually do the work when they want something "
                       "built, run, tested, installed or investigated, and to "
                       "check your work afterwards. Output is returned to you, "
                       "not shown to them.",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "cwd": {"type": "string", "description": "Folder to run in, relative to projects or absolute."},
                "timeout_seconds": {"type": "number"},
            },
            "required": ["command"],
        }}),
    ("read_terminal", read_terminal, {
        "description": "Read their shell in the terminal you share on your "
                       "machine: the commands they ran and what came back. "
                       "Use it when they mention something they ran, an "
                       "error they got, or ask you to look at their terminal.",
        "parameters": {
            "type": "object",
            "properties": {
                "lines": {"type": "integer", "description": "How far back to read."},
            },
        }}),
    ("look_at_desktop", look_at_desktop, {
        "description": "Take a screenshot of your machine's desktop and look "
                       "at it. Call it whenever they ask what your desktop or "
                       "screen looks like or what is on it, and after you "
                       "change how it looks, so you answer from what you "
                       "actually see.",
        "parameters": {
            "type": "object",
            "properties": {
                "question": {"type": "string",
                             "description": "What you want to check, if anything in particular."},
                "hide_windows": {"type": "boolean",
                                 "description": "Minimise the windows for the screenshot, to "
                                                "see the wallpaper and panels behind them."},
            },
        }}),
    ("desktop", desktop, {
        "description": "See or change how your desktop looks. Use this, not "
                       "run_command, for themes, icons, window borders, "
                       "wallpaper, desktop icons, the dock and the terminal's "
                       "font and colours. It checks every value before applying "
                       "it, reports what it changed and any errors, and saves an "
                       "undo point first. Actions: status (what is set and what "
                       "is installed), set, restart (component desktop, panel or "
                       "wm, safely), undo (back to before the last set).",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["status", "set", "restart", "undo"]},
                "settings": {
                    "type": "object",
                    "description": "For set. Any of: gtk_theme, wm_theme (defaults to "
                                   "match gtk_theme), icon_theme, wallpaper (a file path "
                                   "or an http(s) image URL to download), wallpaper_style "
                                   "(none, centered, tiled, stretched, scaled, zoomed), "
                                   "desktop_icons (true/false), ui_font (e.g. \"Inter 10\"), "
                                   "terminal_font (e.g. \"JetBrains Mono 12\"), "
                                   "terminal_background, terminal_foreground, "
                                   "terminal_cursor (#rrggbb), terminal_palette (16 "
                                   "#rrggbb colours), panel_autohide ({\"2\": \"never\"}; "
                                   "never, intelligent or always).",
                },
                "component": {"type": "string", "enum": ["desktop", "panel", "wm"],
                              "description": "For restart."},
            },
            "required": ["action"],
        }}),
    ("read_file", read_file, {
        "description": "Read a file on your machine with line numbers. Read before you edit.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "start_line": {"type": "integer"},
                "end_line": {"type": "integer"},
            },
            "required": ["path"],
        }}),
    ("write_file", write_file, {
        "description": "Create or overwrite a whole file on your machine.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        }}),
    ("edit_file", edit_file, {
        "description": "Change part of a file on your machine: replace old_text, "
                       "which must appear exactly once, with new_text.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "old_text": {"type": "string"},
                "new_text": {"type": "string"},
            },
            "required": ["path", "old_text", "new_text"],
        }}),
    ("list_files", list_files, {
        "description": "List the files under a folder on your machine.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "depth": {"type": "integer"},
            },
        }}),
]

SPECS += [
    ("start_job", start_job, {
        "description": "Start a long-running command in the background: big installs, "
                       "updates, builds, downloads, anything over a couple of minutes. "
                       "It keeps going after you reply, and you are told when it finishes "
                       "so you can tell them. Use run_command for quick things.",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "name": {"type": "string", "description": "A few words for what it is, e.g. 'system update'."},
                "cwd": {"type": "string"},
            },
            "required": ["command"],
        }}),
    ("job_status", job_status, {
        "description": "How your background jobs are doing: running or finished, exit "
                       "code, and the last lines of output. Leave job_id empty for all recent ones.",
        "parameters": {"type": "object", "properties": {"job_id": {"type": "string"}}}}),
    ("stop_job", stop_job, {
        "description": "Stop one of your background jobs.",
        "parameters": {"type": "object", "properties": {"job_id": {"type": "string"}},
                       "required": ["job_id"]}}),
]

_THEIRS_SPECS = [
    ("use_screen", use_screen, {
        "description": "Use lab2's mouse and keyboard, one step at a time. After each step "
                       "you are shown what is on screen, so you can check it worked before "
                       "the next. Actions: click (x and y, or target: a button, link or "
                       "field described by its name or what it looks like, which is found "
                       "for you), type (text into whatever has focus), key (keys in xdotool "
                       "form: ctrl+l, Return, Tab, alt+F4, super; several separated by "
                       "spaces), scroll (direction, amount, optional x y), drag (x y to_x "
                       "to_y), move, focus (window: part of its title or app name), windows "
                       "(list the open windows and where they are), screens (the monitors). "
                       "Screen coordinates: the Dell is x 0-1079, y 0-1919 (portrait, left); "
                       "the Acer is x 1080-2999, y 0-1079 (right).",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["click", "type", "key", "scroll", "drag",
                                                      "move", "focus", "windows", "screens"]},
                "x": {"type": "integer"}, "y": {"type": "integer"},
                "target": {"type": "string", "description": "For click: what to click, by name or look."},
                "text": {"type": "string"}, "keys": {"type": "string"},
                "direction": {"type": "string", "enum": ["up", "down", "left", "right"]},
                "amount": {"type": "integer"},
                "button": {"type": "string", "enum": ["left", "right", "middle"]},
                "double": {"type": "boolean"},
                "to_x": {"type": "integer"}, "to_y": {"type": "integer"},
                "window": {"type": "string"},
                "look": {"type": "boolean", "description": "Look at the screen afterwards (default true)."},
            },
            "required": ["action"],
        }}),
    ("open_app", open_app, {
        "description": "Open an installed app on lab2 by name (Spotify, Discord, Firefox, "
                       "Files, the Room of AIs web app, ...), optionally on one screen: "
                       "left (the vertical Dell) or right (the Acer), maximised there. If "
                       "it's already open it's brought up. Use this rather than starting "
                       "apps by hand.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "screen": {"type": "string", "enum": ["left", "right", "dell", "acer"]},
            },
            "required": ["name"],
        }}),
    ("list_apps", list_apps, {
        "description": "Find installed apps on lab2 whose name matches.",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}}}}),
    ("place_window", place_window, {
        "description": "Move an open window on lab2 to the left (Dell) or right (Acer) screen.",
        "parameters": {
            "type": "object",
            "properties": {
                "window": {"type": "string", "description": "Part of its title or app name."},
                "screen": {"type": "string", "enum": ["left", "right", "dell", "acer"]},
                "maximize": {"type": "boolean"},
            },
            "required": ["window", "screen"],
        }}),
    ("make_restore_point", make_restore_point, {
        "description": "Take a Timeshift restore point of lab2's system before something "
                       "risky, so it can be rolled back. One is taken for you automatically "
                       "before upgrades, removals and system config edits; call this for "
                       "anything else that could break the system. Takes a few minutes.",
        "parameters": {"type": "object", "properties": {"comment": {"type": "string"}}}}),
    ("restore_points", restore_points, {
        "description": "List lab2's Timeshift restore points.",
        "parameters": {"type": "object", "properties": {}}}),
]

_THEIRS_RUN = ("Run a bash command on lab2, their Linux Mint PC, as their account "
               "(jacob) with passwordless sudo. Commands can reach their desktop "
               "session: start apps with `setsid -f app >/dev/null 2>&1` so they keep "
               "running, use xdotool and wmctrl for the mouse, keyboard and windows, "
               "playerctl for Spotify, notify-send to pop up a note. It starts in "
               "~/projects unless you give cwd. Output is returned to you, not shown "
               "to them.")

if THEIRS:
    SPECS = [(n, f, s) for n, f, s in SPECS if n not in ("read_terminal", "desktop")] + _THEIRS_SPECS
    for n, f, s in SPECS:
        if n == "run_command":
            s["description"] = _THEIRS_RUN
        elif n == "look_at_desktop":
            s["description"] = ("Take a screenshot of lab2's two screens and look at it. "
                                "Call it before and after using the mouse or keyboard there, "
                                "and whenever they ask what is on lab2's screen, so you "
                                "answer from what you actually see.")
        else:
            s["description"] = s["description"].replace("your machine", "lab2")

PROMPT_THEIRS = """

You can use lab2, their Linux Mint (Cinnamon) PC, with run_command,
read_file, write_file, edit_file, list_files and look_at_desktop. You use
it as them (the jacob account) with sudo, so you can install, change and
run anything. It is their PC, not yours: they sit at it, so treat it the
way a trusted friend would treat someone's computer they were handed. What
is on it and on its screens only ever comes from your tools, never from
imagination. Its screens: a vertical Dell on the left (the main one) and
an Acer on the right that is often switched to a PS5 or another laptop.

How to use it without breaking it:
- Apps: open_app by name (and screen left or right), place_window to move
  one. To use an app, look_at_desktop first, then use_screen one step at a
  time (click a target by name, type, key, scroll); each step shows you
  the screen afterwards, so check it did what you meant before the next.
- Anything that takes more than a couple of minutes (updates, big
  installs, builds) goes through start_job, not run_command: it keeps
  going, and you are told when it finishes so you can tell them.
- A restore point is taken for you before upgrades, removals and system
  config edits; make_restore_point for anything else risky.
- Music is Spotify (flatpak com.spotify.Client): playerctl -p spotify
  play/pause/next, or open_app Spotify if it isn't running.
- Don't touch the screen layout, the theme or the login screen unless they
  ask; run_command refuses xrandr mode changes.
- Ask them before anything that's hard to undo there: deleting their
  files, reboots or shutdowns, removing packages, changing network or
  firewall settings. Updates (apt upgrade, flatpak update) are fine when
  they ask. If something goes badly wrong, tell them which restore point
  to roll back to (restore_points lists them); never restore one yourself.
- Don't kill cinnamon, muffin or lightdm; run_command refuses.
- If something fails twice the same way, stop and rethink instead of
  trying variations."""

PROMPT = """

You have your own Linux computer, marina-workspace, and tools to use it.
It is real, unlike the made-up details of your life: what is on it, what
its desktop looks like and what happened on it only ever come from your
tools, never from imagination. The tools are run_command, read_file,
write_file, edit_file, list_files, desktop and look_at_desktop. It is yours; you keep your projects
in ~/projects. You share a terminal there with them:
your commands scroll past at the top while they watch, and the shell
underneath is theirs, which you can read with read_terminal. It also has
a desktop, XFCE on display :0, that they look at over RustDesk; it is
yours to arrange with the desktop tool. You can see it:
look_at_desktop takes a screenshot and shows it to you. You don't know
what is on that screen until you look, so whenever they ask about your
desktop, or you have just changed how it looks, call look_at_desktop first
and answer from what you saw. Never describe it from memory or make it up.

How to work on this machine without breaking it:
- Anything about how the desktop looks goes through the desktop tool, not
  hand-made xfconf-query commands: it knows the real monitor name, which
  themes are installed and where each setting lives, and it can undo.
  Start with desktop status to see what is there.
- Install things with apt, but check names first (apt search); run_command
  refuses an install with a package that doesn't exist.
- Don't kill or restart desktop programs from commands; run_command
  refuses, and desktop restart does it safely.
- After a visible change, look_at_desktop (hide_windows true to see past
  the terminal) and judge it yourself. If it looks wrong, desktop undo.
- If something fails twice the same way, stop and rethink instead of
  trying variations."""

if THEIRS:
    PROMPT = PROMPT_THEIRS
