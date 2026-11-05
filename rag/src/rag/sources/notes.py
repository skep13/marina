"""The user's own notes.

Reads ``.md``/``.markdown``/``.txt`` files from a directory (default
``rag/sources_data/notes``, override with ``path=``). Each file is one
document; ``doc_id`` is its path relative to the notes root so edits re-ingest
in place. A leading ``domain:`` front-matter line or a top-level directory name
sets the chunk domain.

This source needs no network and is the easiest way to smoke-test the whole
pipeline on a Mac.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Iterator

from .base import Document, Source

_FRONT_DOMAIN = re.compile(r"^\s*domain:\s*(\S+)\s*$", re.IGNORECASE | re.MULTILINE)


class NotesSource(Source):
    name = "notes"
    default_domain = None

    def _root(self) -> Path:
        p = self.opts.get("path")
        return Path(p) if p else self.cfg.sources_dir / "notes"

    def documents(self) -> Iterator[Document]:
        root = self._root()
        if not root.exists():
            return
        for path in sorted(root.rglob("*")):
            if path.suffix.lower() not in (".md", ".markdown", ".txt"):
                continue
            text = path.read_text("utf-8", "replace")
            rel = path.relative_to(root)
            domain = None
            m = _FRONT_DOMAIN.search(text[:500])
            if m:
                domain = m.group(1).lower()
                text = text[: m.start()] + text[m.end():]  # drop the front-matter line
            elif len(rel.parts) > 1:
                domain = rel.parts[0].lower()
            title = path.stem.replace("_", " ").replace("-", " ")
            yield self._doc(
                doc_id=f"notes:{rel.as_posix()}",
                text=text,
                domain=domain,
                url=f"file://{path}",
                title=title,
            )
