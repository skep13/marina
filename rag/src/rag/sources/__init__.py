"""Source registry.

Maps a source name to its :class:`~rag.sources.base.Source` class. To add a
source, implement a ``Source`` subclass in a new module here and add one line to
``REGISTRY`` below (see the README's "Adding a source").
"""
from __future__ import annotations

from typing import Dict, Type

from .base import Document, Source
from .notes import NotesSource
from .mitre_attack import MitreAttackSource
from .nvd_cve import NvdCveSource
from .owasp_cheatsheets import OwaspCheatSheetsSource
from .portswigger import PortSwiggerSource
from .hf_vyber import HfVyberSource

REGISTRY: Dict[str, Type[Source]] = {
    NotesSource.name: NotesSource,
    MitreAttackSource.name: MitreAttackSource,
    NvdCveSource.name: NvdCveSource,
    OwaspCheatSheetsSource.name: OwaspCheatSheetsSource,
    PortSwiggerSource.name: PortSwiggerSource,
    HfVyberSource.name: HfVyberSource,
}


def names() -> list:
    return list(REGISTRY)


def get(name: str, cfg, **opts) -> Source:
    if name not in REGISTRY:
        raise KeyError(f"unknown source {name!r}; known: {', '.join(REGISTRY)}")
    return REGISTRY[name](cfg, **opts)


__all__ = ["REGISTRY", "Document", "Source", "names", "get"]
