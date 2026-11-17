"""Vector store on sqlite-vec.

Why sqlite-vec (over Chroma / LanceDB): it is a single C extension loaded into
Python's stdlib ``sqlite3`` — no server, no daemon, one ``rag.db`` file you can
copy. That matters because lab3 is slated to become a standalone portable
appliance: the store has to run self-contained next to the models with no extra
process. Chroma pulls a large dependency tree and historically a server;
LanceDB is great but heavier and columnar-file-based. For a few hundred
thousand chunks queried locally, sqlite-vec's brute-force KNN is plenty fast and
the operational story is "it's a file".

Layout:
- ``chunks``      regular table: the text + all metadata, keyed by rowid.
- ``vec_chunks``  vec0 virtual table: the embedding + ``domain``/``source`` as
                  filterable metadata columns, same rowid as ``chunks``.
- ``docs``        one row per ingested source document, with a content hash, so
                  re-ingesting skips unchanged documents (incremental).
- ``meta``        store-wide settings (embedding model + dim) so a query can
                  refuse to run against vectors built with a different model.
"""
from __future__ import annotations

import json
import sqlite3
import struct
import time
from pathlib import Path
from typing import Iterable, List, Optional

from .config import Config


class StoreError(RuntimeError):
    pass


def _serialize(vec: List[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def _load_vec_extension(conn: sqlite3.Connection) -> None:
    try:
        conn.enable_load_extension(True)
    except AttributeError as e:
        raise StoreError(
            "this Python's sqlite3 was built without extension loading; use a "
            "Python that supports it (Homebrew/pyenv, or the project .venv)"
        ) from e
    try:
        import sqlite_vec
    except ImportError as e:
        raise StoreError("sqlite-vec not installed; `pip install -r rag/requirements.txt`") from e
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)


class Store:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.dim = cfg.embed.dim
        self.path = cfg.db_path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        _load_vec_extension(self.conn)
        self._init_schema()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()

    def _init_schema(self) -> None:
        c = self.conn
        c.execute("PRAGMA journal_mode=WAL")
        c.execute(
            """CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS docs (
                   doc_id TEXT PRIMARY KEY,
                   source TEXT NOT NULL,
                   url TEXT,
                   content_hash TEXT NOT NULL,
                   n_chunks INTEGER NOT NULL DEFAULT 0,
                   ingested_at REAL NOT NULL
               )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS chunks (
                   rowid INTEGER PRIMARY KEY,
                   chunk_id TEXT UNIQUE NOT NULL,
                   doc_id TEXT NOT NULL,
                   source TEXT NOT NULL,
                   domain TEXT,
                   url TEXT,
                   title TEXT,
                   text TEXT NOT NULL,
                   extra TEXT
               )"""
        )
        c.execute("CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(doc_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_chunks_source ON chunks(source)")
        c.execute(
            f"""CREATE VIRTUAL TABLE IF NOT EXISTS vec_chunks USING vec0(
                    domain TEXT,
                    source TEXT,
                    embedding FLOAT[{self.dim}]
                )"""
        )
        self._check_meta()
        c.commit()

    def _check_meta(self) -> None:
        want = {"model": self.cfg.embed.model, "dim": str(self.dim)}
        rows = {r["key"]: r["value"] for r in self.conn.execute("SELECT key, value FROM meta")}
        if not rows:
            self.conn.executemany(
                "INSERT INTO meta(key, value) VALUES(?, ?)", list(want.items())
            )
            return
        if rows.get("dim") != want["dim"] or rows.get("model") != want["model"]:
            raise StoreError(
                f"store {self.path} was built with model={rows.get('model')} "
                f"dim={rows.get('dim')}, but config is model={want['model']} "
                f"dim={want['dim']}. Use a matching model or re-ingest into a "
                f"fresh --data-dir."
            )

    # ---- incremental bookkeeping ----
    def doc_unchanged(self, doc_id: str, content_hash: str) -> bool:
        row = self.conn.execute(
            "SELECT content_hash FROM docs WHERE doc_id = ?", (doc_id,)
        ).fetchone()
        return bool(row and row["content_hash"] == content_hash)

    def delete_doc(self, doc_id: str) -> None:
        rows = self.conn.execute(
            "SELECT rowid FROM chunks WHERE doc_id = ?", (doc_id,)
        ).fetchall()
        ids = [r["rowid"] for r in rows]
        for rid in ids:
            self.conn.execute("DELETE FROM vec_chunks WHERE rowid = ?", (rid,))
        self.conn.execute("DELETE FROM chunks WHERE doc_id = ?", (doc_id,))
        self.conn.execute("DELETE FROM docs WHERE doc_id = ?", (doc_id,))

    def add_doc(
        self,
        doc_id: str,
        source: str,
        url: Optional[str],
        content_hash: str,
        chunks: List[dict],
        embeddings: List[List[float]],
    ) -> None:
        """Replace a document's chunks atomically (delete old, insert new)."""
        if len(chunks) != len(embeddings):
            raise StoreError("chunk/embedding count mismatch")
        self.delete_doc(doc_id)
        for ch, emb in zip(chunks, embeddings):
            cur = self.conn.execute(
                """INSERT INTO chunks(chunk_id, doc_id, source, domain, url, title, text, extra)
                   VALUES(?,?,?,?,?,?,?,?)""",
                (
                    ch["chunk_id"],
                    doc_id,
                    source,
                    ch.get("domain"),
                    ch.get("url") or url,
                    ch.get("title"),
                    ch["text"],
                    json.dumps(ch.get("extra") or {}),
                ),
            )
            rowid = cur.lastrowid
            self.conn.execute(
                "INSERT INTO vec_chunks(rowid, domain, source, embedding) VALUES(?,?,?,?)",
                (rowid, ch.get("domain") or "", source, _serialize(emb)),
            )
        self.conn.execute(
            """INSERT INTO docs(doc_id, source, url, content_hash, n_chunks, ingested_at)
               VALUES(?,?,?,?,?,?)
               ON CONFLICT(doc_id) DO UPDATE SET
                 source=excluded.source, url=excluded.url,
                 content_hash=excluded.content_hash, n_chunks=excluded.n_chunks,
                 ingested_at=excluded.ingested_at""",
            (doc_id, source, url, content_hash, len(chunks), time.time()),
        )
        self.conn.commit()

    def doc_ids_for_source(self, source: str) -> set:
        return {
            r["doc_id"]
            for r in self.conn.execute("SELECT doc_id FROM docs WHERE source = ?", (source,))
        }

    # ---- query ----
    def search(
        self,
        query_vec: List[float],
        k: int = 6,
        domain: Optional[str] = None,
        source: Optional[str] = None,
    ) -> List[dict]:
        where = ["embedding MATCH ?", "k = ?"]
        params: list = [_serialize(query_vec), int(k)]
        if domain:
            where.append("domain = ?")
            params.append(domain)
        if source:
            where.append("source = ?")
            params.append(source)
        sql = (
            "SELECT rowid, distance FROM vec_chunks WHERE "
            + " AND ".join(where)
            + " ORDER BY distance"
        )
        rows = self.conn.execute(sql, params).fetchall()
        out = []
        for r in rows:
            meta = self.conn.execute(
                "SELECT chunk_id, doc_id, source, domain, url, title, text, extra "
                "FROM chunks WHERE rowid = ?",
                (r["rowid"],),
            ).fetchone()
            if not meta:
                continue
            out.append(
                {
                    "chunk_id": meta["chunk_id"],
                    "doc_id": meta["doc_id"],
                    "source": meta["source"],
                    "domain": meta["domain"],
                    "url": meta["url"],
                    "title": meta["title"],
                    "text": meta["text"],
                    "distance": float(r["distance"]),
                    # vectors are L2-normalized, so L2 distance d maps to cosine
                    # similarity 1 - d^2/2. Clamp for float noise.
                    "score": max(-1.0, min(1.0, 1.0 - (float(r["distance"]) ** 2) / 2.0)),
                    "extra": json.loads(meta["extra"] or "{}"),
                }
            )
        return out

    def stats(self) -> dict:
        c = self.conn
        n_docs = c.execute("SELECT COUNT(*) n FROM docs").fetchone()["n"]
        n_chunks = c.execute("SELECT COUNT(*) n FROM chunks").fetchone()["n"]
        by_source = {
            r["source"]: r["n"]
            for r in c.execute("SELECT source, COUNT(*) n FROM chunks GROUP BY source")
        }
        by_domain = {
            (r["domain"] or "(none)"): r["n"]
            for r in c.execute("SELECT domain, COUNT(*) n FROM chunks GROUP BY domain")
        }
        meta = {r["key"]: r["value"] for r in c.execute("SELECT key, value FROM meta")}
        return {
            "db": str(self.path),
            "model": meta.get("model"),
            "dim": meta.get("dim"),
            "docs": n_docs,
            "chunks": n_chunks,
            "by_source": by_source,
            "by_domain": by_domain,
        }
