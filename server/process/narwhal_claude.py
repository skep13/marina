"""Claude as one of Narwhal's models, run on lab3 so the phone and the Mac can
both use it and watch it live.

It is Anthropic's own Claude Code CLI (`claude -p`), signed in once with the
owner's Claude subscription. It runs as its own user, narwhal-claude, through
a one-command sudo rule (/etc/sudoers.d/narwhal-claude), so it works in
/var/lib/narwhal-claude/work and can't read Marina's data or tokens.

events() turns Claude Code's stream-json into Narwhal's reply events: what
it says becomes "text", and the steps it takes (tools, thinking) become
"think", so every app shows them like any other model's reasoning.
"""

import json
import os
import queue
import subprocess
import threading
import time

WRAPPER = "/usr/local/bin/narwhal-claude"
CMD = ["sudo", "-n", "-u", "narwhal-claude", "-H", WRAPPER]
HOME = "/var/lib/narwhal-claude"
MODES = ("acceptEdits", "bypassPermissions", "plan")
MODELS = ("", "opus", "sonnet", "haiku", "fable")
EFFORTS = ("", "low", "medium", "high", "xhigh", "max")
# Claude on lab3 works in a sandbox there; the owner's projects are on the Mac.
SANDBOX_NOTE = ("You are running on lab3, a homelab server, in a sandbox folder; you can't reach the "
                "user's Mac. Their files and projects are on their Mac. When they ask about their files, "
                "code or folders, don't look for them here: give them the commands, diffs or file "
                "contents to use on the Mac (macOS, zsh). Use this sandbox only for scratch work, like "
                "trying code out. On the Narwhal Mac app they can switch Claude to run on the Mac itself.")
# One Claude run at a time on lab3: RAM is tight there.
LOCK = threading.Lock()


def available():
    return os.path.exists(WRAPPER)


def label(model):
    for m in MODELS[1:]:
        if m in (model or ""):
            return "Claude · " + m.capitalize()
    return "Claude"


def _arg(inp):
    inp = inp or {}
    v = next((inp[k] for k in ("command", "file_path", "notebook_path", "pattern", "url", "query",
                                "description", "path") if inp.get(k)), "")
    return str(v).replace(HOME + "/work", "~").split("\n")[0][:160]


def plan_usage(info, at=None):
    """Claude Code's rate_limit_info -> what the apps show: how much of each
    plan window is used (0..1) and when it resets (unix seconds)."""
    if not isinstance(info, dict):
        return None
    wins = {}
    for name, w in (info.get("unifiedWindows") or {}).items():
        if isinstance(w, dict) and isinstance(w.get("utilization"), (int, float)):
            wins[str(name)[:40]] = {"used": max(0.0, min(1.0, float(w["utilization"]))),
                                    "resets": int(w.get("resetsAt") or 0) or None,
                                    "status": str(w.get("status") or "")[:20]}
    if not wins:
        return None
    return {"at": int(at or time.time()), "status": str(info.get("status") or "")[:20], "windows": wins}


def _sign_in_hint(msg):
    if any(w in (msg or "").lower() for w in ("authenticat", "log in", "login", "sign in")):
        return "Claude Code on lab3 isn't signed in. Run: sudo -u narwhal-claude -H narwhal-claude auth login"
    return msg


