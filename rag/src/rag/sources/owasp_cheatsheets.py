"""OWASP Cheat Sheet Series.

Lists ``cheatsheets/*.md`` in the OWASP/CheatSheetSeries repo via the GitHub
contents API, then fetches each raw markdown file. One cheat sheet = one
document. domain = "web" (most are web/appsec; override with ``domain=``).

GitHub's unauthenticated API allows ~60 requests/hour, which is enough for the
one listing call plus cached raw fetches. Set ``GITHUB_TOKEN`` to raise the
limit if you re-pull often.
"""
from __future__ import annotations

import json
import os
from typing import Iterator

from .base import Document, Source
from . import _http

LIST_URL = "https://api.github.com/repos/OWASP/CheatSheetSeries/contents/cheatsheets"


class OwaspCheatSheetsSource(Source):
    name = "owasp_cheatsheets"
    default_domain = "web"

    def documents(self) -> Iterator[Document]:
        cache = self.cfg.cache_dir / self.name
        # The listing call may need auth headers; use requests directly but keep
        # the per-file raw fetches cached.
        listing = self._list(cache)
        for item in listing:
            if not item.get("name", "").endswith(".md"):
                continue
            raw_url = item.get("download_url")
            if not raw_url:
                continue
            md = _http.get(raw_url, cache, ttl=30 * 24 * 3600)
            name = item["name"][:-3]
            title = name.replace("_Cheat_Sheet", "").replace("_", " ")
            yield self._doc(
                doc_id=f"owasp:{name}",
                text=md,
                url=f"https://cheatsheetseries.owasp.org/cheatsheets/{name}.html",
                title=title,
            )

    def _list(self, cache):
        if os.environ.get("RAG_OFFLINE") == "1":
            return json.loads(_http.get(LIST_URL, cache))
        import requests

        headers = {"User-Agent": _http.USER_AGENT, "Accept": "application/vnd.github+json"}
        tok = os.environ.get("GITHUB_TOKEN")
        if tok:
            headers["Authorization"] = f"Bearer {tok}"
        r = requests.get(LIST_URL, headers=headers, timeout=60)
        r.raise_for_status()
        # cache the listing text so RAG_OFFLINE reruns work
        cache.mkdir(parents=True, exist_ok=True)
        (cache / (_http._key(LIST_URL) + ".txt")).write_text(r.text, "utf-8")
        return r.json()
