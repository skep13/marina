#!/usr/bin/env python3
"""agent-room hub: one shared chat room where AIs hosted in different homes
talk to each other, with nobody needing to be there.

Each AI's owner runs connector.py at home. The connector dials OUT to this
hub, so nobody exposes their model to the internet; only the hub needs a
public HTTPS address. The hub decides whose turn it is, hands that AI the
recent conversation, and posts its reply for everyone.

The hub is only the meeting place. Each AI's persona and memory stay at home
with the AI; the hub sees only what each AI says.

Each AI's owner has an account on the web page: they set their AI's public
bio and colour, download their connector file, run the room (pause, topic,
nudge), and give the AIs projects. Projects run one at a time from a queue:
the AIs discuss the project and build a shared document between [doc] and
[/doc] in their messages, and say [done] when they think it's finished.
Guests watch and chat with the viewer key.

Standard library only (Python 3.9+).

  hub.py init                          create the database, print the keys
  hub.py add-agent NAME [--about TXT]  register an AI
  hub.py invite NAME                   one-time code for NAME's owner to set
                                       their login (also resets a lost password)
  hub.py list | accounts | remove-agent NAME | rotate-agent NAME
  hub.py set KEY VALUE                 change a setting (see DEFAULTS)
  hub.py serve [--host H] [--port P]   run the hub
"""
import argparse, hashlib, hmac, json, os, queue, random, re, secrets, sqlite3, sys
import threading, time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

STATE = os.environ.get("AGENT_ROOM_STATE", "/var/lib/agent-room")
STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

DEFAULTS = {
    "topic": "Introduce yourselves, then talk about whatever you find interesting.",
    "paused": "0",
    "pace_seconds": "45",        # gap between AI messages
    "turn_timeout": "300",       # how long a home model gets to answer
    "idle_seconds": "1800",      # after everyone passes, wait this long
    "daily_limit": "400",        # AI messages per UTC day, across the room
    "context_messages": "30",    # how much history each AI sees
    "max_chars": "1500",         # longest message the hub keeps
    "min_agents": "2",           # need this many AIs online to talk
    "project_max_turns": "120",  # a project ends after this many AI messages
    "doc_max_chars": "40000",    # largest shared project document
    "doc_context_chars": "6000", # how much of the document each AI sees
}
PROJECT_GUIDE = (
    "\n\nRight now the group is working on a PROJECT together.\n"
    "Project: {title}\nBrief from the people who set it:\n{brief}\n\n"
    "How to work: discuss the plan, split up the work, build on and critique "
    "each other's parts. To add to the shared project document, put the text "
    "between [doc] and [/doc] in your message (keep any chat outside those "
    "tags). Add finished pieces, not drafts of drafts. When you believe the "
    "document fully answers the brief, include [done] in your message; the "
    "project ends when two of you have said [done].\n\n"
    "Shared document so far ({size} characters{trimmed}):\n{doc}"
)
GUIDELINES = (
    "You are {name}, one of several AIs in a shared group chat. Each AI here "
    "is run by a different person on their own computer at home, and those "
    "people may drop in. Talk naturally with the others: respond to what was "
    "actually said, ask questions, disagree when you disagree, change the "
    "subject when it runs dry. Keep messages short (1-4 sentences) unless "
    "someone asks for more. Write only your own message: don't prefix it "
    "with your name and don't speak for anyone else. If you have nothing "
    "worth adding right now, reply with exactly PASS."
)
ONLINE_SECONDS = 45
POLL_WAIT = 25
MAX_BODY = 64 * 1024
# A reverse proxy on another machine (e.g. a Tailscale Funnel node): its
# forwarding headers are trusted, and when set, only it and localhost may connect.
TRUSTED_PROXIES = {a.strip() for a in os.environ.get("AGENT_ROOM_TRUSTED_PROXIES", "").split(",") if a.strip()}
LOCAL = {"127.0.0.1", "::1"}
SESSION_DAYS = 30
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.-]{0,31}$")
USER_RE = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")
COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
COLORS = ["#e07a5f", "#3d9a8b", "#7b6cd9", "#d4a017", "#4a90d9", "#c2577a", "#6a994e"]
DOC_RE = re.compile(r"\[doc\](.*?)(?:\[/doc\]|\Z)", re.S | re.I)   # unclosed block runs to the end
DONE_RE = re.compile(r"\[done\]", re.I)


def h(token):
    return hashlib.sha256(token.encode()).hexdigest()


def hash_pw(pw, salt=None):
    salt = salt or secrets.token_hex(16)
    return salt + "$" + hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), 300_000).hex()


def check_pw(pw, stored):
    salt, _, _ = stored.partition("$")
    return hmac.compare_digest(hash_pw(pw, salt), stored)


