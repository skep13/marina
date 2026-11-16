"""AIWS's state: client tokens, the assistant's action log, jobs and
settings that change at runtime. One SQLite file, WAL mode."""
import hashlib
import json
import secrets
import sqlite3
import threading
import time

from aiws import config

_lock = threading.Lock()
_db = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS tokens (
  hash TEXT PRIMARY KEY, name TEXT UNIQUE, scopes TEXT, created REAL, last_used REAL);
CREATE TABLE IF NOT EXISTS actions (
  id INTEGER PRIMARY KEY, ts REAL, session TEXT, tool TEXT, args TEXT,
  status TEXT, result TEXT, finished REAL);
CREATE TABLE IF NOT EXISTS jobs (
  id INTEGER PRIMARY KEY, ts REAL, name TEXT, worker TEXT, command TEXT,
  status TEXT, exit_code INTEGER, started REAL, finished REAL, log TEXT,
  spec TEXT);
CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT);
"""


def db():
    global _db
    if _db is None:
        config.STATE.mkdir(parents=True, exist_ok=True)
        _db = sqlite3.connect(config.STATE / "aiws.db", check_same_thread=False)
        _db.row_factory = sqlite3.Row
        _db.execute("PRAGMA journal_mode=WAL")
        _db.executescript(SCHEMA)
    return _db


def q(sql, *args):
    with _lock:
        cur = db().execute(sql, args)
        db().commit()
        return cur


def rows(sql, *args):
    with _lock:
        return [dict(r) for r in db().execute(sql, args).fetchall()]


# ---- settings ----
def get(k, default=None):
    r = rows("SELECT v FROM kv WHERE k=?", k)
    return json.loads(r[0]["v"]) if r else default


def put(k, v):
    q("INSERT INTO kv(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
      k, json.dumps(v))


# ---- tokens ----
def _hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def new_token(name, scopes=("chat",)):
    token = "aiws_" + secrets.token_urlsafe(32)
    q("INSERT OR REPLACE INTO tokens(hash,name,scopes,created) VALUES(?,?,?,?)",
      _hash(token), name, ",".join(scopes), time.time())
    return token


def check_token(token):
    """The token's row, or None."""
    if not token:
        return None
    r = rows("SELECT name, scopes FROM tokens WHERE hash=?", _hash(token))
    if not r:
        return None
    q("UPDATE tokens SET last_used=? WHERE hash=?", time.time(), _hash(token))
    r[0]["scopes"] = set(r[0]["scopes"].split(","))
    return r[0]


def list_tokens():
    return rows("SELECT name, scopes, created, last_used FROM tokens ORDER BY name")


def revoke(name):
    return q("DELETE FROM tokens WHERE name=?", name).rowcount


# ---- assistant action log ----
def action_start(session, tool, args):
    return q("INSERT INTO actions(ts,session,tool,args,status) VALUES(?,?,?,?,?)",
             time.time(), session, tool, json.dumps(args)[:4000], "running").lastrowid


def action_end(aid, status, result):
    q("UPDATE actions SET status=?, result=?, finished=? WHERE id=?",
      status, str(result)[:4000], time.time(), aid)


def actions(limit=100, after=0):
    return rows("SELECT * FROM actions WHERE id>? ORDER BY id DESC LIMIT ?", after, limit)
