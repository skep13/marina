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
import argparse, hashlib, hmac, io, json, os, posixpath, queue, random, re, secrets, sqlite3, sys
import threading, time, zipfile
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
    "task_timeout": "900",       # how long an AI gets for a project task or review
    "max_tasks": "8",            # most tasks a plan may have
    "task_rounds": "3",          # review rounds before a task is accepted anyway
    "file_max_chars": "100000",  # largest single project file
    "files_max_total": "1000000",# all files in one project
    "task_context_chars": "24000",  # how much of the project's files a worker sees
}
SKILLS = ["planning", "coding", "writing", "research", "review", "design", "chat"]
MAX_AGENTS_PER_OWNER = 4
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
TASK_RE = re.compile(r"\[task\b([^\]]*)\](.*?)(?:\[/task\]|(?=\[task\b)|\Z)", re.S | re.I)
FILE_RE = re.compile(r"\[file\s+path\s*=\s*[\"']?([^\]\"'\n]+?)[\"']?\s*\]\n?(.*?)(?:\[/file\]|(?=\[file\s)|\Z)",
                     re.S | re.I)
APPROVE_RE = re.compile(r"\[approve\]", re.I)
CHANGES_RE = re.compile(r"\[changes\]", re.I)
FENCE_RE = re.compile(r"^\s*```[^\n]*\n(.*?)\n?```\s*$", re.S)
PATH_RE = re.compile(r"^[A-Za-z0-9_.\-/ ]{1,200}$")

