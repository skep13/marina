"""Tiny cached HTTP helper for network sources.

Caches raw responses under ``data/cache/<source>/`` keyed by a hash of the URL
so re-runs are cheap and offline-friendly, and so lab3 (which has curl/wget but
no fancy fetchers) can pre-seed the cache if needed. Honors ``RAG_OFFLINE=1``:
when set, only cached responses are used and a miss raises.
"""
from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path

USER_AGENT = "marina-rag/0.1 (+local cybersec RAG; contact: repo owner)"


def _key(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:20]


def get(url: str, cache_dir: Path, ttl: float = 7 * 24 * 3600, binary: bool = False):
    cache_dir.mkdir(parents=True, exist_ok=True)
    ext = ".bin" if binary else ".txt"
    cached = cache_dir / (_key(url) + ext)
    if cached.exists() and (time.time() - cached.stat().st_mtime) < ttl:
        return cached.read_bytes() if binary else cached.read_text("utf-8", "replace")
    if os.environ.get("RAG_OFFLINE") == "1":
        if cached.exists():
            return cached.read_bytes() if binary else cached.read_text("utf-8", "replace")
        raise RuntimeError(f"RAG_OFFLINE=1 and no cache for {url}")

    import requests

    r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=60)
    r.raise_for_status()
    if binary:
        cached.write_bytes(r.content)
        return r.content
    cached.write_text(r.text, "utf-8")
    return r.text


def strip_html(html: str) -> str:
    """Best-effort HTML -> text. Uses BeautifulSoup if present, else a crude
    regex fallback so core installs still work."""
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        import re

        html = re.sub(r"(?is)<(script|style|nav|header|footer).*?</\1>", " ", html)
        html = re.sub(r"(?s)<[^>]+>", " ", html)
        import html as _h

        return _h.unescape(re.sub(r"[ \t]+", " ", html))
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer", "noscript"]):
        tag.decompose()
    main = soup.find("main") or soup.find("article") or soup.body or soup
    return main.get_text("\n")
