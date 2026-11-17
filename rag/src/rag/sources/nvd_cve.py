"""NVD / CVE records.

Two intake modes (the loader uses whichever applies):

1. Local feed files — any ``*.json`` under ``sources_data/nvd/`` in NVD API 2.0
   shape (a top-level ``vulnerabilities`` list, or a bare list of ``cve``
   objects). Best for bulk/offline: download the feeds once with curl on lab3.
2. Live API — NVD API 2.0 (``services.nvd.nist.gov``). Bounded by ``limit`` and
   optionally ``keyword=``; set ``NVD_API_KEY`` to lift the rate limit. This is
   for keeping a small, current slice fresh, not for mirroring all of NVD.

Each CVE becomes one document: id, CVSS severity, the English description and
reference URLs. domain = "cve".
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Iterator

from .base import Document, Source
from . import _http

API = "https://services.nvd.nist.gov/rest/json/cves/2.0"


class NvdCveSource(Source):
    name = "nvd_cve"
    default_domain = "cve"

    def _local_dir(self) -> Path:
        p = self.opts.get("path")
        return Path(p) if p else self.cfg.sources_dir / "nvd"

    def documents(self) -> Iterator[Document]:
        local = self._local_dir()
        files = sorted(local.glob("*.json")) if local.exists() else []
        if files:
            for f in files:
                data = json.loads(f.read_text("utf-8", "replace"))
                vulns = data.get("vulnerabilities", data if isinstance(data, list) else [])
                for v in vulns:
                    doc = self._to_doc(v.get("cve", v))
                    if doc:
                        yield doc
        else:
            yield from self._from_api()

    def _from_api(self) -> Iterator[Document]:
        limit = int(self.opts.get("limit", 200))
        keyword = self.opts.get("keyword")
        got = 0
        start = 0
        page = min(2000, limit)
        while got < limit:
            params = {"resultsPerPage": page, "startIndex": start}
            if keyword:
                params["keywordSearch"] = keyword
            url = API + "?" + "&".join(f"{k}={v}" for k, v in params.items())
            raw = self._api_get(url)
            data = json.loads(raw)
            vulns = data.get("vulnerabilities", [])
            if not vulns:
                break
            for v in vulns:
                doc = self._to_doc(v.get("cve", {}))
                if doc:
                    yield doc
                    got += 1
                    if got >= limit:
                        break
            start += len(vulns)
            if start >= data.get("totalResults", 0):
                break
            time.sleep(0.6 if os.environ.get("NVD_API_KEY") else 6.0)

    def _api_get(self, url: str) -> str:
        if os.environ.get("RAG_OFFLINE") == "1":
            return _http.get(url, self.cfg.cache_dir / self.name)
        import requests

        headers = {"User-Agent": _http.USER_AGENT}
        key = os.environ.get("NVD_API_KEY")
        if key:
            headers["apiKey"] = key
        r = requests.get(url, headers=headers, timeout=90)
        r.raise_for_status()
        cache = self.cfg.cache_dir / self.name
        cache.mkdir(parents=True, exist_ok=True)
        (cache / (_http._key(url) + ".txt")).write_text(r.text, "utf-8")
        return r.text

    def _to_doc(self, cve: dict):
        cid = cve.get("id")
        if not cid:
            return None
        descs = cve.get("descriptions", [])
        desc = next((d["value"] for d in descs if d.get("lang") == "en"), "")
        if not desc:
            return None
        sev = self._severity(cve)
        refs = [r.get("url") for r in cve.get("references", []) if r.get("url")][:6]
        parts = [cid]
        if sev:
            parts.append(f"Severity: {sev}")
        parts.append(desc)
        if refs:
            parts.append("References:\n" + "\n".join(refs))
        return self._doc(
            doc_id=f"cve:{cid}",
            text="\n".join(parts),
            url=f"https://nvd.nist.gov/vuln/detail/{cid}",
            title=cid,
            extra={"severity": sev},
        )

    @staticmethod
    def _severity(cve: dict) -> str:
        metrics = cve.get("metrics", {})
        for key in ("cvssMetricV31", "cvssMetricV30", "cvssMetricV2"):
            arr = metrics.get(key)
            if arr:
                data = arr[0].get("cvssData", {})
                base = data.get("baseScore")
                sev = data.get("baseSeverity") or arr[0].get("baseSeverity")
                return f"{sev} ({base})" if base is not None else (sev or "")
        return ""
