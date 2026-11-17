"""Source plugin contract.

A source yields :class:`Document` objects. The ingest pipeline chunks, embeds
and upserts them, and uses ``content_hash`` to skip documents that have not
changed since the last run (incremental re-ingest).

To add a source: write a module in ``rag/sources/`` exposing a ``Source``
subclass and register it in ``rag/sources/__init__.py`` (see the README).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Iterator, Optional

from ..config import Config


@dataclass
class Document:
    # doc_id must be stable across runs for incrementality (e.g. a URL or path)
    doc_id: str
    text: str
    source: str
    domain: Optional[str] = None      # coarse topic: web | network | malware | ...
    url: Optional[str] = None
    title: Optional[str] = None
    extra: dict = field(default_factory=dict)

    @property
    def content_hash(self) -> str:
        h = hashlib.sha256()
        h.update(self.text.encode("utf-8", "replace"))
        h.update(b"\x00")
        h.update((self.title or "").encode("utf-8", "replace"))
        return h.hexdigest()


class Source:
    """Base source. Subclasses set ``name``/``default_domain`` and implement
    ``documents()``."""

    name: str = "base"
    default_domain: Optional[str] = None

    def __init__(self, cfg: Config, **opts):
        self.cfg = cfg
        self.opts = opts

    def documents(self) -> Iterator[Document]:  # pragma: no cover
        raise NotImplementedError

    # helpers for subclasses
    def _doc(self, doc_id: str, text: str, **kw) -> Document:
        kw.setdefault("domain", self.default_domain)
        return Document(doc_id=doc_id, text=text, source=self.name, **kw)
