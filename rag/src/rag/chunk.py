"""Chunking.

Dependency-light, word-based. We pack whole paragraphs up to a soft word
budget (``chunk_tokens`` is read as a word count — close enough for retrieval
without pulling in a tokenizer), then slide with ``chunk_overlap`` words of
carry-over so a fact straddling a boundary still lands whole in one chunk. A
single paragraph larger than the budget is split on word boundaries.

Each chunk carries its parent document's metadata plus a stable ``chunk_id``
(``doc_id#NN``) so re-ingesting a document overwrites its own chunks cleanly.
"""
from __future__ import annotations

import re
from typing import Iterator, List

_WS = re.compile(r"[ \t]+")
_PARA = re.compile(r"\n\s*\n")


def clean_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    lines = [_WS.sub(" ", ln).strip() for ln in text.split("\n")]
    return "\n".join(lines).strip()


def _paragraphs(text: str) -> List[str]:
    return [p.strip() for p in _PARA.split(text) if p.strip()]


def _split_long(words: List[str], budget: int, overlap: int) -> Iterator[List[str]]:
    i = 0
    step = max(1, budget - overlap)
    while i < len(words):
        yield words[i : i + budget]
        i += step


def chunk_text(text: str, budget: int = 350, overlap: int = 60) -> List[str]:
    text = clean_text(text)
    if not text:
        return []
    chunks: List[str] = []
    cur: List[str] = []
    cur_n = 0
    for para in _paragraphs(text):
        words = para.split()
        if len(words) > budget:
            if cur:
                chunks.append(" ".join(cur))
                cur, cur_n = [], 0
            for piece in _split_long(words, budget, overlap):
                chunks.append(" ".join(piece))
            continue
        if cur_n + len(words) > budget and cur:
            chunks.append(" ".join(cur))
            # carry the tail of the previous chunk for overlap
            carry = " ".join(cur).split()[-overlap:] if overlap else []
            cur = list(carry)
            cur_n = len(carry)
        cur.extend(words)
        cur_n += len(words)
    if cur:
        chunks.append(" ".join(cur))
    return [c for c in chunks if c.strip()]


def chunk_document(doc, budget: int = 350, overlap: int = 60) -> List[dict]:
    """Turn a Document into chunk dicts ready for the store."""
    pieces = chunk_text(doc.text, budget, overlap)
    out = []
    for i, piece in enumerate(pieces):
        out.append(
            {
                "chunk_id": f"{doc.doc_id}#{i:03d}",
                "text": piece,
                "domain": doc.domain,
                "url": doc.url,
                "title": doc.title,
                "extra": doc.extra,
            }
        )
    return out
