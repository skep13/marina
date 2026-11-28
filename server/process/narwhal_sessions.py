"""Narwhal's synced sessions: kept on lab3 so the phone and the Mac list,
open and continue the same chats, and either can watch a reply live while
the other one asked for it.

A reply runs on the bridge, not in the app that asked: it keeps going if the
phone locks or the Mac closes, and every device following the session sees
the same events. Finished turns are stored in SQLite (narwhal.db next to her
other data); the reply in progress lives in memory until it ends.

Per-session follow stream, one JSON object per line, each with a `seq`
that only grows while the bridge runs:
  {"type": "hello", "running": bool, "seq": n}       first line on connect
  {"type": "user", "turn": {...}}                     a message was sent
  {"type": "start", "turn_id", "route", "model", "label", "reason"}
  {"type": "think" | "text", "turn_id", "text"}
  {"type": "done" | "stopped" | "error", "turn_id", "turn": {...}}
  {"type": "resync"}     events were missed: reload the session
  {"type": "ping"}       keep-alive, no seq

The global watch stream sends {"type": "changed", "session": id, "running",
"deleted"?} whenever any session changes, so session lists stay current.

Narwhal shares none of Marina's memory or history.
"""

import json
import re
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timezone

from process import config as cfg
from process import narwhal
from process import narwhal_claude
from process import narwhal_route as route_mod
from process import narwhal_mac
from process import narwhal_search

TITLE_CHARS = 48
# Notes the owner writes (projects, layouts, IPs...) go to the model with every
# message, like a memory file. This caps how much of the context they take.
NOTES_MAX_CHARS = 12_000
NOTE_MAX_CHARS = 8_000
PING_SECONDS = 15
# Events of the current (or last) run kept for watchers that join late.
MAX_EVENTS = 20_000


class Busy(Exception):
    """The session is already answering."""


class NotFound(Exception):
    pass


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _id():
    return uuid.uuid4().hex[:12]