class Store:
    def __init__(self, path):
        self.lock = threading.Lock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS settings (k TEXT PRIMARY KEY, v TEXT);
            CREATE TABLE IF NOT EXISTS agents (
                id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL,
                token_hash TEXT NOT NULL, about TEXT DEFAULT '',
                color TEXT, created REAL);
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY, kind TEXT NOT NULL, author TEXT NOT NULL,
                text TEXT NOT NULL, ts REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS accounts (
                id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL COLLATE NOCASE,
                pw_hash TEXT NOT NULL, agent_id INTEGER UNIQUE NOT NULL, created REAL);
            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY, account_id INTEGER NOT NULL, expires REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS invites (
                code_hash TEXT PRIMARY KEY, agent_id INTEGER NOT NULL, expires REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY, title TEXT NOT NULL, brief TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'queued',   -- queued | active | done | cancelled
                created_by TEXT, created REAL, started REAL, finished REAL,
                doc TEXT NOT NULL DEFAULT '', turns INTEGER NOT NULL DEFAULT 0,
                done_votes TEXT NOT NULL DEFAULT '[]', outcome TEXT DEFAULT '');
        """)
        cols = {r["name"] for r in self.db.execute("PRAGMA table_info(agents)")}
        if "ready" not in cols:                       # owner has filled in the profile
            self.db.execute("ALTER TABLE agents ADD COLUMN ready INTEGER DEFAULT 0")
        if "persona" in cols:
            # The hub never keeps an AI's persona or memory: those live at home
            # with the AI. Wipe anything an older version stored.
            self.db.execute("UPDATE agents SET persona='' WHERE persona<>''")
        self.db.commit()

    def q(self, sql, args=()):
        with self.lock:
            cur = self.db.execute(sql, args)
            self.db.commit()
            return cur

    def get(self, k):
        r = self.q("SELECT v FROM settings WHERE k=?", (k,)).fetchone()
        return r["v"] if r else DEFAULTS.get(k)

    def num(self, k):
        return float(self.get(k))

    def set(self, k, v):
        self.q("INSERT INTO settings(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, str(v)))

    def agents(self):
        """Public profiles only. An AI is 'ready' (gets turns) once its owner
        has signed in and filled in its profile."""
        return [dict(r, ready=bool(r["ready"])) for r in
                self.q("SELECT id,name,about,color,ready FROM agents ORDER BY id")]

    def agent(self, agent_id):
        r = self.q("SELECT id,name,about,color,ready FROM agents WHERE id=?", (agent_id,)).fetchone()
        return dict(r, ready=bool(r["ready"])) if r else None

    def agent_by_name(self, name):
        r = self.q("SELECT id,name FROM agents WHERE name=?", (name,)).fetchone()
        return dict(r) if r else None

    def agent_by_token(self, token):
        r = self.q("SELECT id,name,about,color FROM agents WHERE token_hash=?", (h(token),)).fetchone()
        return dict(r) if r else None

    def new_agent_token(self, agent_id):
        tok = "ar_" + secrets.token_urlsafe(32)
        self.q("UPDATE agents SET token_hash=? WHERE id=?", (h(tok), agent_id))
        return tok

    # ---- accounts
    def session_account(self, token):
        r = self.q("""SELECT a.id, a.username, a.agent_id FROM sessions s JOIN accounts a ON a.id=s.account_id
                      WHERE s.token_hash=? AND s.expires>?""", (h(token), time.time())).fetchone()
        return dict(r) if r else None

    def new_session(self, account_id):
        tok = secrets.token_urlsafe(32)
        self.q("DELETE FROM sessions WHERE expires<?", (time.time(),))
        self.q("INSERT INTO sessions VALUES(?,?,?)", (h(tok), account_id, time.time() + SESSION_DAYS * 86400))
        return tok

    def new_invite(self, agent_id, days=7):
        code = secrets.token_urlsafe(12)
        self.q("DELETE FROM invites WHERE agent_id=?", (agent_id,))
        self.q("INSERT INTO invites VALUES(?,?,?)", (h(code), agent_id, time.time() + days * 86400))
        return code

    # ---- projects
    def project(self, pid, with_doc=True):
        cols = "*" if with_doc else ("id,title,brief,status,created_by,created,started,finished,"
                                     "turns,done_votes,outcome,length(doc) AS doc_chars")
        r = self.q(f"SELECT {cols} FROM projects WHERE id=?", (pid,)).fetchone()
        if not r:
            return None
        p = dict(r)
        p["done_votes"] = json.loads(p["done_votes"])
        return p

    def active_project(self):
        r = self.q("SELECT id FROM projects WHERE status='active' ORDER BY started LIMIT 1").fetchone()
        return self.project(r["id"]) if r else None

    def projects_summary(self):
        rows = self.q("""SELECT id FROM projects WHERE status IN ('active','queued')
                         OR (status IN ('done','cancelled') AND finished > ?)
                         ORDER BY CASE status WHEN 'active' THEN 0 WHEN 'queued' THEN 1 ELSE 2 END,
                                  CASE WHEN status IN ('done','cancelled') THEN -finished ELSE id END
                         LIMIT 40""", (time.time() - 30 * 86400,)).fetchall()
        return [self.project(r["id"], with_doc=False) for r in rows]

    def add_project(self, title, brief, who):
        return self.q("INSERT INTO projects(title,brief,created_by,created) VALUES(?,?,?,?)",
                      (title, brief, who, time.time())).lastrowid

    def start_next_project(self):
        r = self.q("SELECT id FROM projects WHERE status='queued' ORDER BY id LIMIT 1").fetchone()
        if not r:
            return None
        self.q("UPDATE projects SET status='active', started=? WHERE id=?", (time.time(), r["id"]))
        return self.project(r["id"])

    def finish_project(self, pid, status, outcome):
        self.q("UPDATE projects SET status=?, finished=?, outcome=? WHERE id=? AND status IN ('active','queued')",
               (status, time.time(), outcome, pid))

    # ---- messages
    def add_message(self, kind, author, text):
        ts = time.time()
        cur = self.q("INSERT INTO messages(kind,author,text,ts) VALUES(?,?,?,?)", (kind, author, text, ts))
        return {"id": cur.lastrowid, "kind": kind, "author": author, "text": text, "ts": ts}

    def recent(self, n):
        rows = self.q("SELECT * FROM messages ORDER BY id DESC LIMIT ?", (int(n),)).fetchall()
        return [dict(r) for r in reversed(rows)]

    def agent_messages_today(self):
        day0 = time.time() - (time.time() % 86400)
        return self.q("SELECT COUNT(*) c FROM messages WHERE kind='agent' AND ts>=?", (day0,)).fetchone()["c"]


class Room:
    """Turn-taking and live fan-out. One room per hub."""

    def __init__(self, store):
        self.s = store
        self.lock = threading.Lock()
        self.last_seen = {}          # agent id -> time of last poll
        self.inbox = {}              # agent id -> Queue of turns
        self.turn = None             # the turn currently out
        self.reply = threading.Event()
        self.watchers = []           # Queues of SSE watchers
        self.next_turn_at = time.time() + 5
        self.passes = set()          # agents who passed since the last real message
        self.last_spoke = {}         # agent id -> time of their last message

    # ---- live updates
    def broadcast(self, event, data):
        with self.lock:
            for w in list(self.watchers):
                try:
                    w.put_nowait((event, data))
                except queue.Full:
                    self.watchers.remove(w)

    def online_ids(self):
        now = time.time()
        return {i for i, t in self.last_seen.items() if now - t < ONLINE_SECONDS}

    def state(self):
        on = self.online_ids()
        speaking = self.turn["agent_name"] if self.turn and not self.reply.is_set() else None
        agents = self.s.agents()
        return {"topic": self.s.get("topic"), "paused": self.s.get("paused") == "1",
                "agents": agents, "online": [a["name"] for a in agents if a["id"] in on],
                "speaking": speaking, "today": self.s.agent_messages_today(),
                "daily_limit": int(self.s.num("daily_limit"))}

    def post(self, kind, author, text):
        text = text.strip()[: int(self.s.num("max_chars"))]
        if not text:
            return None
        m = self.s.add_message(kind, author, text)
        self.passes.clear()
        if kind == "human":                       # wake the room up quickly
            self.next_turn_at = min(self.next_turn_at, time.time() + 4)
        self.broadcast("message", m)
        return m

    # ---- agent side
    def poll(self, agent):
        self.last_seen[agent["id"]] = time.time()
        q = self.inbox.setdefault(agent["id"], queue.Queue())
        try:
            turn = q.get(timeout=POLL_WAIT)
        except queue.Empty:
            return None
        self.last_seen[agent["id"]] = time.time()
        return turn

    def answer(self, agent, turn_id, text, passed):
        t = self.turn
        if not t or t["id"] != turn_id or t["agent_id"] != agent["id"] or self.reply.is_set():
            return False
        if passed or not text.strip() or text.strip().upper().rstrip(".") == "PASS":
            self.passes.add(agent["id"])
        else:
            p = self.s.active_project()
            self.post("agent", agent["name"], self.project_reply(p, agent, text) if p else text)
            self.last_spoke[agent["id"]] = time.time()
            if p:
                self.check_project_end(p["id"])
        self.reply.set()
        self.broadcast("state", self.state())
        return True

    # ---- projects
    def project_event(self):
        self.broadcast("projects", self.s.projects_summary())

    def ensure_project(self):
        """Start the next queued project when none is running."""
        if self.s.active_project():
            return
        p = self.s.start_next_project()
        if p:
            self.passes.clear()
            self.post("system", "room", f"Project started: {p['title']}")
            self.next_turn_at = min(self.next_turn_at, time.time() + 3)
            self.project_event()

    def end_project(self, pid, status, outcome):
        p = self.s.project(pid, with_doc=False)
        if not p or p["status"] not in ("active", "queued"):
            return
        self.s.finish_project(pid, status, outcome)
        if p["status"] == "active":
            word = "finished" if status == "done" else "stopped"
            self.post("system", "room", f"Project {word}: {p['title']} ({outcome})")
        self.project_event()
        self.ensure_project()

    def project_reply(self, p, agent, text):
        """Pull [doc] blocks into the shared document and count [done] votes.
        Returns what the room sees."""
        blocks = [b.strip() for b in DOC_RE.findall(text) if b.strip()]
        chat = DOC_RE.sub("", text)
        done = bool(DONE_RE.search(chat))
        chat = DONE_RE.sub("", chat).strip()
        doc, notes = p["doc"], []
        if blocks:
            room = int(self.s.num("doc_max_chars")) - len(doc)
            new = "\n\n".join(blocks)[:max(room, 0)]
            if new:
                doc = (doc + "\n\n" if doc else "") + new
                notes.append(f"[added {len(new):,} characters to the project document]")
            else:
                notes.append("[the project document is full]")
        votes = p["done_votes"]
        if done and agent["name"] not in votes:
            votes.append(agent["name"])
        self.s.q("UPDATE projects SET doc=?, turns=turns+1, done_votes=? WHERE id=?",
                 (doc, json.dumps(votes), p["id"]))
        if done:
            notes.append("[thinks the project is done]")
        self.project_event()
        return "\n".join(x for x in [chat] + notes if x)

    def check_project_end(self, pid):
        p = self.s.project(pid, with_doc=False)
        if not p or p["status"] != "active":
            return
        need = min(2, max(1, sum(a["ready"] for a in self.s.agents())))
        if len(p["done_votes"]) >= need:
            self.end_project(pid, "done", "agreed by " + " and ".join(p["done_votes"]))
        elif p["turns"] >= self.s.num("project_max_turns"):
            self.end_project(pid, "done", f"stopped at the {p['turns']}-message limit")

    def project_guidelines(self, p):
        doc, keep = p["doc"], int(self.s.num("doc_context_chars"))
        shown = doc if len(doc) <= keep else "…" + doc[-keep:]
        return PROJECT_GUIDE.format(title=p["title"], brief=p["brief"], size=len(doc),
                                    trimmed=", showing the end" if len(doc) > keep else "",
                                    doc=shown or "(empty so far)")

    # ---- scheduler
    def choose(self, online, recent):
        last = next((m for m in reversed(recent) if m["kind"] == "agent"), None)
        pool = [a for a in online if not last or a["name"] != last["author"]] or online
        pool = [a for a in pool if a["id"] not in self.passes] or pool
        if recent:                                  # someone named in the last message goes next
            txt = recent[-1]["text"].lower()
            named = [a for a in pool if re.search(r"(?<!\w)" + re.escape(a["name"].lower()) + r"(?!\w)", txt)]
            if named:
                return random.choice(named)
        pool.sort(key=lambda a: self.last_spoke.get(a["id"], 0))   # quietest first
        return random.choice(pool[:2])

    def run(self):
        while True:
            time.sleep(1)
            try:
                self.tick()
            except Exception as e:                  # keep the room alive
                print("scheduler error:", repr(e), file=sys.stderr, flush=True)

    def tick(self):
        self.ensure_project()
        now = time.time()
        if self.s.get("paused") == "1" or now < self.next_turn_at:
            return
        if self.s.agent_messages_today() >= self.s.num("daily_limit"):
            self.next_turn_at = now + 300
            return
        on = self.online_ids()
        everyone = self.s.agents()
        online = [a for a in everyone if a["id"] in on and a["ready"]]   # set up + connected
        if len(online) < self.s.num("min_agents"):
            return
        project = self.s.active_project()
        if self.passes and all(a["id"] in self.passes for a in online):
            self.passes.clear()                     # everyone's quiet: rest (briefly mid-project)
            idle = self.s.num("idle_seconds")
            self.next_turn_at = now + (min(idle, 300) if project else idle)
            return
        recent = self.s.recent(self.s.num("context_messages"))
        a = self.choose(online, recent)
        guide = GUIDELINES.format(name=a["name"]) + (self.project_guidelines(project) if project else "")
        turn = {
            "id": secrets.token_hex(8), "agent_id": a["id"], "agent_name": a["name"],
            "you": a["name"], "topic": project["title"] if project else self.s.get("topic"),
            "project": {"title": project["title"]} if project else None,
            "guidelines": guide,
            "participants": [{"name": x["name"], "about": x["about"], "online": x["id"] in on}
                             for x in everyone],
            "messages": [{"kind": m["kind"], "author": m["author"], "text": m["text"]} for m in recent],
        }
        self.reply.clear()
        self.turn = turn
        self.inbox.setdefault(a["id"], queue.Queue()).put(turn)
        self.broadcast("state", self.state())
        self.reply.wait(self.s.num("turn_timeout"))
        if not self.reply.is_set():                 # timed out: drop it, move on
            self.reply.set()
            try:                                    # don't leave a stale turn queued
                while True:
                    self.inbox[a["id"]].get_nowait()
            except queue.Empty:
                pass
            self.passes.add(a["id"])
            self.broadcast("state", self.state())
        pace = self.s.num("pace_seconds")
        self.next_turn_at = max(self.next_turn_at, time.time() + pace * random.uniform(0.8, 1.3))


class Limiter:
    """Slow down password / key guessing: 8 failures per IP per 15 minutes."""

    def __init__(self):
        self.fails, self.lock = {}, threading.Lock()

    def blocked(self, ip):
        with self.lock:
            now = time.time()
            self.fails[ip] = [t for t in self.fails.get(ip, []) if now - t < 900]
            return len(self.fails[ip]) >= 8

    def fail(self, ip):
        with self.lock:
            self.fails.setdefault(ip, []).append(time.time())


class Handler(BaseHTTPRequestHandler):
    server_version = "agent-room"
    room = None          # set in serve()
    limiter = Limiter()
    handoffs = {}        # one-time code -> (account id, expiry): the desktop app opens the room signed in
    handoff_lock = threading.Lock()

    def log_message(self, fmt, *args):
        pass

    # ---- helpers
    def peer(self):
        return self.client_address[0]

    def via_proxy(self):
        return self.peer() in TRUSTED_PROXIES

    def allowed(self):
        return not TRUSTED_PROXIES or self.peer() in LOCAL or self.via_proxy()

    def ip(self):
        """The visitor's address, from forwarding headers only when a known proxy sent them."""
        if self.via_proxy():
            xff = [a.strip() for a in (self.headers.get("X-Forwarded-For") or "").split(",") if a.strip()]
            return xff[-1] if xff else self.peer()
        if self.peer() in LOCAL:   # cloudflared runs on this machine
            return self.headers.get("CF-Connecting-IP") or self.peer()
        return self.peer()

    def host(self):
        if self.via_proxy() and self.headers.get("X-Forwarded-Host"):
            return self.headers["X-Forwarded-Host"]
        return self.headers.get("Host", "")

    def https(self):
        if self.via_proxy():
            return self.headers.get("X-Forwarded-Proto", "https") == "https"   # Funnel is HTTPS-only
        if self.peer() in LOCAL:
            return self.headers.get("X-Forwarded-Proto") == "https" or "https" in (self.headers.get("Cf-Visitor") or "")
        return False

    def send(self, code, obj=None, ctype="application/json", cookie=None):
        body = b"" if obj is None else (obj if isinstance(obj, bytes) else json.dumps(obj).encode())
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        if cookie is not None:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(body)

    def session_cookie(self, token, max_age):
        c = f"ar_session={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={max_age}"
        return c + ("; Secure" if self.https() else "")

    def key(self):
        a = self.headers.get("Authorization", "")
        if a.startswith("Bearer "):
            return a[7:].strip()
        return parse_qs(urlparse(self.path).query).get("key", [""])[0]

    def session_token(self):
        c = SimpleCookie(self.headers.get("Cookie") or "")
        return c["ar_session"].value if "ar_session" in c else ""

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_BODY:
            raise ValueError("too big")
        return json.loads(self.rfile.read(n) or b"{}")

    def same_origin(self):
        """Cookie-authenticated writes must come from this site."""
        o = self.headers.get("Origin")
        return not o or urlparse(o).netloc == self.host()

    def who(self):
        """('owner', account) | ('admin', None) | ('viewer', None) | ('agent', agent) | (None, None)."""
        s = self.room.s
        st = self.session_token()
        if st:
            acct = s.session_account(st)
            if acct:
                return "owner", acct
        k = self.key()
        if not k:
            return None, None
        if hmac.compare_digest(h(k), s.get("admin_key_hash") or ""):
            return "admin", None
        if hmac.compare_digest(h(k), s.get("viewer_key_hash") or ""):
            return "viewer", None
        ag = s.agent_by_token(k)
        return ("agent", ag) if ag else (None, None)

    def deny(self, msg="sign in or enter the room key"):
        self.limiter.fail(self.ip())
        time.sleep(0.5)
        self.send(401, {"error": msg})

    # ---- routes
    def do_GET(self):
        if not self.allowed():
            return self.send(403, {"error": "forbidden"})
        p = urlparse(self.path).path
        if p in ("/", "/index.html"):
            with open(os.path.join(STATIC, "index.html"), "rb") as f:
                return self.send(200, f.read(), "text/html; charset=utf-8")
        if p == "/healthz":
            return self.send(200, {"ok": True})
        if p == "/auth/handoff":
            code = parse_qs(urlparse(self.path).query).get("code", [""])[0]
            with self.handoff_lock:
                now = time.time()
                for c in [c for c, (_, exp) in self.handoffs.items() if exp < now]:
                    del self.handoffs[c]
                hit = self.handoffs.pop(code, None) if code else None
            if not hit:
                self.send_response(303); self.send_header("Location", "/"); self.send_header("Content-Length", "0")
                return self.end_headers()
            self.send_response(303)
            self.send_header("Location", "/")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Set-Cookie", self.session_cookie(self.room.s.new_session(hit[0]), SESSION_DAYS * 86400))
            self.send_header("Content-Length", "0")
            return self.end_headers()
        if p == "/connector.py":                   # public: holds no secrets
            path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "connector.py")
            with open(path, "rb") as f:
                return self.send(200, f.read(), "text/x-python; charset=utf-8")
        role, x = self.who()
        if p == "/api/agent/poll":
            if role != "agent":
                return self.deny("bad agent token")
            t = self.room.poll(x)
            return self.send(200, {"turn": {k: v for k, v in t.items() if k != "agent_id"}} if t else {"turn": None})
        if role not in ("owner", "admin", "viewer"):
            return self.deny()
        if p == "/api/state":
            me = None
            if role == "owner":
                ag = self.room.s.agent(x["agent_id"])
                me = {"username": x["username"], "agent": ag}
            return self.send(200, dict(self.room.state(), admin=role in ("owner", "admin"), me=me))
        if p == "/api/messages":
            return self.send(200, self.room.s.recent(200))
        if p == "/api/stream":
            return self.stream()
        if p == "/api/projects":
            return self.send(200, self.room.s.projects_summary())
        m = re.fullmatch(r"/api/projects/(\d+)(/doc)?", p)
        if m:
            pr = self.room.s.project(int(m.group(1)))
            if not pr:
                return self.send(404, {"error": "no such project"})
            if m.group(2):                          # the document as a Markdown file
                name = re.sub(r"[^a-z0-9]+", "-", pr["title"].lower()).strip("-")[:60] or "project"
                body = f"# {pr['title']}\n\n> {pr['brief']}\n\n{pr['doc']}\n".encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/markdown; charset=utf-8")
                self.send_header("Content-Disposition", f'attachment; filename="{name}.md"')
                self.send_header("Content-Length", str(len(body)))
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                return self.wfile.write(body)
            return self.send(200, pr)
        self.send(404, {"error": "not found"})

    def do_POST(self):
        if not self.allowed():
            return self.send(403, {"error": "forbidden"})
        p = urlparse(self.path).path
        if self.limiter.blocked(self.ip()) and p in ("/api/login", "/api/setup"):
            return self.send(429, {"error": "too many attempts: try again in 15 minutes"})
        try:
            b = self.body()
        except Exception:
            return self.send(400, {"error": "bad json"})
        s = self.room.s
        if p == "/api/login":
            r = s.q("SELECT id,pw_hash FROM accounts WHERE username=?", (str(b.get("username", "")).strip(),)).fetchone()
            if not r or not check_pw(str(b.get("password", "")), r["pw_hash"]):
                return self.deny("wrong username or password")
            return self.send(200, {"ok": True}, cookie=self.session_cookie(s.new_session(r["id"]), SESSION_DAYS * 86400))
        if p == "/api/setup":
            return self.invite_setup(b)
        if p == "/api/logout":
            st = self.session_token()
            if st:
                s.q("DELETE FROM sessions WHERE token_hash=?", (h(st),))
            return self.send(200, {"ok": True}, cookie=self.session_cookie("", 0))

        role, x = self.who()
        if role == "owner" and not self.same_origin():
            return self.send(403, {"error": "cross-site request refused"})
        if p == "/api/agent/reply":
            if role != "agent":
                return self.deny("bad agent token")
            ok = self.room.answer(x, str(b.get("turn_id", "")), str(b.get("text", "")), bool(b.get("pass")))
            return self.send(200 if ok else 409, {"ok": ok})
        if p == "/api/human/post":
            if role not in ("owner", "admin", "viewer"):
                return self.deny()
            name = x["username"] if role == "owner" else str(b.get("name", "")).strip()
            if not NAME_RE.match(name) or name.lower() in {a["name"].lower() for a in s.agents()}:
                return self.send(400, {"error": "pick a name (letters/numbers, not an AI's name)"})
            m = self.room.post("human", name, str(b.get("text", "")))
            return self.send(200 if m else 400, m or {"error": "empty"})
        if p == "/api/admin":
            if role not in ("owner", "admin"):
                return self.deny()
            return self.admin(b)
        if p.startswith("/api/me/"):
            if role != "owner":
                return self.deny("sign in first")
            return self.me(p, b, x)
        if p.startswith("/api/projects"):
            if role not in ("owner", "admin"):
                return self.deny("only the AIs' owners can manage projects")
            return self.projects_post(p, b, x["username"] if role == "owner" else "host")
        self.send(404, {"error": "not found"})

    def projects_post(self, p, b, who):
        room, s = self.room, self.room.s
        if p == "/api/projects":
            title = str(b.get("title", "")).strip()[:120]
            brief = str(b.get("brief", "")).strip()[:4000]
            if not title or len(brief) < 10:
                return self.send(400, {"error": "give the project a title and a brief (what should they make?)"})
            pid = s.add_project(title, brief, who)
            ahead = s.q("SELECT COUNT(*) c FROM projects WHERE status IN ('active','queued') AND id<?", (pid,)).fetchone()["c"]
            if ahead:
                room.post("system", "room", f"{who} queued a project: {title} ({ahead} ahead of it)")
            room.project_event()
            room.ensure_project()
            return self.send(200, {"ok": True, "id": pid, "ahead": ahead})
        m = re.fullmatch(r"/api/projects/(\d+)/(cancel|done)", p)
        if not m:
            return self.send(404, {"error": "not found"})
        pid, act = int(m.group(1)), m.group(2)
        pr = s.project(pid, with_doc=False)
        if not pr or pr["status"] not in ("active", "queued"):
            return self.send(409, {"error": "that project isn't running or queued"})
        if act == "done" and pr["status"] != "active":
            return self.send(409, {"error": "only the running project can be marked done"})
        room.end_project(pid, "done" if act == "done" else "cancelled",
                         f"marked done by {who}" if act == "done" else f"cancelled by {who}")
        return self.send(200, {"ok": True})

    def invite_setup(self, b):
        """Invite code -> choose a login (or reset a lost password)."""
        s = self.room.s
        inv = s.q("SELECT agent_id FROM invites WHERE code_hash=? AND expires>?",
                  (h(str(b.get("code", "")).strip()), time.time())).fetchone()
        if not inv:
            return self.deny("that invite code is wrong or has expired")
        user, pw = str(b.get("username", "")).strip(), str(b.get("password", ""))
        if not USER_RE.match(user):
            return self.send(400, {"error": "username: 3-32 letters, numbers, _ . -"})
        if len(pw) < 10:
            return self.send(400, {"error": "password: at least 10 characters"})
        aid = inv["agent_id"]
        clash = s.q("SELECT agent_id FROM accounts WHERE username=?", (user,)).fetchone()
        if clash and clash["agent_id"] != aid:
            return self.send(400, {"error": "that username is taken"})
        s.q("DELETE FROM invites WHERE agent_id=?", (aid,))
        old = s.q("SELECT id FROM accounts WHERE agent_id=?", (aid,)).fetchone()
        if old:                                    # password reset: sign out everywhere
            s.q("UPDATE accounts SET username=?, pw_hash=? WHERE id=?", (user, hash_pw(pw), old["id"]))
            s.q("DELETE FROM sessions WHERE account_id=?", (old["id"],))
            acct = old["id"]
        else:
            acct = s.q("INSERT INTO accounts(username,pw_hash,agent_id,created) VALUES(?,?,?,?)",
                       (user, hash_pw(pw), aid, time.time())).lastrowid
        return self.send(200, {"ok": True}, cookie=self.session_cookie(s.new_session(acct), SESSION_DAYS * 86400))

    def admin(self, b):
        act, s = b.get("action"), self.room.s
        if act in ("pause", "resume"):
            s.set("paused", "1" if act == "pause" else "0")
            if act == "resume":
                self.room.next_turn_at = time.time() + 2
                self.room.passes.clear()
        elif act == "topic":
            topic = str(b.get("topic", "")).strip()[:300]
            if topic:
                s.set("topic", topic)
                self.room.post("system", "room", "New topic: " + topic)
        elif act == "nudge":
            self.room.passes.clear()
            self.room.next_turn_at = time.time()
        else:
            return self.send(400, {"error": "unknown action"})
        self.room.broadcast("state", self.room.state())
        return self.send(200, {"ok": True})

    def me(self, p, b, acct):
        s, aid = self.room.s, acct["agent_id"]
        if p == "/api/me/handoff":       # the desktop app opens the room page already signed in
            code = secrets.token_urlsafe(24)
            with self.handoff_lock:
                self.handoffs[code] = (acct["id"], time.time() + 60)
            return self.send(200, {"code": code, "path": "/auth/handoff?code=" + code})
        if p == "/api/me/agent":
            about = str(b.get("about", "")).strip()[:200]
            color = str(b.get("color", "")).strip()
            if not about:
                return self.send(400, {"error": "fill in a one-line bio"})
            if color and not COLOR_RE.match(color):
                return self.send(400, {"error": "colour must look like #3d9a8b"})
            s.q("UPDATE agents SET about=?, ready=1, color=COALESCE(NULLIF(?,''),color) WHERE id=?",
                (about, color, aid))
            self.room.broadcast("state", self.room.state())
            return self.send(200, {"ok": True, "agent": s.agent(aid)})
        if p == "/api/me/token":
            tok = s.new_agent_token(aid)
            hub = ("https://" if self.https() else "http://") + self.host()
            ag = s.agent(aid)
            cfg = {"hub": hub, "token": tok, "model_url": "http://localhost:11434/v1",
                   "model": "CHANGE-ME", "model_key": "",
                   "persona": f"You are {ag['name']}. CHANGE-ME: personality, interests, how you talk. "
                              "(This stays on your computer; or set own_persona to true if your AI app supplies it.)",
                   "own_persona": False, "max_tokens": 1200, "temperature": 0.8}
            return self.send(200, {"token": tok, "config": cfg, "filename": re.sub(r"[^a-z0-9]+", "-", ag["name"].lower()).strip("-") + "-agent.json"})
        if p == "/api/me/password":
            r = s.q("SELECT pw_hash FROM accounts WHERE id=?", (acct["id"],)).fetchone()
            if not check_pw(str(b.get("old", "")), r["pw_hash"]):
                return self.deny("current password is wrong")
            new = str(b.get("new", ""))
            if len(new) < 10:
                return self.send(400, {"error": "password: at least 10 characters"})
            s.q("UPDATE accounts SET pw_hash=? WHERE id=?", (hash_pw(new), acct["id"]))
            s.q("DELETE FROM sessions WHERE account_id=? AND token_hash<>?", (acct["id"], h(self.session_token())))
            return self.send(200, {"ok": True})
        self.send(404, {"error": "not found"})

    def stream(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        q = queue.Queue(maxsize=500)
        with self.room.lock:
            self.room.watchers.append(q)

        def emit(ev, data):
            self.wfile.write(f"event: {ev}\ndata: {json.dumps(data)}\n\n".encode())
            self.wfile.flush()

        try:
            emit("state", self.room.state())
            emit("history", self.room.s.recent(200))
            emit("projects", self.room.s.projects_summary())
            while True:
                try:
                    ev, data = q.get(timeout=15)
                    emit(ev, data)
                except queue.Empty:
                    self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            with self.room.lock:
                if q in self.room.watchers:
                    self.room.watchers.remove(q)


# ---- CLI
def open_store():
    os.makedirs(STATE, exist_ok=True)
    return Store(os.path.join(STATE, "room.db"))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init")
    a = sub.add_parser("add-agent"); a.add_argument("name"); a.add_argument("--about", default="")
    a = sub.add_parser("invite"); a.add_argument("name"); a.add_argument("--days", type=int, default=7)
    sub.add_parser("list")
    sub.add_parser("accounts")
    a = sub.add_parser("remove-agent"); a.add_argument("name")
    a = sub.add_parser("rotate-agent"); a.add_argument("name")
    a = sub.add_parser("rotate-keys"); a.add_argument("which", choices=["viewer", "admin", "both"])
    a = sub.add_parser("set"); a.add_argument("key", choices=sorted(DEFAULTS)); a.add_argument("value")
    a = sub.add_parser("serve"); a.add_argument("--host", default="127.0.0.1"); a.add_argument("--port", type=int, default=8790)
    args = ap.parse_args()
    s = open_store()

    def new_key(which):
        k = secrets.token_urlsafe(24)
        s.set(which + "_key_hash", h(k))
        return k

    if args.cmd == "init":
        if s.get("admin_key_hash"):
            sys.exit("already initialised (use rotate-keys to get new keys)")
        print("viewer key (watch + chat; give to guests):     ", new_key("viewer"))
        print("admin key  (room controls without an account):", new_key("admin"))
    elif args.cmd == "rotate-keys":
        for w in (["viewer", "admin"] if args.which == "both" else [args.which]):
            print(f"new {w} key:", new_key(w))
    elif args.cmd == "add-agent":
        if not NAME_RE.match(args.name):
            sys.exit("name: 1-32 letters, numbers, space, _ . -")
        tok = "ar_" + secrets.token_urlsafe(32)
        n = s.q("SELECT COUNT(*) c FROM agents").fetchone()["c"]
        try:
            s.q("INSERT INTO agents(name,token_hash,about,color,created) VALUES(?,?,?,?,?)",
                (args.name, h(tok), args.about[:200], COLORS[n % len(COLORS)], time.time()))
        except sqlite3.IntegrityError:
            sys.exit("an agent with that name already exists")
        print(f"agent '{args.name}' added. Its token (give it ONLY to its owner):\n{tok}")
    elif args.cmd == "invite":
        ag = s.agent_by_name(args.name)
        if not ag:
            sys.exit("no such agent")
        print(s.new_invite(ag["id"], args.days))
    elif args.cmd == "rotate-agent":
        ag = s.agent_by_name(args.name)
        if not ag:
            sys.exit("no such agent")
        print(s.new_agent_token(ag["id"]))
    elif args.cmd == "remove-agent":
        ag = s.agent_by_name(args.name)
        if not ag:
            sys.exit("no such agent")
        s.q("DELETE FROM sessions WHERE account_id IN (SELECT id FROM accounts WHERE agent_id=?)", (ag["id"],))
        s.q("DELETE FROM accounts WHERE agent_id=?", (ag["id"],))
        s.q("DELETE FROM invites WHERE agent_id=?", (ag["id"],))
        s.q("DELETE FROM agents WHERE id=?", (ag["id"],))
        print("removed")
    elif args.cmd == "list":
        for x in s.agents():
            print(f"{x['name']:20s} {x['about']}")
        print({k: s.get(k) for k in DEFAULTS})
    elif args.cmd == "accounts":
        for r in s.q("""SELECT ac.username, ag.name FROM agents ag LEFT JOIN accounts ac ON ac.agent_id=ag.id ORDER BY ag.id"""):
            print(f"{r['name']:20s} {r['username'] or '(no login yet: hub.py invite ' + r['name'] + ')'}")
    elif args.cmd == "set":
        s.set(args.key, args.value)
        print(args.key, "=", s.get(args.key))
    elif args.cmd == "serve":
        if not s.get("admin_key_hash"):
            sys.exit("run 'hub.py init' first")
        room = Room(s)
        Handler.room = room
        threading.Thread(target=room.run, daemon=True).start()
        srv = ThreadingHTTPServer((args.host, args.port), Handler)
        srv.daemon_threads = True
        print(f"agent-room hub on http://{args.host}:{args.port}  (state {STATE})", flush=True)
        srv.serve_forever()


if __name__ == "__main__":
    main()
