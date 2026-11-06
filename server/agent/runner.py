"""A Claude-Code-style agent loop for Marina and Songbird, driving this Mac.

It talks straight to lab3's llama-swap (not the chat bridge), runs the
OpenAI tool-call loop, and gives the model the same Mac toolset Marina's
bridge has: shell, files, the screen and mouse/keyboard, and the web. Each
persona's tool policy comes from personas.py.

  marina-do "find every TODO in ~/marina and summarise them"
  songbird-do "check which listening ports are open and what owns them"
  marina-do --steps 20 --dry-run "..."         # show tools, make no changes

Safety that is always on, whatever the persona:
- every tool call is printed and appended to ~/.marina/agent-<persona>.log
- a stop file (~/.marina/agent.stop) halts the loop between steps; so does Ctrl-C
- a step cap (persona.policy.max_steps, or --steps)

The lab3 key is NOT read from the repo. Set it in the environment or in a
git-ignored keys file (see KEYS_FILE), per persona (MARINA_LAB3_KEY /
SONGBIRD_LAB3_KEY).
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

# Reuse the bridge's tested Mac tools. They live under server/process.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from process.tools import mac          # noqa: E402
from process.tools import lookup       # noqa: E402

from agent.personas import PERSONAS, LAB3_BASE_URL  # noqa: E402

# Both personas now have a vision projector, so screenshots and the
# click-by-description lookups inside the Mac tools use the running persona's
# own model (set per run) — no model-swap to borrow Marina's eyes.
_VISION_MODEL = "marina"  # overwritten per run with the persona's model
_VISION_KEY = None        # set when a run starts; used by the mac._vision override

# Local cybersecurity RAG endpoint (deployed on lab3, behind the ai.local proxy).
RAG_URL = os.environ.get("AGENT_RAG_URL", "http://ai.local/rag")
RAG_HOST_HEADER = os.environ.get("AGENT_RAG_HOST", "ai.local")

STATE = Path.home() / ".marina"
STOP_FILE = STATE / "agent.stop"
KEYS_FILE = STATE / "agent-keys.env"   # git-ignored; KEY=VALUE per line
HOME = Path.home()


class Refused(Exception):
    pass


class Stopped(Exception):
    pass


# --- key loading -------------------------------------------------------------

def load_key(persona):
    key = os.environ.get(persona.key_env)
    if not key and KEYS_FILE.exists():
        for line in KEYS_FILE.read_text().splitlines():
            m = re.match(r"\s*(?:export\s+)?([A-Z0-9_]+)\s*=\s*(.*)", line)
            if m and m.group(1) == persona.key_env:
                key = m.group(2).strip().strip("'\"")
    if not key:
        sys.exit(f"{persona.name}: no lab3 key. Set {persona.key_env} in the "
                 f"environment or in {KEYS_FILE} (KEY=VALUE, chmod 600).")
    return key


# --- the file-path guard, varied by policy ----------------------------------

def guard_path(path, policy, write=False):
    p = Path(os.path.expanduser((path or "").strip() or "~"))
    if not p.is_absolute():
        p = HOME / p
    p = p.resolve()
    if policy.confine_home and p != HOME and HOME not in p.parents:
        raise Refused(f"{p} is outside the home folder")
    if policy.shield_secrets:
        for secret in mac._SECRET_PATHS:
            if p == secret or secret in p.parents:
                raise Refused("that path holds keys or passwords; it's shielded "
                              "(set shield_secrets False to lift this)")
    return p


# --- tools -------------------------------------------------------------------
# Each takes (ctx, **args) and returns a string. ctx carries the policy.

class Ctx:
    def __init__(self, persona, key, dry_run):
        self.persona = persona
        self.policy = persona.policy
        self.key = key
        self.dry_run = dry_run


def t_run_command(ctx, command, cwd=""):
    command = (command or "").strip()
    if not command:
        return "No command given."
    pol = ctx.policy
    if pol.shield_secrets and mac._SECRET_COMMANDS.search(command):
        raise Refused("that command reaches into keys or passwords (shielded)")
    if pol.block_ui_commands and mac._UI_COMMANDS.search(command):
        raise Refused("that drives apps or macOS permissions behind the user's back; "
                      "use the click/type/key tools instead")
    if pol.block_risky and mac._RISKY.search(command):
        raise Refused("that's a destructive or irreversible command and this persona "
                      "isn't allowed to run those; tell the user to run it themselves")
    where = str(guard_path(cwd or "~", pol)) if (cwd or pol.confine_home) else None
    if ctx.dry_run:
        return f"[dry-run] would run: {command}" + (f" (in {where})" if where else "")
    proc = subprocess.Popen(["/bin/zsh", "-lc", command], cwd=where or None,
                            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, start_new_session=True)
    try:
        out, _ = proc.communicate(timeout=1800)
        code = proc.returncode
    except subprocess.TimeoutExpired:
        import signal
        os.killpg(proc.pid, signal.SIGKILL)
        out, _ = proc.communicate()
        code, out = 124, (out or "") + "\n(stopped after 1800 seconds)"
    return f"exit code {code}\n{mac._clip(out) or '(no output)'}"


def t_read_file(ctx, path, start_line=1, end_line=None):
    p = guard_path(path, ctx.policy)
    try:
        lines = p.read_text(errors="replace").splitlines()
    except Exception as e:
        return str(e)
    end = end_line or len(lines)
    body = "\n".join(f"{i}\t{ln}" for i, ln in enumerate(lines[start_line - 1:end], start_line))
    return mac._clip(f"({len(lines)} lines)\n{body}")


def t_write_file(ctx, path, content):
    p = guard_path(path, ctx.policy, write=True)
    if ctx.dry_run:
        return f"[dry-run] would write {len(content)} chars to {p}"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return f"Wrote {p} ({len(content.splitlines())} lines)."


def t_edit_file(ctx, path, old_text, new_text):
    p = guard_path(path, ctx.policy, write=True)
    try:
        text = p.read_text()
    except Exception as e:
        return str(e)
    count = text.count(old_text)
    if count == 0:
        return "old_text was not found. Read the file again and copy the text exactly."
    if count > 1:
        return f"old_text appears {count} times; include more surrounding lines so it's unique."
    if ctx.dry_run:
        return f"[dry-run] would edit {p}"
    p.write_text(text.replace(old_text, new_text))
    return f"Edited {p}."


def t_list_files(ctx, path="", depth=2):
    p = guard_path(path or "~", ctx.policy)
    out, base = [], p
    for root, dirs, files in os.walk(p):
        rel = Path(root).relative_to(base)
        if len(rel.parts) >= depth:
            dirs[:] = []
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for f in sorted(files):
            out.append(str(Path(root, f)))
    return mac._clip("\n".join(out[:300])) or "(empty)"


def t_screenshot(ctx, question="Describe what is on screen."):
    if not mac.can_see():
        return ("Screen Recording isn't allowed for this process, so I can't see the "
                "screen. The user can grant it in System Settings > Privacy & Security.")
    b64, w, h = mac._screenshot()
    # Ask the persona's own vision-capable model on lab3 about the image.
    content = [{"type": "text", "text": f"{question}\n(The screen is {w}x{h} pixels.)"},
               {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}]
    r = lab3_chat(ctx, [{"role": "user", "content": content}], tools=None,
                  max_tokens=500, model=ctx.persona.model)
    return r["choices"][0]["message"].get("content") or "(no description)"


def t_click(ctx, target="", x=None, y=None, button="left", double=False):
    if not ctx.policy.gui_control:
        raise Refused("this persona may not control the mouse")
    if ctx.dry_run:
        return f"[dry-run] would click {target or (x, y)}"
    return mac.mac_click(target=target, x=x, y=y, button=button, double=double)


def t_type_text(ctx, text, app=""):
    if not ctx.policy.gui_control:
        raise Refused("this persona may not type")
    if ctx.dry_run:
        return f"[dry-run] would type {len(text)} chars"
    return mac.mac_type(text, app=app)


def t_press_key(ctx, keys):
    if not ctx.policy.gui_control:
        raise Refused("this persona may not press keys")
    if ctx.dry_run:
        return f"[dry-run] would press {keys}"
    return mac.mac_key(keys)


def t_scroll(ctx, direction="down", amount=5):
    if not ctx.policy.gui_control:
        raise Refused("this persona may not scroll")
    if ctx.dry_run:
        return f"[dry-run] would scroll {direction} {amount}"
    return mac.mac_scroll(direction=direction, amount=amount)


_APP_NAME = re.compile(r"^[A-Za-z0-9 ._-]{1,60}$")


def t_focus_app(ctx, name):
    """Bring an app to the front so screenshots, clicks and keys act on it.
    A plain activate — no synthetic keystrokes — so it's allowed even though
    general osascript isn't."""
    name = (name or "").strip().rstrip(".app")
    if not _APP_NAME.match(name):
        raise Refused("give a plain application name, e.g. Safari or TextEdit")
    if ctx.dry_run:
        return f"[dry-run] would focus {name}"
    # Launch it if it isn't running, then activate, then confirm it's frontmost.
    subprocess.run(["open", "-a", name], capture_output=True, text=True, timeout=10)
    time.sleep(0.6)
    for _ in range(3):
        subprocess.run(["osascript", "-e", f'tell application "{name}" to activate'],
                       capture_output=True, text=True, timeout=10)
        time.sleep(1.0)
        front = mac._frontmost() or ""
        if name.lower() in front.lower() or front.lower() in name.lower():
            return f"{name} is now frontmost. Take a screenshot to see it."
    return (f"Asked {name} to come forward, but {front or 'another app'} is still in "
            f"front — it may be on another Space or mid-launch. Screenshot to check "
            f"before you type, so your keys don't go to the wrong app.")