def events(prompt, session="", mode="acceptEdits", model="", system="", cancel=None,
           popen=subprocess.Popen, effort=""):
    """Yields {"type": "session", "id"} once Claude Code names its session,
    {"type": "usage", ...} when it reports the plan's limits, then
    "think"/"text" events, then one of done/stopped/error."""
    if mode not in MODES:
        mode = "acceptEdits"
    if model not in MODELS:
        model = ""
    args = CMD + ["-p", "--output-format", "stream-json", "--verbose", "--include-partial-messages",
                  "--permission-mode", mode]
    if model:
        args += ["--model", model]
    if effort in EFFORTS[1:]:
        args += ["--effort", effort]
    if session and all(c.isalnum() or c == "-" for c in session):
        args += ["--resume", session]
    if system:
        args += ["--append-system-prompt", system]
    started = time.monotonic()
    try:
        proc = popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                     text=True, start_new_session=True)
    except OSError as e:
        yield {"type": "error", "message": f"Couldn't start Claude Code on lab3: {e}"}
        return
    try:
        proc.stdin.write(prompt)
        proc.stdin.close()
    except OSError:
        pass

    lines, err = queue.Queue(), []
    threading.Thread(target=lambda: [lines.put(l) for l in proc.stdout] + [lines.put(None)],
                     daemon=True).start()
    threading.Thread(target=lambda: err.extend(proc.stderr), daemon=True).start()

    said = False          # some text already went out (so a new block gets a gap)
    first = None
    result = None
    while True:
        if cancel and cancel():
            proc.terminate()
            try:
                proc.wait(5)
            except subprocess.TimeoutExpired:
                proc.kill()
            yield {"type": "stopped", "seconds": round(time.monotonic() - started, 1)}
            return
        try:
            line = lines.get(timeout=0.5)
        except queue.Empty:
            continue
        if line is None:
            break
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        kind = ev.get("type")
        if kind == "system" and ev.get("subtype") == "init":
            if ev.get("session_id"):
                yield {"type": "session", "id": ev["session_id"], "model": ev.get("model") or ""}
        elif kind == "stream_event":
            e = ev.get("event") or {}
            if e.get("type") == "content_block_start" and (e.get("content_block") or {}).get("type") == "text" and said:
                yield {"type": "text", "text": "\n\n"}
            d = e.get("delta") or {}
            if d.get("type") == "text_delta" and d.get("text"):
                first = first or time.monotonic()
                said = True
                yield {"type": "text", "text": d["text"]}
            elif d.get("type") == "thinking_delta" and d.get("thinking"):
                yield {"type": "think", "text": d["thinking"]}
        elif kind == "assistant":
            for b in (ev.get("message") or {}).get("content") or []:
                if b.get("type") == "tool_use":
                    yield {"type": "think", "text": f"\n▸ {b.get('name')}  {_arg(b.get('input'))}\n"}
        elif kind == "user":
            for b in (ev.get("message") or {}).get("content") or []:
                if b.get("type") == "tool_result" and b.get("is_error"):
                    c = b.get("content")
                    msg = " ".join(x.get("text", "") for x in c) if isinstance(c, list) else str(c or "")
                    yield {"type": "think", "text": f"  ✗ {msg.splitlines()[0][:160] if msg else 'failed'}\n"}
        elif kind == "rate_limit_event":
            u = plan_usage(ev.get("rate_limit_info"))
            if u:
                yield {"type": "usage", **u}
        elif kind == "result":
            result = ev
            if ev.get("session_id"):
                yield {"type": "session", "id": ev["session_id"]}
    proc.wait()
    seconds = round(time.monotonic() - started, 1)
    if not result:
        tail = "".join(err).strip().splitlines()[-3:]
        yield {"type": "error", "seconds": seconds,
               "message": _sign_in_hint("\n".join(tail)) or f"Claude Code exited ({proc.returncode})."}
        return
    u = result.get("usage") or {}
    end = {"seconds": round((result.get("duration_ms") or seconds * 1000) / 1000, 1),
           "completion_tokens": u.get("output_tokens"),
           "prompt_tokens": (u.get("input_tokens") or 0) + (u.get("cache_read_input_tokens") or 0)
           + (u.get("cache_creation_input_tokens") or 0) or None}
    denied = sorted({d.get("tool_name") for d in result.get("permission_denials") or [] if d.get("tool_name")})
    if denied:
        yield {"type": "text", "text": ("\n\n" if said else "") + f"*Claude wasn't allowed to use "
               f"{', '.join(denied)}. Pick “Edit + run commands” to let it, then ask again.*"}
    if result.get("is_error") or result.get("subtype") not in (None, "success"):
        yield {"type": "error", **end, "message": _sign_in_hint(str(result.get("result") or result.get("subtype")))}
        return
    yield {"type": "done", **end}
