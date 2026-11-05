"""Cleaned subset of the Hugging Face dataset ``Vyber07/cyber-security``.

The dataset is GATED: you must accept its terms on Hugging Face and download it
yourself (see the README). Point this source at the downloaded directory
(default ``sources_data/hf_vyber``). It contains 507 files of which ~394 are
valid JSON; this loader parses every ``*.json`` and silently drops the ~113
that fail to parse, logging the count via ``skipped``/``kept`` on the instance.

Each file's records are flattened to text. Common instruction-tuning shapes are
recognized (instruction/input/output, question/answer, prompt/response,
text/content); anything else is serialized generically. domain = "misc".

License note: the upstream card tags apache-2.0 but the content is assembled
from third-party sources (HackTheBox, PortSwigger, ...). Treat provenance as
uncertain and keep this index private.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator, List

from .base import Document, Source

_PAIRS = [
    ("instruction", "output"),
    ("instruction", "response"),
    ("question", "answer"),
    ("prompt", "response"),
    ("prompt", "completion"),
    ("input", "output"),
]


class HfVyberSource(Source):
    name = "hf_vyber"
    default_domain = "misc"

    def __init__(self, cfg, **opts):
        super().__init__(cfg, **opts)
        self.kept = 0
        self.skipped = 0

    def _root(self) -> Path:
        p = self.opts.get("path")
        return Path(p) if p else self.cfg.sources_dir / "hf_vyber"

    def documents(self) -> Iterator[Document]:
        root = self._root()
        if not root.exists():
            return
        for path in sorted(root.rglob("*.json")):
            try:
                data = json.loads(path.read_text("utf-8", "replace"))
            except (json.JSONDecodeError, ValueError):
                self.skipped += 1
                continue
            self.kept += 1
            rel = path.relative_to(root).as_posix()
            records = data if isinstance(data, list) else [data]
            for i, rec in enumerate(records):
                text = self._record_text(rec)
                if not text.strip():
                    continue
                yield self._doc(
                    doc_id=f"hf_vyber:{rel}#{i}",
                    text=text,
                    url=None,
                    title=path.stem.replace("_", " "),
                )

    def _record_text(self, rec) -> str:
        if isinstance(rec, str):
            return rec
        if not isinstance(rec, dict):
            return str(rec)
        for a, b in _PAIRS:
            if a in rec and b in rec:
                extra = f"\n{rec['input']}" if rec.get("input") and a != "input" else ""
                return f"{rec[a]}{extra}\n\n{rec[b]}".strip()
        for key in ("text", "content", "body"):
            if isinstance(rec.get(key), str):
                return rec[key]
        # generic: join string leaves
        parts: List[str] = []
        for k, v in rec.items():
            if isinstance(v, str) and v.strip():
                parts.append(f"{k}: {v}")
        return "\n".join(parts)