def t_rag_search(ctx, query, k=6, domain="", source=""):
    import urllib.parse
    params = {"q": query, "k": k}
    if domain:
        params["domain"] = domain
    if source:
        params["source"] = source
    url = RAG_URL + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Host": RAG_HOST_HEADER})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.read().decode()[:6000]
    except Exception as e:
        return f"rag_search unavailable ({e}); fall back to your own knowledge or the web."


def t_web_search(ctx, query, max_results=5):
    return lookup.web_search(query, max_results=max_results)


def t_read_page(ctx, url):
    return lookup.read_page(url)


TOOLS = {
    "run_command": (t_run_command, "Run a shell command (zsh) and return its output.",
                    {"command": "string", "cwd": "string"}, ["command"]),
    "read_file": (t_read_file, "Read a file with line numbers.",
                  {"path": "string", "start_line": "integer", "end_line": "integer"}, ["path"]),
    "write_file": (t_write_file, "Create or overwrite a file.",
                   {"path": "string", "content": "string"}, ["path", "content"]),
    "edit_file": (t_edit_file, "Replace text that occurs exactly once in a file.",
                  {"path": "string", "old_text": "string", "new_text": "string"},
                  ["path", "old_text", "new_text"]),
    "list_files": (t_list_files, "List files under a directory.",
                   {"path": "string", "depth": "integer"}, []),
    "screenshot": (t_screenshot, "Look at the screen and answer a question about it.",
                   {"question": "string"}, []),
    "click": (t_click, "Click a UI element by description, or at screen points x,y.",
              {"target": "string", "x": "integer", "y": "integer",
               "button": "string", "double": "boolean"}, []),
    "type_text": (t_type_text, "Type text into the focused control.",
                  {"text": "string", "app": "string"}, ["text"]),
    "press_key": (t_press_key, "Press a key combination, e.g. cmd+s or return.",
                  {"keys": "string"}, ["keys"]),
    "scroll": (t_scroll, "Scroll the focused window.",
               {"direction": "string", "amount": "integer"}, []),
    "focus_app": (t_focus_app, "Bring a named app to the front (e.g. Safari, TextEdit) "
                  "before you screenshot, click or type in it.",
                  {"name": "string"}, ["name"]),
    "rag_search": (t_rag_search, "Search the local cybersecurity knowledge base "
                   "(MITRE ATT&CK, OWASP cheat sheets, PortSwigger Web Security Academy, "
                   "your own notes) for vetted reference material. Prefer this over memory "
                   "for security facts, techniques and mitigations. Optional: domain "
                   "('att&ck','web','cve') or source to narrow results.",
                   {"query": "string", "k": "integer", "domain": "string",
                    "source": "string"}, ["query"]),
    "web_search": (t_web_search, "Search the web.",
                   {"query": "string", "max_results": "integer"}, ["query"]),
    "read_page": (t_read_page, "Fetch a public web page as text.",
                  {"url": "string"}, ["url"]),
}


