"""A small local web UI for the Mac agent, so you can drive Marina and
Songbird from a browser (a phone included) instead of the terminal.

It wraps the same `runner.run()` loop the CLI uses — nothing about the loop,
the personas or their policies changes — and streams each run's structured
events (every tool call with its args and result, and the model's text) to
the page over Server-Sent Events. The Stop button touches the same stop file
`~/.marina/agent.stop` that `touch` and Ctrl-C use.

    python -m agent.web.server            # http://127.0.0.1:7420
    python -m agent.web.server --host 0.0.0.0 --port 7420

Stdlib only, so it runs under the same `python3` the CLI does, with no extra
install. One run at a time: start a task, watch it stream, stop it, start the
next. Bind to 127.0.0.1 unless you mean to serve it on the LAN.
"""
import argparse
import json
import os
import sys
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

# Run both as a module (python -m agent.web.server) and by path, by making
# server/ importable so `agent.*` and the bridge's `process.*` tools resolve.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent import runner                       # noqa: E402
from agent.personas import PERSONAS            # noqa: E402

HERE = Path(__file__).resolve().parent
INDEX = HERE / "index.html"


class RunSession:
    """One agent run: its buffered events and a condition to wake viewers.

    Events are kept so a viewer that connects late (or reconnects) replays the
    whole run before following the live tail. Several viewers can watch at once.
    """

    def __init__(self, persona, prompt, steps, dry_run):
        self.id = uuid.uuid4().hex[:12]
        self.persona = persona
        self.prompt = prompt
        self.steps = steps
        self.dry_run = dry_run
        self.events = []            # list of event dicts, in order
        self.done = False
        self._cond = threading.Condition()
        self._thread = None

    def _emit(self, ev):
        with self._cond:
            self.events.append(ev)
            self._cond.notify_all()

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        try:
            runner.run(self.persona, self.prompt, self.steps, self.dry_run,
                       on_event=self._emit)
        except runner.Stopped:
            self._emit({"type": "stopped"})
        except SystemExit as e:
            # load_key / lab3_chat call sys.exit on a bad key or an unreachable
            # lab3; in this worker thread that is a catchable SystemExit.
            self._emit({"type": "error",
                        "message": str(e) or "the run exited"})
        except Exception as e:          # pragma: no cover - defensive
            self._emit({"type": "error",
                        "message": f"{type(e).__name__}: {e}"})
        finally:
            with self._cond:
                self.done = True
                self.events.append({"type": "end"})
                self._cond.notify_all()

    def stream(self):
        """Yield events from the start, blocking for new ones until the run
        ends. A yielded None is a keep-alive tick. Used by the SSE handler."""
        i = 0
        while True:
            with self._cond:
                if i >= len(self.events):
                    if self.done:
                        return
                    self._cond.wait(timeout=20)
                    if i >= len(self.events):
                        yield None          # heartbeat while idle
                        continue
                batch = self.events[i:]
                i = len(self.events)
            for ev in batch:
                yield ev
                if ev.get("type") == "end":
                    return


class Agent:
    """Holds the single active run. One task at a time keeps the shared stop
    file and the loop's module-level vision key unambiguous."""

    def __init__(self):
        self._lock = threading.Lock()
        self.current = None

    def start(self, persona_name, prompt, max_steps, dry_run):
        persona = PERSONAS.get(persona_name)
        if persona is None:
            raise ValueError(f"no such persona: {persona_name}")
        if not (prompt or "").strip():
            raise ValueError("the task is empty")
        steps = int(max_steps) if max_steps else persona.policy.max_steps
        steps = max(1, min(steps, 200))
        with self._lock:
            if self.current and not self.current.done:
                raise RuntimeError("a run is already in progress; stop it first")
            # Clear any stale stop flag left from a previous run.
            runner.STOP_FILE.unlink(missing_ok=True)
            sess = RunSession(persona, prompt.strip(), steps, bool(dry_run))
            self.current = sess
        sess.start()
        return sess

    def stop(self):
        runner.request_stop()
        sess = self.current
        return bool(sess and not sess.done)


AGENT = Agent()


def persona_list():
    out = []
    for name, p in PERSONAS.items():
        pol = p.policy
        out.append({
            "name": name,
            "model": p.model,
            "max_steps": pol.max_steps,
            "policy": {
                "confine_home": pol.confine_home,
                "block_risky": pol.block_risky,
                "block_ui_commands": pol.block_ui_commands,
                "shield_secrets": pol.shield_secrets,
                "gui_control": pol.gui_control,
            },
        })
    return out


class Handler(BaseHTTPRequestHandler):
    server_version = "MacAgentWeb/1.0"

    def log_message(self, *a):   # keep the console quiet; runs log to ~/.marina
        pass

    # -- helpers --------------------------------------------------------------

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode() or "{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}

    # -- routes ---------------------------------------------------------------

    def do_GET(self):
        route = urlparse(self.path)
        if route.path in ("/", "/index.html"):
            return self._serve_index()
        if route.path == "/api/personas":
            return self._json({"personas": persona_list()})
        if route.path == "/api/status":
            sess = AGENT.current
            return self._json({
                "running": bool(sess and not sess.done),
                "run_id": sess.id if sess else None,
                "persona": sess.persona.name if sess else None,
            })
        if route.path == "/api/events":
            return self._serve_events(parse_qs(route.query))
        self.send_error(404, "not found")

    def do_POST(self):
        route = urlparse(self.path)
        if route.path == "/api/run":
            body = self._read_json()
            try:
                sess = AGENT.start(body.get("persona"), body.get("prompt", ""),
                                   body.get("max_steps"), body.get("dry_run"))
            except (ValueError, RuntimeError) as e:
                code = 409 if isinstance(e, RuntimeError) else 400
                return self._json({"error": str(e)}, code)
            return self._json({"run_id": sess.id, "persona": sess.persona.name,
                               "steps": sess.steps, "dry_run": sess.dry_run})
        if route.path == "/api/stop":
            return self._json({"stopping": AGENT.stop()})
        self.send_error(404, "not found")

    # -- static + SSE ---------------------------------------------------------

    def _serve_index(self):
        try:
            body = INDEX.read_bytes()
        except OSError:
            return self.send_error(500, "index.html missing")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_events(self, qs):
        run_id = (qs.get("run_id") or [None])[0]
        sess = AGENT.current
        if not sess or (run_id and sess.id != run_id):
            return self.send_error(404, "no such run")
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        try:
            for ev in sess.stream():
                if ev is None:
                    chunk = b": heartbeat\n\n"       # SSE comment keep-alive
                else:
                    chunk = f"data: {json.dumps(ev)}\n\n".encode()
                self.wfile.write(chunk)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass        # the viewer navigated away; the run keeps going


def main():
    ap = argparse.ArgumentParser(description="Web UI for the Mac agent.")
    ap.add_argument("--host", default=os.environ.get("AGENT_WEB_HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int,
                    default=int(os.environ.get("AGENT_WEB_PORT", "7420")))
    args = ap.parse_args()
    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    where = f"http://{args.host}:{args.port}"
    if args.host in ("0.0.0.0", "::"):
        where += "  (reachable on the LAN — bind 127.0.0.1 to keep it local)"
    print(f"Mac agent web UI on {where}\nPersonas: {', '.join(PERSONAS)}  "
          f"(Ctrl-C to quit)", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.", flush=True)
        httpd.shutdown()


if __name__ == "__main__":
    main()