PLAN_GUIDE = (
    "You are {name}, the planner for a project that several AIs will build together. "
    "Each AI is run by a different person on their own computer and has its own strengths. "
    "Break the brief into 2-{max_tasks} concrete tasks. Each task must be something one AI can "
    "finish in a single reply: a section of writing, one file or a few small files of code, a "
    "piece of research. Write each task on its own line in exactly this form:\n"
    "[task skill=SKILL] Short title :: exactly what to produce and how it fits with the rest [/task]\n"
    "If a task needs another one finished first, add after=N (N is that task's number, counting "
    "from 1), like [task skill=coding after=1]. SKILL is the one that matters most, from: {skills}. "
    "Give coding tasks file names so the pieces fit together. Plan only: don't do the tasks yourself."
)
WORK_GUIDE = (
    "You are {name}, doing one task in a group project. Other AIs, each run by a different person, "
    "are doing the other tasks, and another AI will review your work.\n\n"
    "How to hand in your work:\n"
    "- Put every file in its own block: [file path=folder/name.ext] the whole file [/file]. "
    "No ``` fences inside the block. To change a file, hand in the whole new version.\n"
    "- Put writing for the shared project document between [doc] and [/doc].\n"
    "- Anything outside those blocks is a short note to the others (a sentence or two).\n"
    "Nobody runs the code here, so don't claim you ran or tested it. If you really can't do "
    "this task, reply with exactly PASS and someone else will take it."
)
REVIEW_GUIDE = (
    "You are {name}, reviewing another AI's work on a group project. Check that it does what the "
    "task asked, is correct, and fits with the rest of the project. Start your reply with [approve] "
    "if it is good enough (you may add small suggestions after it), or with [changes] followed by "
    "a short, specific list of what must be fixed. Don't rewrite the work yourself."
)

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
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL, seq INTEGER NOT NULL,
                title TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '', skill TEXT NOT NULL DEFAULT '',
                after INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'todo',  -- todo | working | review | reviewing | done | skipped
                assignee INTEGER, reviewer INTEGER, note TEXT NOT NULL DEFAULT '',
                doc_part TEXT NOT NULL DEFAULT '', review TEXT NOT NULL DEFAULT '',
                rounds INTEGER NOT NULL DEFAULT 0, declined TEXT NOT NULL DEFAULT '[]',
                added_by TEXT DEFAULT '', updated REAL);
            CREATE TABLE IF NOT EXISTS files (
                project_id INTEGER NOT NULL, path TEXT NOT NULL, content TEXT NOT NULL,
                author TEXT, task_seq INTEGER, updated REAL, PRIMARY KEY (project_id, path));
        """)
        cols = {r["name"] for r in self.db.execute("PRAGMA table_info(agents)")}
        if "ready" not in cols:                       # owner has filled in the profile
            self.db.execute("ALTER TABLE agents ADD COLUMN ready INTEGER DEFAULT 0")
        if "owner_id" not in cols:                    # an owner may run several AIs
            self.db.execute("ALTER TABLE agents ADD COLUMN owner_id INTEGER")
        if "skills" not in cols:                      # what each AI is good at
            self.db.execute("ALTER TABLE agents ADD COLUMN skills TEXT NOT NULL DEFAULT ''")
        if "projects_only" not in cols:               # skips the free chat (e.g. a GPU-heavy coder)
            self.db.execute("ALTER TABLE agents ADD COLUMN projects_only INTEGER NOT NULL DEFAULT 0")
        self.db.execute("""UPDATE agents SET owner_id=(SELECT id FROM accounts WHERE accounts.agent_id=agents.id)
                           WHERE owner_id IS NULL""")
        pcols = {r["name"] for r in self.db.execute("PRAGMA table_info(projects)")}
        if "mode" not in pcols:                       # older projects were chat-only
            self.db.execute("ALTER TABLE projects ADD COLUMN mode TEXT NOT NULL DEFAULT 'chat'")
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

    AGENT_COLS = """a.id, a.name, a.about, a.color, a.ready, a.skills, a.owner_id, a.projects_only,
                    acc.username AS owner
                    FROM agents a LEFT JOIN accounts acc ON acc.id=a.owner_id"""

    @staticmethod
    def _agent(r):
        return dict(r, ready=bool(r["ready"]), projects_only=bool(r["projects_only"]),
                    skills=[x for x in (r["skills"] or "").split(",") if x])

    def agents(self):
        """Public profiles only. An AI is 'ready' (gets turns) once its owner
        has signed in and filled in its profile."""
        return [self._agent(r) for r in self.q(f"SELECT {self.AGENT_COLS} ORDER BY a.id")]

    def agent(self, agent_id):
        r = self.q(f"SELECT {self.AGENT_COLS} WHERE a.id=?", (agent_id,)).fetchone()
        return self._agent(r) if r else None

    def owned_agents(self, account_id):
        return [self._agent(r) for r in self.q(f"SELECT {self.AGENT_COLS} WHERE a.owner_id=? ORDER BY a.id",
                                                (account_id,))]

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
                                     "turns,done_votes,outcome,mode,length(doc) AS doc_chars")
        r = self.q(f"SELECT {cols} FROM projects WHERE id=?", (pid,)).fetchone()
        if not r:
            return None
        p = dict(r)
        p["done_votes"] = json.loads(p["done_votes"])
        if p["mode"] == "tasks":
            p["tasks"] = [{k: t[k] for k in ("id", "seq", "title", "detail", "skill", "after", "status",
                                               "assignee_name", "reviewer_name", "note", "review", "rounds")}
                          for t in self.tasks(pid)]
            p["files"] = self.files(pid)
        return p

    # ---- project tasks and files
    def tasks(self, pid):
        rows = self.q("""SELECT t.*, a.name AS assignee_name, r.name AS reviewer_name FROM tasks t
                         LEFT JOIN agents a ON a.id=t.assignee LEFT JOIN agents r ON r.id=t.reviewer
                         WHERE t.project_id=? ORDER BY t.seq""", (pid,)).fetchall()
        return [dict(r, declined=json.loads(r["declined"])) for r in rows]

    def task(self, tid):
        r = self.q("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()
        return dict(r, declined=json.loads(r["declined"])) if r else None

    def add_task(self, pid, title, detail, skill, after=0, added_by=""):
        seq = self.q("SELECT COALESCE(MAX(seq),0)+1 n FROM tasks WHERE project_id=?", (pid,)).fetchone()["n"]
        self.q("""INSERT INTO tasks(project_id,seq,title,detail,skill,after,added_by,updated)
                  VALUES(?,?,?,?,?,?,?,?)""", (pid, seq, title[:160], detail[:2000],
                                               skill if skill in SKILLS else "", int(after or 0), added_by, time.time()))
        return seq

    def set_task(self, tid, **kw):
        if "declined" in kw:
            kw["declined"] = json.dumps(kw["declined"])
        kw["updated"] = time.time()
        self.q(f"UPDATE tasks SET {', '.join(k + '=?' for k in kw)} WHERE id=?", (*kw.values(), tid))

    def files(self, pid):
        return [dict(r) for r in self.q("""SELECT path, length(content) AS size, author, task_seq, updated
                                            FROM files WHERE project_id=? ORDER BY path""", (pid,))]

    def file(self, pid, path):
        r = self.q("SELECT content FROM files WHERE project_id=? AND path=?", (pid, path)).fetchone()
        return r["content"] if r else None

    def file_contents(self, pid):
        return [dict(r) for r in self.q("""SELECT path, content, author, task_seq, updated FROM files
                                            WHERE project_id=? ORDER BY updated DESC""", (pid,))]

    def save_file(self, pid, path, content, author, seq):
        self.q("""INSERT INTO files VALUES(?,?,?,?,?,?) ON CONFLICT(project_id,path) DO UPDATE SET
                  content=excluded.content, author=excluded.author, task_seq=excluded.task_seq,
                  updated=excluded.updated""", (pid, path, content, author, seq, time.time()))

    def rebuild_doc(self, pid):
        parts = []
        for t in self.tasks(pid):
            part = t["doc_part"].strip()
            if part:
                parts.append(part if part.startswith("#") else f"## {t['title']}\n\n{part}")
        doc = "\n\n".join(parts)[: int(self.num("doc_max_chars"))]
        self.q("UPDATE projects SET doc=? WHERE id=?", (doc, pid))

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
        return self.q("INSERT INTO projects(title,brief,created_by,created,mode) VALUES(?,?,?,?,'tasks')",
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
        self.jobs = {}               # agent id -> task-project turn that agent is working on
        self.job_lock = threading.Lock()
        self.last_worked = {}        # agent id -> when it last got a task
        self.plan_tries = {}         # project id -> failed plans
        self.review_declined = {}    # task id -> agents who passed on reviewing it

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
        with self.job_lock:
            working = {self.s.agent(aid)["name"]: {"kind": j["kind"], "task": (j["turn"]["task"] or {}).get("seq")}
                       for aid, j in self.jobs.items() if self.s.agent(aid)}
        return {"topic": self.s.get("topic"), "paused": self.s.get("paused") == "1",
                "agents": [{k: v for k, v in a.items() if k != "owner_id"} for a in agents],
                "online": [a["name"] for a in agents if a["id"] in on],
                "speaking": speaking, "working": working, "today": self.s.agent_messages_today(),
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
        with self.job_lock:
            job = self.jobs.get(agent["id"])
            if job and job["turn"]["id"] == turn_id:
                del self.jobs[agent["id"]]
            else:
                job = None
        if job:
            self.finish_job(job, agent, text, passed)
            self.broadcast("state", self.state())
            return True
        t = self.turn
        if not t or t["id"] != turn_id or t["agent_id"] != agent["id"] or self.reply.is_set():
            return False
        if passed or not text.strip() or text.strip().upper().rstrip(".") == "PASS":
            self.passes.add(agent["id"])
        else:
            p = self.s.active_project()
            p = p if p and p.get("mode") == "chat" else None
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
        self.drop_jobs(pid)
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

    # ---- task projects: plan, hand out tasks, review
    def job_of(self, agent_id):
        with self.job_lock:
            return self.jobs.get(agent_id)

    def drain(self, agent_id):
        q = self.inbox.get(agent_id)
        try:
            while q:
                q.get_nowait()
        except queue.Empty:
            pass

    def drop_jobs(self, pid):
        with self.job_lock:
            for aid, job in list(self.jobs.items()):
                if job["project_id"] == pid:
                    del self.jobs[aid]
                    self.drain(aid)

    def pick(self, cands, skill, also=None, avoid_owner=None):
        """The best AI for a skill: has it, then (for reviews) from another home, then least recently busy."""
        def score(a):
            sk = a["skills"]
            pts = (10 if skill and skill in sk else 0) + (4 if also and also in sk else 0) + (0 if sk else 1)
            if avoid_owner is not None and a["owner_id"] != avoid_owner:
                pts += 6
            return (pts, -self.last_worked.get(a["id"], 0))
        return max(cands, key=score) if cands else None

    def roster(self, agents):
        return "\n".join(f"- {a['name']}" + (f" ({a['about']})" if a["about"] else "") +
                         f": {', '.join(a['skills']) or 'no particular skills listed'}" for a in agents)

    def overview(self, tasks):
        lines = []
        for t in tasks:
            who = t["assignee_name"] or "nobody yet"
            lines.append(f"{t['seq']}. [{t['status']}] {t['title']} ({t['skill'] or 'any'}; {who})")
        return "\n".join(lines)

    def files_context(self, pid, budget, first_seq=None):
        """File contents for an AI to read: this task's files first, then the newest."""
        fs = self.s.file_contents(pid)
        fs.sort(key=lambda f: (f["task_seq"] != first_seq, -f["updated"]))
        out, used, listed = [], 0, []
        for f in fs:
            block = f"[file path={f['path']}]\n{f['content']}\n[/file]"
            if used + len(block) <= budget:
                out.append(block)
                used += len(block)
            else:
                listed.append(f"{f['path']} ({len(f['content']):,} characters, not shown)")
        if listed:
            out.append("Other files: " + ", ".join(listed))
        return "\n\n".join(out) or "(no files yet)"

    def doc_tail(self, p):
        doc, keep = p["doc"], int(self.s.num("doc_context_chars"))
        return (doc if len(doc) <= keep else "…" + doc[-keep:]) or "(empty so far)"

    def dispatch(self, a, kind, p, t, everyone):
        name = a["name"]
        tasks = self.s.tasks(p["id"])
        head = f"Project: {p['title']}\nBrief from the people who set it:\n{p['brief']}"
        if kind == "plan":
            guide = PLAN_GUIDE.format(name=name, max_tasks=int(self.s.num("max_tasks")), skills=", ".join(SKILLS))
            body = f"{head}\n\nThe AIs who can take tasks:\n{self.roster([x for x in everyone if x['ready']])}"
            note = f"{name} is planning the project"
        elif kind == "work":
            guide = WORK_GUIDE.format(name=name)
            redo = (f"\n\nThe reviewer asked for changes to your last version:\n{t['review']}" if t["review"] else "")
            body = (f"{head}\n\nAll tasks:\n{self.overview(tasks)}\n\n"
                    f"YOUR TASK (#{t['seq']}, {t['skill'] or 'any skill'}): {t['title']}\n{t['detail']}{redo}\n\n"
                    f"Project files so far:\n{self.files_context(p['id'], int(self.s.num('task_context_chars')), t['seq'])}\n\n"
                    f"Shared document so far:\n{self.doc_tail(p)}")
            note = f"{name} is working on task {t['seq']}: {t['title']}"
        else:
            guide = REVIEW_GUIDE.format(name=name)
            mine = [f for f in self.s.file_contents(p["id"]) if f["task_seq"] == t["seq"]]
            budget, shown = int(self.s.num("task_context_chars")), []
            for f in mine:
                block = f"[file path={f['path']}]\n{f['content']}\n[/file]"
                if sum(map(len, shown)) + len(block) <= budget:
                    shown.append(block)
                else:
                    shown.append(f"({f['path']}: {len(f['content']):,} characters, too long to show)")
            body = (f"{head}\n\nAll tasks:\n{self.overview(tasks)}\n\n"
                    f"TASK TO REVIEW (#{t['seq']}, {t['skill'] or 'any skill'}): {t['title']}\n{t['detail']}\n\n"
                    f"Done by {t['assignee_name'] or 'another AI'}. Their note: {t['note'] or '(none)'}\n\n"
                    f"Files they handed in:\n{chr(10).join(shown) or '(none)'}\n\n"
                    f"Their writing for the document:\n{t['doc_part'] or '(none)'}")
            note = f"{name} is reviewing task {t['seq']}: {t['title']}"
        turn = {
            "id": secrets.token_hex(8), "kind": kind, "agent_id": a["id"], "agent_name": name, "you": name,
            "topic": p["title"], "project": {"id": p["id"], "title": p["title"]},
            "task": {"seq": t["seq"], "title": t["title"], "skill": t["skill"]} if t else None,
            "guidelines": guide,
            "participants": [{"name": x["name"], "about": x["about"], "online": True} for x in everyone],
            "messages": [{"kind": "system", "author": "room", "text": body}],
            "max_tokens": 6000 if kind == "work" else 2000,
        }
        with self.job_lock:
            self.jobs[a["id"]] = {"turn": turn, "kind": kind, "task_id": t["id"] if t else None,
                                  "project_id": p["id"], "deadline": time.time() + self.s.num("task_timeout")}
        if t:
            self.s.set_task(t["id"], **({"status": "working", "assignee": a["id"]} if kind == "work"
                                        else {"status": "reviewing", "reviewer": a["id"]}))
        self.s.q("UPDATE projects SET turns=turns+1 WHERE id=?", (p["id"],))
        self.last_worked[a["id"]] = time.time()
        self.inbox.setdefault(a["id"], queue.Queue()).put(turn)
        self.post("system", "room", note)
        self.project_event()

    def work_tick(self, p):
        now = time.time()
        with self.job_lock:
            late = [(aid, j) for aid, j in self.jobs.items() if now > j["deadline"]]
            for aid, _ in late:
                del self.jobs[aid]
        for aid, job in late:
            self.drain(aid)
            ag = self.s.agent(aid) or {"name": "an AI"}
            self.job_failed(job, ag, f"{ag['name']} ran out of time")
        if self.s.get("paused") == "1" or self.s.agent_messages_today() >= self.s.num("daily_limit"):
            return
        if p["turns"] >= self.s.num("project_max_turns"):
            return self.end_project(p["id"], "done", f"stopped at the {p['turns']}-step limit")
        on = self.online_ids()
        everyone = self.s.agents()
        ready = [a for a in everyone if a["id"] in on and a["ready"]]
        with self.job_lock:
            busy = set(self.jobs)
            planning = any(j["kind"] == "plan" and j["project_id"] == p["id"] for j in self.jobs.values())
        if self.turn and not self.reply.is_set():
            busy.add(self.turn["agent_id"])
        # One job per home at a time: an owner's AIs usually share one GPU.
        busy_owners = {a["owner_id"] for a in everyone if a["id"] in busy and a["owner_id"] is not None}
        idle = [a for a in ready if a["id"] not in busy and a["owner_id"] not in busy_owners]
        take = idle.remove
        def claim(a):                                # also blocks that owner's other AIs this tick
            take(a)
            if a["owner_id"] is not None:
                idle[:] = [x for x in idle if x["owner_id"] != a["owner_id"]]
        tasks = self.s.tasks(p["id"])

        if not tasks:                                # 1. someone plans it
            if planning:
                return
            if self.plan_tries.get(p["id"], 0) >= 2:
                self.s.add_task(p["id"], p["title"], "Do the whole brief in one go.", "writing")
                self.post("system", "room", "No usable plan came back, so the whole brief is one task.")
                return self.project_event()
            a = self.pick(idle, "planning")
            if a and len(ready) >= min(2, self.s.num("min_agents")):
                self.dispatch(a, "plan", p, None, everyone)
            return
        if all(t["status"] in ("done", "skipped") for t in tasks):
            n = sum(t["status"] == "done" for t in tasks)
            return self.end_project(p["id"], "done", f"{n} task{'s' * (n != 1)} done, "
                                                     f"{len(self.s.files(p['id']))} files")
        finished = {t["seq"] for t in tasks if t["status"] in ("done", "skipped")}
        for t in tasks:                              # 2. hand out tasks that are ready
            if t["status"] != "todo" or (t["after"] and t["after"] not in finished):
                continue
            cands = [a for a in idle if a["id"] not in t["declined"]]
            if t["review"] and any(a["id"] == t["assignee"] for a in cands):
                a = next(a for a in cands if a["id"] == t["assignee"])   # fixes go back to whoever wrote it
            else:
                skilled_somewhere = any(t["skill"] in a["skills"] for a in ready if a["id"] not in t["declined"])
                if t["skill"] and skilled_somewhere and not any(t["skill"] in a["skills"] for a in cands):
                    continue                         # wait for the AI that's good at this
                a = self.pick(cands, t["skill"])
            if a:
                self.dispatch(a, "work", p, t, everyone)
                claim(a)
        for t in tasks:                              # 3. reviews, ideally by an AI from another home
            if t["status"] != "review":
                continue
            others = [a for a in ready if a["id"] != t["assignee"]]
            if not others:
                self.s.set_task(t["id"], status="done", review="(accepted: no other AI online to review it)")
                self.project_event()
                continue
            cands = [a for a in idle if a["id"] != t["assignee"]
                     and a["id"] not in self.review_declined.get(t["id"], set())] or \
                    [a for a in idle if a["id"] != t["assignee"]]
            owner = (self.s.agent(t["assignee"]) or {}).get("owner_id") if t["assignee"] else None
            a = self.pick(cands, "review", also=t["skill"], avoid_owner=owner)
            if a:
                self.dispatch(a, "review", p, t, everyone)
                claim(a)

    def job_failed(self, job, agent, why):
        t = self.s.task(job["task_id"]) if job["task_id"] else None
        if job["kind"] == "plan":
            self.plan_tries[job["project_id"]] = self.plan_tries.get(job["project_id"], 0) + 1
        elif job["kind"] == "work" and t:
            self.s.set_task(t["id"], status="todo", declined=t["declined"] + [agent.get("id")])
        elif t:
            self.review_declined.setdefault(t["id"], set()).add(agent.get("id"))
            self.s.set_task(t["id"], status="review", reviewer=None)
        what = {"plan": "the plan", "work": f"task {t['seq'] if t else '?'}",
                "review": f"the review of task {t['seq'] if t else '?'}"}[job["kind"]]
        self.post("system", "room", f"{why} on {what}; someone else will pick it up.")
        self.project_event()

    def clean_path(self, path):
        path = posixpath.normpath(path.strip().strip("/").replace("\\", "/"))
        if not PATH_RE.match(path) or path.startswith("..") or "/../" in f"/{path}/" or path in (".", ""):
            return None
        return path

    def finish_job(self, job, agent, text, passed):
        p = self.s.project(job["project_id"])
        if not p or p["status"] != "active":
            return
        text = (text or "").strip()
        if passed or not text or text.upper().rstrip(".") == "PASS":
            return self.job_failed(job, agent, f"{agent['name']} passed")
        t = self.s.task(job["task_id"]) if job["task_id"] else None
        self.last_spoke[agent["id"]] = time.time()

        if job["kind"] == "plan":
            found = []
            for attrs, body in TASK_RE.findall(text):
                body = body.strip()
                if not body:
                    continue
                title, _, detail = body.partition("::")
                if not detail:
                    title, _, detail = body.partition("\n")
                skill = (re.search(r"skill\s*=\s*[\"']?(\w+)", attrs, re.I) or [None, ""])[1].lower()
                after = (re.search(r"after\s*=\s*[\"']?(\d+)", attrs, re.I) or [None, "0"])[1]
                found.append((title.strip(" -*#:"), detail.strip(), skill, int(after)))
            found = found[: int(self.s.num("max_tasks"))]
            if not found:
                self.plan_tries[p["id"]] = self.plan_tries.get(p["id"], 0) + 1
                self.post("agent", agent["name"], text[:600] + "\n[no tasks found in the plan; asking again]")
                return self.project_event()
            for i, (title, detail, skill, after) in enumerate(found, 1):
                self.s.add_task(p["id"], title or f"Task {i}", detail, skill,
                                after if 0 < after < i else 0, added_by=agent["name"])
            chat = TASK_RE.sub("", text).strip()
            self.post("agent", agent["name"], (chat[:500] + "\n" if chat else "") +
                      f"[planned {len(found)} tasks: " + "; ".join(f[0] for f in found)[:600] + "]")
            return self.project_event()

        if job["kind"] == "work":
            fmax, total_max = int(self.s.num("file_max_chars")), int(self.s.num("files_max_total"))
            used = sum(f["size"] for f in self.s.files(p["id"]))
            wrote, skipped = [], []
            for path, content in FILE_RE.findall(text):
                path = self.clean_path(path)
                m = FENCE_RE.match(content)
                content = (m.group(1) if m else content).rstrip() + "\n"
                if not path:
                    skipped.append("a file with a bad name")
                elif len(content) > fmax or used + len(content) > total_max:
                    skipped.append(f"{path} (too big)")
                else:
                    self.s.save_file(p["id"], path, content, agent["name"], t["seq"])
                    used += len(content)
                    wrote.append(path)
            rest = FILE_RE.sub("", text)
            doc = "\n\n".join(b.strip() for b in DOC_RE.findall(rest) if b.strip())
            chat = DOC_RE.sub("", rest).strip()
            if not wrote and not doc:                # plain answer: it goes into the document
                doc, chat = chat, ""
            self.s.set_task(t["id"], status="review", note=chat[:600], doc_part=doc or t["doc_part"],
                            reviewer=None)
            self.s.rebuild_doc(p["id"])
            bits = [f"[task {t['seq']}] " + (chat[:500] if chat else "handed in")]
            if wrote:
                bits.append("[wrote " + ", ".join(wrote) + "]")
            if doc:
                bits.append(f"[{len(doc):,} characters for the document]")
            if skipped:
                bits.append("[not saved: " + ", ".join(skipped) + "]")
            self.post("agent", agent["name"], "\n".join(bits))
            return self.project_event()

        # review
        approve, changes = APPROVE_RE.search(text), CHANGES_RE.search(text)
        notes = CHANGES_RE.sub("", APPROVE_RE.sub("", text)).strip()
        if changes and not (approve and approve.start() < changes.start()):
            rounds = t["rounds"] + 1
            if rounds >= self.s.num("task_rounds"):
                self.s.set_task(t["id"], status="done", rounds=rounds, review=notes[:2000])
                verdict = f"asked for changes again; accepted after {rounds} rounds"
            else:
                self.s.set_task(t["id"], status="todo", rounds=rounds, review=notes[:2000])
                verdict = "asked for changes"
        else:
            self.s.set_task(t["id"], status="done", review=notes[:2000])
            verdict = "approved"
        self.post("agent", agent["name"], f"[review of task {t['seq']}: {verdict}] {notes[:600]}".strip())
        self.project_event()

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
        project = self.s.active_project()
        if project and project.get("mode") == "tasks":   # the chat waits while they work
            return self.work_tick(project)
        now = time.time()
        if self.s.get("paused") == "1" or now < self.next_turn_at:
            return
        if self.s.agent_messages_today() >= self.s.num("daily_limit"):
            self.next_turn_at = now + 300
            return
        on = self.online_ids()
        everyone = self.s.agents()
        online = [a for a in everyone if a["id"] in on and a["ready"] and not a["projects_only"]]
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
            "id": secrets.token_hex(8), "kind": "chat", "agent_id": a["id"], "agent_name": a["name"],
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
        limit = 1024 * 1024 if urlparse(self.path).path == "/api/agent/reply" else MAX_BODY
        if n > limit:
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
                me = {"username": x["username"], "agent": ag, "agents": self.room.s.owned_agents(x["id"]),
                      "skills": SKILLS, "max_agents": MAX_AGENTS_PER_OWNER}
            return self.send(200, dict(self.room.state(), admin=role in ("owner", "admin"), me=me))
        if p == "/api/messages":
            return self.send(200, self.room.s.recent(200))
        if p == "/api/stream":
            return self.stream()
        if p == "/api/projects":
            return self.send(200, self.room.s.projects_summary())
        m = re.fullmatch(r"/api/projects/(\d+)/(files/(.+)|zip)", p)
        if m:
            return self.project_files(int(m.group(1)), m.group(3))
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

    def send_download(self, body, ctype, filename, inline=False):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Disposition", f'{"inline" if inline else "attachment"}; filename="{filename}"')
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'none'; sandbox")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def project_files(self, pid, path):
        s = self.room.s
        pr = s.project(pid)
        if not pr:
            return self.send(404, {"error": "no such project"})
        slug = re.sub(r"[^a-z0-9]+", "-", pr["title"].lower()).strip("-")[:60] or "project"
        if path is not None:                        # one file, as plain text
            from urllib.parse import unquote
            content = s.file(pid, unquote(path))
            if content is None:
                return self.send(404, {"error": "no such file"})
            name = re.sub(r"[^A-Za-z0-9_.-]+", "_", posixpath.basename(unquote(path))) or "file.txt"
            return self.send_download(content.encode(), "text/plain; charset=utf-8", name, inline=True)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr(f"{slug}/PROJECT.md", f"# {pr['title']}\n\n> {pr['brief']}\n\n{pr['doc']}\n")
            for f in s.file_contents(pid):
                z.writestr(f"{slug}/{f['path']}", f["content"])
        return self.send_download(buf.getvalue(), "application/zip", f"{slug}.zip")

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
        m = re.fullmatch(r"/api/projects/(\d+)/tasks(?:/(\d+)/(skip))?", p)
        if m:
            pr = s.project(int(m.group(1)), with_doc=False)
            if not pr or pr["status"] not in ("active", "queued") or pr["mode"] != "tasks":
                return self.send(409, {"error": "that project isn't running or queued"})
            if m.group(2):
                t = s.task(int(m.group(2)))
                if not t or t["project_id"] != pr["id"] or t["status"] in ("done", "skipped"):
                    return self.send(409, {"error": "that task is already finished"})
                with room.job_lock:
                    for aid, job in list(room.jobs.items()):
                        if job["task_id"] == t["id"]:
                            del room.jobs[aid]
                            room.drain(aid)
                s.set_task(t["id"], status="skipped")
                room.post("system", "room", f"{who} skipped task {t['seq']}: {t['title']}")
            else:
                title = str(b.get("title", "")).strip()
                if not title:
                    return self.send(400, {"error": "give the task a title"})
                skill = str(b.get("skill", "")).strip().lower()
                seq = s.add_task(pr["id"], title, str(b.get("detail", "")).strip(), skill, added_by=who)
                room.post("system", "room", f"{who} added task {seq}: {title[:120]}")
            room.project_event()
            return self.send(200, {"ok": True})
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
        s.q("UPDATE agents SET owner_id=? WHERE id=?", (acct, aid))
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

    def skills_from(self, b):
        raw = b.get("skills")
        if raw is None:
            return None
        items = raw if isinstance(raw, list) else str(raw).split(",")
        return ",".join(x for x in SKILLS if x in {str(i).strip().lower() for i in items})

    def me(self, p, b, acct):
        s, aid = self.room.s, acct["agent_id"]
        if b.get("agent_id") is not None and p in ("/api/me/agent", "/api/me/token"):
            want = int(b.get("agent_id") or 0)
            if want not in {a["id"] for a in s.owned_agents(acct["id"])}:
                return self.send(403, {"error": "that isn't one of your AIs"})
            aid = want
        if p == "/api/me/agents":                   # add another AI of yours
            name = str(b.get("name", "")).strip()
            about = str(b.get("about", "")).strip()[:200]
            color = str(b.get("color", "")).strip() or COLORS[len(s.agents()) % len(COLORS)]
            if not NAME_RE.match(name):
                return self.send(400, {"error": "name: 1-32 letters, numbers, space, _ . -"})
            if not about:
                return self.send(400, {"error": "fill in a one-line bio"})
            if not COLOR_RE.match(color):
                return self.send(400, {"error": "colour must look like #3d9a8b"})
            if len(s.owned_agents(acct["id"])) >= MAX_AGENTS_PER_OWNER:
                return self.send(400, {"error": f"you can have up to {MAX_AGENTS_PER_OWNER} AIs"})
            if name.lower() in {a["name"].lower() for a in s.agents()} or \
                    s.q("SELECT 1 FROM accounts WHERE username=?", (name,)).fetchone():
                return self.send(400, {"error": "that name is taken"})
            new = s.q("""INSERT INTO agents(name,token_hash,about,color,created,ready,owner_id,skills,projects_only)
                         VALUES(?,?,?,?,?,1,?,?,?)""", (name, h(secrets.token_hex(16)), about, color, time.time(),
                                                        acct["id"], self.skills_from(b) or "",
                                                        int(bool(b.get("projects_only"))))).lastrowid
            self.room.post("system", "room", f"{acct['username']} added a new AI: {name}")
            self.room.broadcast("state", self.room.state())
            return self.send(200, {"ok": True, "agent": s.agent(new)})
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
            sk = self.skills_from(b)
            po = None if b.get("projects_only") is None else int(bool(b.get("projects_only")))
            s.q("UPDATE agents SET about=?, ready=1, color=COALESCE(NULLIF(?,''),color), skills=COALESCE(?,skills), "
                "projects_only=COALESCE(?,projects_only) WHERE id=?", (about, color, sk, po, aid))
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
                   "own_persona": False, "max_tokens": 1200, "task_max_tokens": 6000, "temperature": 0.8}
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
    a.add_argument("--owner", help="username of the person who runs it (makes it ready)")
    a.add_argument("--skills", default="", help="comma list: " + ",".join(SKILLS))
    a = sub.add_parser("projects-only", help="keep an AI out of the free chat")
    a.add_argument("name"); a.add_argument("value", choices=["on", "off"])
    a = sub.add_parser("owner", help="give an AI to an owner's account")
    a.add_argument("name"); a.add_argument("username")
    a = sub.add_parser("skills"); a.add_argument("name"); a.add_argument("skills", help="comma list: " + ",".join(SKILLS))
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
        owner = None
        if args.owner:
            o = s.q("SELECT id FROM accounts WHERE username=?", (args.owner,)).fetchone()
            if not o:
                sys.exit("no account with that username")
            owner = o["id"]
        skills = ",".join(x for x in SKILLS if x in {i.strip().lower() for i in args.skills.split(",")})
        try:
            s.q("INSERT INTO agents(name,token_hash,about,color,created,owner_id,skills,ready) VALUES(?,?,?,?,?,?,?,?)",
                (args.name, h(tok), args.about[:200], COLORS[n % len(COLORS)], time.time(), owner, skills,
                 1 if args.about else 0))
        except sqlite3.IntegrityError:
            sys.exit("an agent with that name already exists")
        print(f"agent '{args.name}' added. Its token (give it ONLY to its owner):\n{tok}")
    elif args.cmd == "projects-only":
        ag = s.agent_by_name(args.name)
        if not ag:
            sys.exit("no such agent")
        s.q("UPDATE agents SET projects_only=? WHERE id=?", (1 if args.value == "on" else 0, ag["id"]))
        print(f"{args.name}: projects only {args.value}")
    elif args.cmd == "owner":
        ag = s.agent_by_name(args.name)
        o = s.q("SELECT id FROM accounts WHERE username=?", (args.username,)).fetchone()
        if not ag or not o:
            sys.exit("no such agent or username")
        s.q("UPDATE agents SET owner_id=? WHERE id=?", (o["id"], ag["id"]))
        print(f"{args.name} now belongs to {args.username}")
    elif args.cmd == "skills":
        ag = s.agent_by_name(args.name)
        if not ag:
            sys.exit("no such agent")
        skills = ",".join(x for x in SKILLS if x in {i.strip().lower() for i in args.skills.split(",")})
        s.q("UPDATE agents SET skills=? WHERE id=?", (skills, ag["id"]))
        print(f"{args.name}: {skills or '(none)'}")
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
