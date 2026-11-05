"""Ingestion orchestration.

For each source: iterate its documents, skip any whose content hash matches the
store (incremental), chunk the rest, embed the chunks in batches, and upsert.
With ``prune=True`` a source's documents that disappeared since the last run are
deleted from the store. Re-runnable: running twice with no source changes does
no embedding work.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, List, Optional

from . import sources
from .chunk import chunk_document
from .config import Config
from .embed import Embedder, get_embedder
from .store import Store


@dataclass
class IngestStats:
    source: str
    docs_seen: int = 0
    docs_embedded: int = 0
    docs_skipped: int = 0
    docs_pruned: int = 0
    chunks: int = 0
    notes: dict = field(default_factory=dict)


def ingest_source(
    name: str,
    cfg: Config,
    store: Store,
    embedder: Optional[Embedder] = None,
    prune: bool = False,
    force: bool = False,
    log: Callable[[str], None] = lambda m: None,
    **opts,
) -> IngestStats:
    embedder = embedder or get_embedder(cfg)
    src = sources.get(name, cfg, **opts)
    st = IngestStats(source=name)
    seen_ids = set()

    for doc in src.documents():
        st.docs_seen += 1
        seen_ids.add(doc.doc_id)
        if not force and store.doc_unchanged(doc.doc_id, doc.content_hash):
            st.docs_skipped += 1
            continue
        chunks = chunk_document(doc, cfg.chunk_tokens, cfg.chunk_overlap)
        if not chunks:
            # nothing to embed, but record the doc so it isn't re-tried forever
            store.add_doc(doc.doc_id, name, doc.url, doc.content_hash, [], [])
            continue
        embeddings = embedder.embed_documents([c["text"] for c in chunks])
        store.add_doc(doc.doc_id, name, doc.url, doc.content_hash, chunks, embeddings)
        st.docs_embedded += 1
        st.chunks += len(chunks)
        log(f"  [{name}] {doc.doc_id} -> {len(chunks)} chunks")

    if prune:
        stale = store.doc_ids_for_source(name) - seen_ids
        for doc_id in stale:
            store.delete_doc(doc_id)
            st.docs_pruned += 1
        if stale:
            store.conn.commit()

    for attr in ("kept", "skipped"):
        if hasattr(src, attr):
            st.notes[attr] = getattr(src, attr)
    return st


def ingest(
    names: List[str],
    cfg: Config,
    prune: bool = False,
    force: bool = False,
    log: Callable[[str], None] = lambda m: None,
    source_opts: Optional[dict] = None,
) -> List[IngestStats]:
    source_opts = source_opts or {}
    embedder = get_embedder(cfg)
    results = []
    with Store(cfg) as store:
        for name in names:
            log(f"[{name}] ingesting (provider={cfg.embed.provider}, model={cfg.embed.model})")
            stats = ingest_source(
                name, cfg, store, embedder, prune=prune, force=force,
                log=log, **source_opts.get(name, {}),
            )
            results.append(stats)
            log(
                f"[{name}] done: {stats.docs_embedded} embedded, "
                f"{stats.docs_skipped} unchanged, {stats.chunks} chunks"
                + (f", {stats.docs_pruned} pruned" if prune else "")
            )
    return results
