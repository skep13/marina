"""The assistant's loop. Runs as the desktop user (aiws-agent.service,
a systemd user unit) and takes tasks from aiwsd.

Before every action it asks aiwsd whether it may go on: paused means
wait, stopped means drop the task. Every action is logged in aiwsd
before it runs and updated after, so the control centre shows what is
happening as it happens. `ai agent stop` also kills this process
outright, which is the immediate stop; the state check is the polite one.
"""
import json
import os
import sys
import time
import traceback
import urllib.error
import urllib.request

from aiws.agent import tools

SYSTEM = """You are AIWS's built-in assistant, working inside the user's
development workstation on the project "{name}" at {root}.

You can read and edit the project's files, run commands in its visible
terminal, look at and operate the desktop, and send jobs to other machines
in the homelab. The user can see every action you take and can pause or
stop you at any time.

Work in small, checkable steps. Read before you edit. Prefer the
accessibility tree to screenshots. You have no admin rights; if a task
needs them, say what the user should run from the control centre.
When you're done, reply with a short summary of what you did and found."""

MAX_STEPS = int(os.environ.get("AIWS_AGENT_MAX_STEPS", "40"))


class Stopped(Exception):
    pass


class Client:
    def __init__(self, base, token):
        self.base = base.rstrip("/")
        self.token = token

    def call(self, path, payload=None, method=None):
        url = f"{self.base}/{path[3:]}" if path.startswith("../") else f"{self.base}/v1/{path}"
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(url, data, method=method or ("POST" if data else "GET"),
                                     headers={"Authorization": f"Bearer {self.token}",
                                              "Content-Type": "application/json",
                                              "X-AIWS-Client": "agent"})
        with urllib.request.urlopen(req, timeout=900) as r:
            return json.load(r)

    def api(self, path, payload=None, method=None):
        return self.call("../api/" + path, payload, method)


def checkpoint(c, task_id):
    """Block while paused; raise if stopped."""
    while True:
        st = c.api("agent/state")["state"]
        if st == "stopped" or st == f"cancel:{task_id}":
            raise Stopped()
        if st != "paused":
            return
        time.sleep(0.5)


def run_task(c, task):
    project = c.api(f"projects/{task['project']}")
    ctx = tools.Context(project, c.call)
    fns, schemas = tools.available(ctx)
    session = f"task-{task['id']}"
    msgs = [{"role": "system", "content": SYSTEM.format(**project)},
            {"role": "user", "content": task["prompt"]}]
    for step in range(MAX_STEPS):
        checkpoint(c, task["id"])
        r = c.call("chat/completions", {
            "model": task.get("model") or "ai:code", "messages": msgs, "tools": schemas,
            "temperature": 0.3, "max_tokens": 2048})
        msg = r["choices"][0]["message"]
        msgs.append({k: v for k, v in msg.items() if k in ("role", "content", "tool_calls")})
        calls = msg.get("tool_calls") or []
        if not calls:
            return msg.get("content") or ""
        for call in calls:
            name = call["function"]["name"]
            try:
                args = json.loads(call["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            checkpoint(c, task["id"])
            aid = c.api("agent/actions", {"session": session, "tool": name, "args": args})["id"]
            try:
                if name not in fns:
                    raise tools.Refused(f"{name} isn't available in this project")
                out, status = fns[name](ctx, **args), "ok"
            except tools.Refused as e:
                out, status = f"refused: {e}", "refused"
            except Exception as e:
                out, status = f"error: {e}", "error"
            c.api(f"agent/actions/{aid}", {"status": status, "result": str(out)[:4000]}, "PATCH")
            msgs.append({"role": "tool", "tool_call_id": call.get("id", name), "content": str(out)})
    return "Stopped after the step limit."


def main():
    base = os.environ.get("AIWS_URL", "http://127.0.0.1:7300")
    token_file = os.environ.get("AIWS_TOKEN_FILE", "/var/lib/aiws/desktop.token")
    token = os.environ.get("AIWS_TOKEN") or open(token_file).read().strip()
    c = Client(base, token)
    print(f"aiws-agent: waiting for tasks from {base}", flush=True)
    while True:
        try:
            task = c.api("agent/next")  # long-poll, returns {} after a timeout
        except (urllib.error.URLError, OSError):
            time.sleep(3)
            continue
        if not task:
            continue
        c.api(f"agent/tasks/{task['id']}", {"status": "running"}, "PATCH")
        try:
            result, status = run_task(c, task), "done"
        except Stopped:
            result, status = "Stopped by the user.", "stopped"
        except Exception:
            result, status = traceback.format_exc()[-3000:], "failed"
        c.api(f"agent/tasks/{task['id']}", {"status": status, "result": result}, "PATCH")


if __name__ == "__main__":
    sys.exit(main())
