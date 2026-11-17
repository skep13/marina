"""PortSwigger Web Security Academy topic pages.

Fetches each topic's landing page and cleans it to text. The default is a
curated list of the core vulnerability topics; override with ``urls=[...]`` or
point ``urls_file=`` at a newline-delimited file of topic URLs (e.g. scraped
from https://portswigger.net/web-security/all-topics).

Note: the Academy content is PortSwigger's; this pulls it for a private, local
reference index. Respect their terms — keep fetches cached and infrequent.
domain = "web".
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterator, List

from .base import Document, Source
from . import _http

BASE = "https://portswigger.net/web-security/"
TOPICS = [
    "sql-injection", "cross-site-scripting", "csrf", "clickjacking",
    "cors", "xxe", "ssrf", "request-smuggling", "os-command-injection",
    "server-side-template-injection", "path-traversal", "access-control",
    "authentication", "websockets", "web-cache-poisoning", "insecure-deserialization",
    "information-disclosure", "business-logic-vulnerabilities", "http-host-header",
    "oauth", "jwt", "api-testing", "file-upload", "nosql-injection",
    "graphql", "race-conditions", "web-cache-deception", "prototype-pollution",
]


class PortSwiggerSource(Source):
    name = "portswigger"
    default_domain = "web"

    def _urls(self) -> List[str]:
        if "urls" in self.opts:
            return list(self.opts["urls"])
        uf = self.opts.get("urls_file")
        if uf and Path(uf).exists():
            return [ln.strip() for ln in Path(uf).read_text().splitlines() if ln.strip()]
        return [BASE + t for t in TOPICS]

    def documents(self) -> Iterator[Document]:
        cache = self.cfg.cache_dir / self.name
        for url in self._urls():
            try:
                html = _http.get(url, cache, ttl=30 * 24 * 3600)
            except Exception:
                continue
            text = _http.strip_html(html)
            slug = url.rstrip("/").rsplit("/", 1)[-1]
            title = slug.replace("-", " ").title()
            yield self._doc(
                doc_id=f"portswigger:{slug}",
                text=text,
                url=url,
                title=title,
            )
