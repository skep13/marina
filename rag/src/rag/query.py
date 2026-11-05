"""Query: embed a question, KNN the store, return a stable result dict.

The JSON shape returned by :func:`query` is the contract a Songbird/Marina
agent tool will depend on. Keep these keys stable; add fields, don't rename or
remove. See the README ("Query JSON contract").
"""
from __future__ import annotations

from typing import Optional

from .config import Config
from .embed import get_embedder
from .store import Store


def query(
    question: str,
    cfg: Config,
    k: int = 6,
    domain: Optional[str] = None,
    source: Optional[str] = None,
    max_chars: Optional[int] = None,
) -> dict:
    embedder = get_embedder(cfg)
    qvec = embedder.embed_query(question)
    with Store(cfg) as store:
        hits = store.search(qvec, k=k, domain=domain, source=source)
    results = []
    for i, h in enumerate(hits):
        text = h["text"]
        if max_chars and len(text) > max_chars:
            text = text[:max_chars].rstrip() + "…"
        results.append(
            {
                "rank": i + 1,
                "score": round(h["score"], 4),
                "text": text,
                "source": h["source"],
                "url": h["url"],
                "domain": h["domain"],
                "title": h["title"],
                "chunk_id": h["chunk_id"],
            }
        )
    return {
        "query": question,
        "k": k,
        "domain": domain,
        "source": source,
        "model": cfg.embed.model,
        "provider": cfg.embed.provider,
        "count": len(results),
        "results": results,
    }