class Store:
    """SQLite for finished turns. One connection, guarded by a lock."""

    def __init__(self, path):
        self.lock = threading.Lock()
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        with self.lock, self.db:
            self.db.executescript("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY, title TEXT NOT NULL, created TEXT NOT NULL,
                    updated TEXT NOT NULL, last_route TEXT);
                CREATE TABLE IF NOT EXISTS turns (
                    id TEXT PRIMARY KEY, session_id TEXT NOT NULL, n INTEGER NOT NULL,
                    role TEXT NOT NULL, text TEXT NOT NULL DEFAULT '',
                    thinking TEXT NOT NULL DEFAULT '', route TEXT, model TEXT, label TEXT,
                    reason TEXT, seconds REAL, think_seconds REAL,
                    status TEXT NOT NULL DEFAULT 'ok', error TEXT, at TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS turns_by_session ON turns(session_id, n);
                CREATE TABLE IF NOT EXISTS notes (
                    id TEXT PRIMARY KEY, title TEXT NOT NULL, body TEXT NOT NULL DEFAULT '',
                    enabled INTEGER NOT NULL DEFAULT 1, created TEXT NOT NULL, updated TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT NOT NULL);
            """)
            have = {r[1] for r in self.db.execute("PRAGMA table_info(turns)")}
            for col, kind in (("prompt_tokens", "INTEGER"), ("completion_tokens", "INTEGER"),
                              ("tok_s", "REAL")):
                if col not in have:
                    self.db.execute(f"ALTER TABLE turns ADD COLUMN {col} {kind}")
            if "claude_session" not in {r[1] for r in self.db.execute("PRAGMA table_info(sessions)")}:
                # The Claude Code session this chat continues (--resume).
                self.db.execute("ALTER TABLE sessions ADD COLUMN claude_session TEXT")
            # A reply cut off by a bridge restart is kept as stopped.
            self.db.execute("UPDATE turns SET status='stopped' WHERE status='running'")

    def q(self, sql, args=()):
        with self.lock, self.db:
            return [dict(r) for r in self.db.execute(sql, args).fetchall()]

    def x(self, sql, args=()):
        with self.lock, self.db:
            return self.db.execute(sql, args).rowcount


# The Mac app asks the owner before writes and commands, so give it time.
MAC_TOOL_WAIT = 300
MAC_RESULT_CHARS = 60_000
MAX_TOOL_ROUNDS = 12

WEB_NOTE = ("Today is {today}. You can search the web (web_search, then open_page for a result "
            "worth reading) when you don't know something or it may have changed since you were "
            "trained. Don't search for what you already know well. When you use what you found, "
            "say where it came from with the page's link.")


class _Run:
    def __init__(self, turn_id):
        self.turn_id = turn_id
        self.cancel = False
        self.done = False
        self.claude = None             # what a Claude Code reply needs
        self.quick = False             # answer without thinking first
        self.web = False               # may search the web
        self.mac = False               # may use the Mac's files (sent from the Mac app)


class Hub:
    def __init__(self, path=None, client=None, error_message=str):
        self.store = Store(path or cfg.resolve_data("narwhal.db"))
        self.client = client           # callable returning the llama-swap client
        self.error_message = error_message
        self.cond = threading.Condition()
        self.runs = {}                 # session id -> _Run (current or last)
        self.events = {}               # session id -> [event, ...] since the bridge started
        self.seq = {}                  # session id -> last seq handed out
        self.changes = []              # (n, event) for the global watch
        self.change_n = 0
        self.tool_waits = {}           # mac tool call id -> {"event", "result"}

    # --- reading -------------------------------------------------------

    def running(self, sid):
        r = self.runs.get(sid)
        return bool(r and not r.done)

    def list(self):
        rows = self.store.q("""
            SELECT s.*, (SELECT text FROM turns t WHERE t.session_id = s.id AND t.role = 'user'
                         ORDER BY n DESC LIMIT 1) AS preview,
                        (SELECT COUNT(*) FROM turns t WHERE t.session_id = s.id) AS turns
            FROM sessions s ORDER BY updated DESC""")
        for r in rows:
            r["running"] = self.running(r["id"])
            r["preview"] = (r["preview"] or "")[:120]
        return rows

    def get(self, sid):
        rows = self.store.q("SELECT * FROM sessions WHERE id = ?", (sid,))
        if not rows:
            raise NotFound(sid)
        s = rows[0]
        s["turns"] = [self._turn_out(t) for t in self.store.q(
            "SELECT * FROM turns WHERE session_id = ? ORDER BY n", (sid,))]
        s["running"] = self.running(sid)
        s["seq"] = self.seq.get(sid, 0)
        s["context"] = {r: route_mod.context_for(r) for r in route_mod.PICKABLE}
        s.pop("claude_session", None)
        if s["running"]:
            # The reply so far, so a device that opens the session mid-reply
            # shows it at once and then follows from `seq`.
            live = next((t for t in s["turns"] if t["id"] == self.runs[sid].turn_id), None)
            if live is not None:
                think, text = self._partial(sid)
                live["thinking"], live["text"] = think, text
        return s

    @staticmethod
    def _turn_out(t):
        t = dict(t)
        t.pop("session_id", None)
        return t

    def _partial(self, sid):
        run = self.runs.get(sid)
        think, text = [], []
        for ev in self.events.get(sid, []):
            if run and ev.get("turn_id") == run.turn_id:
                if ev["type"] == "think":
                    think.append(ev["text"])
                elif ev["type"] == "text":
                    text.append(ev["text"])
        return "".join(think), "".join(text)

    # --- changing ------------------------------------------------------

    def create(self, title=None):
        sid, now = _id(), _now()
        self.store.x("INSERT INTO sessions (id, title, created, updated) VALUES (?, ?, ?, ?)",
                     (sid, (title or "New chat").strip()[:120] or "New chat", now, now))
        self._changed(sid)
        return self.get(sid)

    def rename(self, sid, title):
        title = (title or "").strip()[:120]
        if not title:
            raise ValueError("empty title")
        if not self.store.x("UPDATE sessions SET title = ? WHERE id = ?", (title, sid)):
            raise NotFound(sid)
        self._changed(sid)
        return self.get(sid)

    def delete(self, sid):
        self.stop(sid)
        self.store.x("DELETE FROM turns WHERE session_id = ?", (sid,))
        if not self.store.x("DELETE FROM sessions WHERE id = ?", (sid,)):
            raise NotFound(sid)
        with self.cond:
            self.events.pop(sid, None)
            self.runs.pop(sid, None)
        self._changed(sid, deleted=True)

    def import_turns(self, title, turns):
        """Brings an old phone-only conversation in as a session."""
        s = self.create(title or "Imported chat")
        n = 0
        last = None
        for t in turns or []:
            role = t.get("role")
            text = str(t.get("text") or t.get("content") or "")
            if role not in ("user", "assistant") or (not text and role == "user"):
                continue
            n += 1
            r = t.get("route") if t.get("route") in route_mod.ROUTES else None
            if role == "assistant":
                r = r or route_mod.SECURITY
                last = r
            self.store.x("""INSERT INTO turns (id, session_id, n, role, text, thinking, route, model,
                            label, seconds, think_seconds, status, at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                         (_id(), s["id"], n, role, text, str(t.get("thinking") or ""), r,
                          route_mod.model_for(r) if r else None, route_mod.label_for(r) if r else None,
                          t.get("seconds"), t.get("think_seconds"),
                          "error" if t.get("failed") else "ok", str(t.get("at") or _now())))
        self.store.x("UPDATE sessions SET last_route = ?, updated = ? WHERE id = ?",
                     (last, _now(), s["id"]))
        self._changed(s["id"])
        return self.get(s["id"])

    def send(self, sid, text, route="auto", mode=None, model=None, effort=None, think=None, web=None, mac=None):
        """Adds the user's message and starts the reply in the background.
        Returns the user turn and the reply's turn id."""
        text = (text or "").strip()
        if not text:
            raise ValueError("empty message")
        rows = self.store.q("SELECT * FROM sessions WHERE id = ?", (sid,))
        if not rows:
            raise NotFound(sid)
        session = rows[0]
        with self.cond:
            if self.running(sid):
                raise Busy(sid)
            if route == route_mod.CLAUDE and not self.claude_ok():
                raise ValueError("Claude Code isn't set up on lab3")
            if route in route_mod.PICKABLE:
                chosen, reason = route, "picked by hand"
            else:
                chosen, reason = route_mod.choose(text, session.get("last_route"))
            run = _Run(_id())
            run.quick = think == "quick"
            run.web = bool(web)
            run.mac = bool(mac)
            self.runs[sid] = run
            self.events[sid] = []

        n = (self.store.q("SELECT MAX(n) AS n FROM turns WHERE session_id = ?", (sid,))[0]["n"] or 0)
        now = _now()
        user = {"id": _id(), "n": n + 1, "role": "user", "text": text, "at": now, "status": "ok"}
        self.store.x("INSERT INTO turns (id, session_id, n, role, text, status, at) VALUES (?, ?, ?, ?, ?, 'ok', ?)",
                     (user["id"], sid, user["n"], "user", text, now))
        model_id, label = route_mod.model_for(chosen), route_mod.label_for(chosen)
        self.store.x("""INSERT INTO turns (id, session_id, n, role, route, model, label, reason, status, at)
                        VALUES (?, ?, ?, 'assistant', ?, ?, ?, ?, 'running', ?)""",
                     (run.turn_id, sid, n + 2, chosen, model_id, label, reason, now))
        title = session["title"]
        if title == "New chat":
            title = _title_from(text)
        self.store.x("UPDATE sessions SET updated = ?, last_route = ?, title = ? WHERE id = ?",
                     (now, chosen, title, sid))

        self._emit(sid, {"type": "user", "turn": self._turn_out({**user, "session_id": sid})})
        self._emit(sid, {"type": "start", "turn_id": run.turn_id, "route": chosen, "model": model_id,
                         "label": label, "reason": reason, "context": route_mod.context_for(chosen)})
        self._changed(sid)
        history = self._history(sid, before=n + 2)
        if chosen == route_mod.CLAUDE:
            run.claude = {"text": text, "mode": mode or "acceptEdits", "model": model or "", "effort": effort or "",
                          "session": session.get("claude_session") or "", "history": history}
        threading.Thread(target=self._reply, args=(sid, run, history, chosen), daemon=True,
                         name=f"narwhal-{sid}").start()
        return {"user": user, "turn_id": run.turn_id, "route": chosen, "model": model_id,
                "label": label, "reason": reason}

    def append(self, sid, text, reply):
        """Stores a finished exchange that ran somewhere else (Claude Code on
        the Mac) so it syncs like any other: the user's message and the
        reply, route "claude". Devices following the session reload it."""
        text = (text or "").strip()
        if not text:
            raise ValueError("empty message")
        reply = reply or {}
        rows = self.store.q("SELECT * FROM sessions WHERE id = ?", (sid,))
        if not rows:
            raise NotFound(sid)
        if self.running(sid):
            raise Busy(sid)
        status = reply.get("status") if reply.get("status") in ("ok", "stopped", "error") else "ok"
        num = lambda k: reply.get(k) if isinstance(reply.get(k), (int, float)) else None
        n = (self.store.q("SELECT MAX(n) AS n FROM turns WHERE session_id = ?", (sid,))[0]["n"] or 0)
        now = _now()
        self.store.x("INSERT INTO turns (id, session_id, n, role, text, status, at) VALUES (?, ?, ?, 'user', ?, 'ok', ?)",
                     (_id(), sid, n + 1, text, now))
        self.store.x("""INSERT INTO turns (id, session_id, n, role, text, thinking, route, model, label,
                        reason, seconds, think_seconds, status, error, prompt_tokens, completion_tokens,
                        tok_s, at) VALUES (?, ?, ?, 'assistant', ?, ?, 'claude', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                     (_id(), sid, n + 2, str(reply.get("text") or ""), str(reply.get("thinking") or ""),
                      str(reply.get("model") or "claude")[:80], str(reply.get("label") or "Claude")[:80],
                      "picked by hand", num("seconds"), num("think_seconds"), status,
                      (str(reply["error"])[:2000] if reply.get("error") else None),
                      num("prompt_tokens"), num("completion_tokens"), num("tok_s"), now))
        title = rows[0]["title"]
        if title == "New chat":
            title = _title_from(text)
        # last_route stays on lab3's side: it only steers Auto between them.
        self.store.x("UPDATE sessions SET updated = ?, title = ? WHERE id = ?", (now, title, sid))
        self._emit(sid, {"type": "resync"})
        self._changed(sid)
        return self.get(sid)

    # --- Claude Code on lab3 ---------------------------------------------

    claude_events = staticmethod(narwhal_claude.events)
    run_tool = staticmethod(narwhal_search.run)

    # --- the Mac's tools ----------------------------------------------------

    def _mac_tool(self, sid, run, name, args):
        """Hands one tool call to the Mac app (watch event "mac_tool") and
        waits for its answer. (step, result) like narwhal_search.run."""
        tid = _id()
        wait = {"event": threading.Event(), "result": None}
        with self.cond:
            self.tool_waits[tid] = wait
            self.change_n += 1
            self.changes.append((self.change_n, {"type": "mac_tool", "id": tid, "session": sid,
                                                 "turn_id": run.turn_id, "name": name,
                                                 "args": narwhal_mac.parse(args)}))
            del self.changes[:-500]
            self.cond.notify_all()
        step = narwhal_mac.step(name, args)
        try:
            deadline = time.monotonic() + MAC_TOOL_WAIT
            while not wait["event"].wait(0.5):
                if run.cancel:
                    return step, "Stopped."
                if time.monotonic() > deadline:
                    return step + "  (no answer from the Mac)", \
                        "The Mac didn't answer (the Narwhal app may be closed or locked)."
        finally:
            with self.cond:
                self.tool_waits.pop(tid, None)
        result = wait["result"]
        if result.startswith("Denied"):
            step += "  ✗ not allowed"
        return step, result

    def tool_result(self, tid, result):
        """The Mac app's answer to a mac_tool request."""
        with self.cond:
            wait = self.tool_waits.get(tid)
        if not wait:
            raise NotFound(tid)
        wait["result"] = str(result if result is not None else "")[:MAC_RESULT_CHARS]
        wait["event"].set()
        return {"ok": True}

    def claude_ok(self):
        return narwhal_claude.available()

    PROFILE_COLORS = ("#3ed2d3", "#a594ff", "#fb923c", "#22a06b", "#e3a43a", "#f472b6", "#60a5fa", "#e6e8ec")

    def profile(self):
        """The owner's profile, shared by the apps: name, colour, photo."""
        rows = self.store.q("SELECT v FROM kv WHERE k = 'profile'")
        p = json.loads(rows[0]["v"]) if rows else {}
        return {"name": p.get("name") or "", "color": p.get("color") or self.PROFILE_COLORS[0],
                "avatar": p.get("avatar") or ""}

    def set_profile(self, name=None, color=None, avatar=None):
        """Changes what's given. avatar is a small data: URL (png/jpeg),
        or "" to remove it."""
        p = self.profile()
        if name is not None:
            p["name"] = " ".join(str(name).split())[:40]
        if color is not None:
            if color not in self.PROFILE_COLORS:
                raise ValueError("unknown colour")
            p["color"] = color
        if avatar is not None:
            avatar = str(avatar)
            if avatar and (not re.match(r"^data:image/(png|jpeg);base64,[A-Za-z0-9+/=]+$", avatar)
                           or len(avatar) > 300_000):
                raise ValueError("the photo has to be a small PNG or JPEG")
            p["avatar"] = avatar
        self.store.x("INSERT OR REPLACE INTO kv (k, v) VALUES ('profile', ?)", (json.dumps(p),))
        with self.cond:
            self.change_n += 1
            self.changes.append((self.change_n, {"type": "profile"}))
            del self.changes[:-500]
            self.cond.notify_all()
        return p

    def claude_usage(self):
        """The Claude plan's use as last reported (by lab3's runs or the
        Mac's), or None before any run."""
        rows = self.store.q("SELECT v FROM kv WHERE k = 'claude_usage'")
        return json.loads(rows[0]["v"]) if rows else None

    def set_claude_usage(self, u):
        """Keeps u if it's newer than what's kept; tells every device."""
        if not u:
            return self.claude_usage()
        with self.cond:
            old = self.claude_usage()
            if old and old.get("at", 0) > u.get("at", 0):
                return old
            self.store.x("INSERT OR REPLACE INTO kv (k, v) VALUES ('claude_usage', ?)", (json.dumps(u),))
            self.change_n += 1
            self.changes.append((self.change_n, {"type": "claude_usage", "usage": u}))
            del self.changes[:-500]
            self.cond.notify_all()
        return u

    def _claude(self, sid, run):
        """Claude Code's reply as Narwhal events. Its first turn in a chat
        gets what was said before (with lab3's models) as plain text; later
        turns continue its own session."""
        c = run.claude
        prompt = c["text"]
        if not c["session"] and c["history"]:
            said = "\n\n".join(f"{'Me' if m['role'] == 'user' else 'Assistant'}: {m['content']}"
                                for m in c["history"])[-16000:]
            prompt = f"Earlier in this chat, with another model:\n\n{said}\n\n---\n\n{prompt}"
        if not narwhal_claude.LOCK.acquire(blocking=False):
            yield {"type": "error", "message": "Claude is answering in another chat. Try again when it's done."}
            return
        try:
            system = "\n\n".join(p for p in (narwhal_claude.SANDBOX_NOTE, self._system(route_mod.CLAUDE)) if p)
            for ev in self.claude_events(prompt, c["session"], c["mode"], c["model"],
                                         system, cancel=lambda: run.cancel,
                                         effort=c.get("effort") or ""):
                if ev["type"] == "usage":
                    self.set_claude_usage({k: v for k, v in ev.items() if k != "type"})
                    continue
                if ev["type"] == "session":
                    self.store.x("UPDATE sessions SET claude_session = ? WHERE id = ?", (ev["id"], sid))
                    if ev.get("model"):
                        self.store.x("UPDATE turns SET label = ?, model = ? WHERE id = ?",
                                     (narwhal_claude.label(ev["model"]), ev["model"], run.turn_id))
                    continue
                yield ev
        finally:
            narwhal_claude.LOCK.release()

    def stop(self, sid):
        with self.cond:
            run = self.runs.get(sid)
            if run and not run.done:
                run.cancel = True
                return True
        return False

    def _history(self, sid, before):
        rows = self.store.q("""SELECT role, text FROM turns WHERE session_id = ? AND n < ?
                               AND status = 'ok' AND text != '' ORDER BY n""", (sid, before))
        return narwhal.clean([{"role": r["role"], "content": r["text"]} for r in rows])

    def _reply(self, sid, run, history, chosen):
        think, text, end = [], [], {"type": "error", "message": "No reply."}
        try:
            if chosen == route_mod.CLAUDE:
                stream = self._claude(sid, run)
            else:
                client = self.client() if callable(self.client) else self.client
                system = self._system(chosen)
                tools = []
                if run.web:
                    system = "\n\n".join(p for p in (system, WEB_NOTE.format(today=time.strftime("%A %d %B %Y"))) if p)
                    tools += narwhal_search.TOOLS
                if run.mac:
                    system = "\n\n".join(p for p in (system, narwhal_mac.NOTE) if p)
                    tools += narwhal_mac.TOOLS

                def run_tool(name, args):
                    if name in narwhal_mac.NAMES:
                        return self._mac_tool(sid, run, name, args)
                    return self.run_tool(name, args)
                stream = narwhal.events(client, history, route_mod.model_for(chosen), system,
                                        self.error_message, cancel=lambda: run.cancel,
                                        thinking=not run.quick, tools=tools or None,
                                        run_tool=run_tool if tools else None, max_rounds=MAX_TOOL_ROUNDS)
            for ev in stream:
                if ev["type"] in ("think", "text"):
                    (think if ev["type"] == "think" else text).append(ev["text"])
                    self._emit(sid, {**ev, "turn_id": run.turn_id})
                else:
                    end = ev
        except Exception as e:  # noqa: BLE001 - a failed reply is shown, never raised
            end = {"type": "error", "message": self.error_message(e)}
        status = {"done": "ok", "stopped": "stopped"}.get(end["type"], "error")
        self.store.x("""UPDATE turns SET text = ?, thinking = ?, seconds = ?, think_seconds = ?,
                        status = ?, error = ?, prompt_tokens = ?, completion_tokens = ?, tok_s = ?
                        WHERE id = ?""",
                     ("".join(text), "".join(think), end.get("seconds"), end.get("think_seconds"),
                      status, end.get("message"), end.get("prompt_tokens"),
                      end.get("completion_tokens"), end.get("tok_s"), run.turn_id))
        self.store.x("UPDATE sessions SET updated = ? WHERE id = ?", (_now(), sid))
        turn = self.store.q("SELECT * FROM turns WHERE id = ?", (run.turn_id,))
        with self.cond:
            run.done = True
        self._emit(sid, {**end, "turn_id": run.turn_id,
                         "turn": self._turn_out(turn[0]) if turn else None})
        self._changed(sid)

    # --- notes -----------------------------------------------------------

    def notes(self):
        """Every note, oldest first (the order they reach the model in), each
        marked `included` when it's on and fits in the budget."""
        rows = self.store.q("SELECT * FROM notes ORDER BY created, rowid")
        sent = {nid for nid, _ in self._sent_notes()}
        for r in rows:
            r["enabled"] = bool(r["enabled"])
            r["included"] = r["id"] in sent
        used = len(self.notes_block())
        return {"notes": rows, "used_chars": used, "max_chars": NOTES_MAX_CHARS}

    def _note(self, nid):
        rows = self.store.q("SELECT * FROM notes WHERE id = ?", (nid,))
        if not rows:
            raise NotFound(nid)
        rows[0]["enabled"] = bool(rows[0]["enabled"])
        return rows[0]

    @staticmethod
    def _clean_note(title, body):
        title = (title or "").strip()[:120]
        body = (body or "").strip()
        if len(body) > NOTE_MAX_CHARS:
            raise ValueError(f"a note can be at most {NOTE_MAX_CHARS} characters")
        return title, body

    def add_note(self, title, body="", enabled=True):
        title, body = self._clean_note(title, body)
        if not title and not body:
            raise ValueError("empty note")
        nid, now = _id(), _now()
        self.store.x("INSERT INTO notes (id, title, body, enabled, created, updated) VALUES (?, ?, ?, ?, ?, ?)",
                     (nid, title or "Untitled", body, int(bool(enabled)), now, now))
        self._notes_changed()
        return self._note(nid)

    def update_note(self, nid, title=None, body=None, enabled=None):
        note = self._note(nid)
        t, b = self._clean_note(note["title"] if title is None else title,
                                note["body"] if body is None else body)
        e = note["enabled"] if enabled is None else bool(enabled)
        self.store.x("UPDATE notes SET title = ?, body = ?, enabled = ?, updated = ? WHERE id = ?",
                     (t or "Untitled", b, int(e), _now(), nid))
        self._notes_changed()
        return self._note(nid)

    def delete_note(self, nid):
        if not self.store.x("DELETE FROM notes WHERE id = ?", (nid,)):
            raise NotFound(nid)
        self._notes_changed()

    def notes_block(self):
        """The enabled notes as one block for the system prompt, oldest
        first, cut at NOTES_MAX_CHARS (whole notes only)."""
        parts = [part for _, part in self._sent_notes()]
        if not parts:
            return ""
        return ("The owner's notes about their projects, machines and network. Treat them as "
                "true and current, use the names, paths and addresses in them, and don't repeat "
                "them back unless asked.\n\n" + "\n\n".join(parts))

    def _sent_notes(self):
        """(id, text) of the notes that go to the model: enabled, not
        empty, oldest first, stopping at the first that would overflow."""
        rows = self.store.q("SELECT id, title, body FROM notes WHERE enabled = 1 AND body != '' ORDER BY created, rowid")
        out, total = [], 0
        for r in rows:
            part = f"## {r['title']}\n{r['body']}"
            if total + len(part) > NOTES_MAX_CHARS:
                break
            out.append((r["id"], part))
            total += len(part) + 2
        return out

    def _system(self, route):
        base = route_mod.system_for(route)
        notes = self.notes_block()
        return "\n\n".join(p for p in (base, notes) if p)

    def _notes_changed(self):
        with self.cond:
            self.change_n += 1
            self.changes.append((self.change_n, {"type": "notes"}))
            del self.changes[:-500]
            self.cond.notify_all()

    # --- events --------------------------------------------------------

    def _emit(self, sid, ev):
        with self.cond:
            self.seq[sid] = self.seq.get(sid, 0) + 1
            ev = {**ev, "seq": self.seq[sid]}
            log = self.events.setdefault(sid, [])
            log.append(ev)
            if len(log) > MAX_EVENTS:
                del log[: len(log) - MAX_EVENTS]
            self.cond.notify_all()

    def _changed(self, sid, deleted=False):
        with self.cond:
            self.change_n += 1
            ev = {"type": "changed", "session": sid, "running": self.running(sid)}
            if deleted:
                ev["deleted"] = True
            self.changes.append((self.change_n, ev))
            del self.changes[:-500]
            self.cond.notify_all()

    def follow(self, sid, after=None, ping=PING_SECONDS, until=None):
        """Events for one session from `after` on, forever (until `until()`
        is true). Without `after`, starts at the live reply if one is running.

        Never yields while holding the lock: the web server resumes this
        generator on whichever worker thread is free, and a lock taken on
        one thread can't be released from another."""
        if not self.store.q("SELECT id FROM sessions WHERE id = ?", (sid,)):
            raise NotFound(sid)
        with self.cond:
            log = self.events.get(sid, [])
            running = self.running(sid)
            if after is None:
                after = (log[0]["seq"] - 1) if (log and running) else self.seq.get(sid, 0)
            hello = {"type": "hello", "running": running, "seq": self.seq.get(sid, 0)}
        yield hello
        while not (until and until()):
            with self.cond:
                log = self.events.get(sid, [])
                out = []
                if log and log[0]["seq"] > after + 1:
                    after = log[0]["seq"] - 1
                    out.append({"type": "resync"})
                out += [e for e in log if e["seq"] > after]
                if not out:
                    self.cond.wait(timeout=ping)
                    log = self.events.get(sid, [])
                    out = [e for e in log if e["seq"] > after]
            if not out:
                if not self.store.q("SELECT id FROM sessions WHERE id = ?", (sid,)):
                    return          # deleted
                yield {"type": "ping"}
                continue
            for e in out:
                if "seq" in e:
                    after = e["seq"]
                yield e

    def watch(self, ping=PING_SECONDS, until=None):
        with self.cond:
            seen = self.change_n
        yield {"type": "hello"}
        while not (until and until()):
            with self.cond:
                out = [e for n, e in self.changes if n > seen]
                if not out:
                    self.cond.wait(timeout=ping)
                    out = [e for n, e in self.changes if n > seen]
                seen = self.change_n
            if not out:
                yield {"type": "ping"}
            for e in out:
                yield e


def _title_from(text):
    line = " ".join(text.split())
    return line if len(line) <= TITLE_CHARS else line[: TITLE_CHARS - 1].rstrip() + "…"


def ndjson(events):
    for ev in events:
        yield json.dumps(ev, ensure_ascii=False) + "\n"


_hub = None
_hub_lock = threading.Lock()


def hub(client=None, error_message=str):
    global _hub
    with _hub_lock:
        if _hub is None:
            _hub = Hub(client=client, error_message=error_message)
        return _hub


def wait_idle(h, sid, timeout=10):
    """For tests: blocks until the session's reply ends."""
    end = time.monotonic() + timeout
    while h.running(sid) and time.monotonic() < end:
        time.sleep(0.01)