def schemas():
    out = []
    for name, (_fn, desc, props, req) in TOOLS.items():
        out.append({"type": "function", "function": {
            "name": name, "description": desc,
            "parameters": {"type": "object", "required": req,
                           "properties": {k: {"type": t} for k, t in props.items()}}}})
    return out


# --- lab3 client -------------------------------------------------------------

def _post_lab3(key, body):
    req = urllib.request.Request(
        LAB3_BASE_URL + "/v1/chat/completions", data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + key})
    with urllib.request.urlopen(req, timeout=900) as r:
        return json.load(r)


def lab3_chat(ctx, messages, tools, max_tokens=2048, temperature=0.3, model=None):
    body = {"model": model or ctx.persona.model, "messages": messages,
            "temperature": temperature, "max_tokens": max_tokens,
            "chat_template_kwargs": {"enable_thinking": False}}
    if tools:
        body["tools"] = tools
    try:
        return _post_lab3(model and _VISION_KEY or ctx.key, body)
    except urllib.error.HTTPError as e:
        sys.exit(f"lab3 said {e.code}: {e.read().decode()[:300]}")
    except (urllib.error.URLError, TimeoutError) as e:
        sys.exit(f"can't reach lab3 at {LAB3_BASE_URL} ({e})")


def _vision_via_lab3(prompt, image_b64, max_tokens=300):
    """Replaces mac._vision so the Mac tools' click-by-description lookups
    use lab3's vision model instead of the chat bridge's local model."""
    content = [{"type": "text", "text": prompt},
               {"type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}}]
    body = {"model": _VISION_MODEL, "messages": [{"role": "user", "content": content}],
            "temperature": 0.0, "max_tokens": max_tokens,
            "chat_template_kwargs": {"enable_thinking": False}}
    r = _post_lab3(_VISION_KEY, body)
    return r["choices"][0]["message"].get("content") or ""


# --- logging and stop --------------------------------------------------------

def log(persona, line):
    STATE.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%H:%M:%S")
    with (STATE / f"agent-{persona.name}.log").open("a") as f:
        f.write(f"{datetime.now().isoformat(timespec='seconds')} {line}\n")
    print(f"  [{stamp}] {line}", flush=True)


def check_stop(persona):
    if STOP_FILE.exists():
        STOP_FILE.unlink(missing_ok=True)
        raise Stopped()


# --- the loop ----------------------------------------------------------------

def run(persona, task, steps, dry_run):
    global _VISION_KEY, _VISION_MODEL
    key = load_key(persona)
    _VISION_KEY = key
    _VISION_MODEL = persona.model    # each persona sees with its own model
    mac._vision = _vision_via_lab3   # click-by-description lookups go to lab3
    ctx = Ctx(persona, key, dry_run)
    fns = {name: spec[0] for name, spec in TOOLS.items()}
    msgs = [{"role": "system", "content": persona.system_prompt},
            {"role": "user", "content": task}]
    log(persona, f"START as {persona.name} (model {persona.model}"
                 f"{', dry-run' if dry_run else ''}): {task}")
    for step in range(1, steps + 1):
        check_stop(persona)
        r = lab3_chat(ctx, msgs, schemas())
        msg = r["choices"][0]["message"]
        msgs.append({k: v for k, v in msg.items()
                     if k in ("role", "content", "tool_calls")})
        calls = msg.get("tool_calls") or []
        if msg.get("content") and msg["content"].strip():
            print(f"\n{persona.name}: {msg['content'].strip()}\n", flush=True)
        if not calls:
            log(persona, "DONE")
            return msg.get("content") or ""
        for call in calls:
            check_stop(persona)
            name = call["function"]["name"]
            try:
                args = json.loads(call["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            brief = ", ".join(f"{k}={str(v)[:60]!r}" for k, v in args.items())
            log(persona, f"step {step}: {name}({brief})")
            try:
                if name not in fns:
                    raise Refused(f"no such tool: {name}")
                out = str(fns[name](ctx, **args))
            except Refused as e:
                out = f"refused: {e}"
                log(persona, f"  refused: {e}")
            except Stopped:
                raise
            except Exception as e:
                out = f"error: {type(e).__name__}: {e}"
                log(persona, f"  error: {e}")
            msgs.append({"role": "tool", "tool_call_id": call.get("id", name),
                         "content": out[:6000]})
    log(persona, f"stopped after the step limit ({steps})")
    return f"Stopped after {steps} steps."


def main():
    ap = argparse.ArgumentParser(description="Drive this Mac as Marina or Songbird.")
    ap.add_argument("task", nargs="+", help="what to do")
    ap.add_argument("--persona", choices=list(PERSONAS), help="override the default persona")
    ap.add_argument("--steps", type=int, help="max tool rounds (default: the persona's)")
    ap.add_argument("--dry-run", action="store_true", help="show tool calls, change nothing")
    args = ap.parse_args()
    name = args.persona or os.environ.get("AGENT_PERSONA") or "marina"
    persona = PERSONAS[name]
    steps = args.steps or persona.policy.max_steps
    try:
        run(persona, " ".join(args.task), steps, args.dry_run)
    except Stopped:
        log(persona, "STOPPED by the user")
        print("\nStopped.", flush=True)
    except KeyboardInterrupt:
        print("\nInterrupted.", flush=True)


if __name__ == "__main__":
    main()
