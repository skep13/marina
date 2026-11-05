"""MITRE ATT&CK (Enterprise) techniques.

Pulls the STIX 2.1 bundle from the public mitre-attack/attack-stix-data repo
and turns each ``attack-pattern`` into a document: name, ATT&CK id, tactics,
platforms and description. Deprecated/revoked techniques are skipped.

Pin a version with ``version=`` (default ``enterprise-attack``'s latest in the
repo's ``enterprise-attack.json``). domain = "att&ck".
"""
from __future__ import annotations

import json
from typing import Iterator

from .base import Document, Source
from . import _http

# The STIX data repo keeps the current bundle at a stable path.
BUNDLE_URL = (
    "https://raw.githubusercontent.com/mitre-attack/attack-stix-data/master/"
    "enterprise-attack/enterprise-attack.json"
)


class MitreAttackSource(Source):
    name = "mitre_attack"
    default_domain = "att&ck"

    def documents(self) -> Iterator[Document]:
        url = self.opts.get("url", BUNDLE_URL)
        raw = _http.get(url, self.cfg.cache_dir / self.name, ttl=30 * 24 * 3600)
        bundle = json.loads(raw)
        for obj in bundle.get("objects", []):
            if obj.get("type") != "attack-pattern":
                continue
            if obj.get("x_mitre_deprecated") or obj.get("revoked"):
                continue
            ext = next(
                (r for r in obj.get("external_references", [])
                 if r.get("source_name") == "mitre-attack"),
                {},
            )
            attack_id = ext.get("external_id", "")
            tactics = [
                ph.get("phase_name")
                for ph in obj.get("kill_chain_phases", [])
                if ph.get("kill_chain_name") == "mitre-attack"
            ]
            platforms = obj.get("x_mitre_platforms", [])
            name = obj.get("name", "")
            parts = [f"{attack_id} {name}".strip()]
            if tactics:
                parts.append("Tactics: " + ", ".join(t for t in tactics if t))
            if platforms:
                parts.append("Platforms: " + ", ".join(platforms))
            parts.append(obj.get("description", ""))
            yield self._doc(
                doc_id=f"attack:{attack_id or obj['id']}",
                text="\n".join(p for p in parts if p),
                url=ext.get("url"),
                title=f"{attack_id} {name}".strip(),
                extra={"attack_id": attack_id, "tactics": tactics, "platforms": platforms},
            )
