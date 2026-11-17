"""Configuration and paths.

Everything is resolved from environment variables with sensible defaults so
the same code runs on lab3 (llama.cpp embeddings, the models next door) and on
a Mac (sentence-transformers, or the offline hash embedder).

Config can also come from a YAML file (``$RAG_CONFIG`` or ``rag/rag.yaml``);
environment variables win over the file. Keep secrets (the lab3 API key) in the
environment or in ``~/.marina/agent-keys.env``, never in the YAML.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

# rag/src/rag/config.py -> rag/
PKG_ROOT = Path(__file__).resolve().parent
RAG_ROOT = PKG_ROOT.parent.parent


def _root() -> Path:
    return Path(os.environ.get("RAG_ROOT", RAG_ROOT))


def _data_dir() -> Path:
    d = os.environ.get("RAG_DATA_DIR")
    return Path(d) if d else _root() / "data"


def _load_file() -> dict:
    p = os.environ.get("RAG_CONFIG")
    path = Path(p) if p else _root() / "rag.yaml"
    if path.exists():
        with open(path) as f:
            return yaml.safe_load(f) or {}
    return {}


# Known embedding models and their retrieval instructions. The GGUF column is
# what to serve on lab3 via llama.cpp; the sentence-transformers column is the
# matching Mac fallback. Keep a query/document pair where the model expects one
# (nomic, e5) so the Mac and lab3 vectors line up.
EMBED_MODELS = {
    "bge-small-en-v1.5": {
        "dim": 384,
        "st_model": "BAAI/bge-small-en-v1.5",
        "gguf_repo": "CompendiumLabs/bge-small-en-v1.5-gguf",
        "gguf_file": "bge-small-en-v1.5-q8_0.gguf",
        # bge only instructs the query side.
        "query_prefix": "Represent this sentence for searching relevant passages: ",
        "doc_prefix": "",
        "normalize": True,
    },
    "nomic-embed-text-v1.5": {
        "dim": 768,
        "st_model": "nomic-ai/nomic-embed-text-v1.5",
        "gguf_repo": "nomic-ai/nomic-embed-text-v1.5-GGUF",
        "gguf_file": "nomic-embed-text-v1.5.Q5_K_M.gguf",
        "query_prefix": "search_query: ",
        "doc_prefix": "search_document: ",
        "normalize": True,
    },
}


@dataclass
class EmbedConfig:
    # provider: llamacpp | sentence-transformers | hash
    provider: str = "hash"
    model: str = "bge-small-en-v1.5"
    dim: int = 384
    # llama.cpp / OpenAI-compatible endpoint (llama-swap on lab3)
    base_url: str = "http://192.168.1.15:8080"
    # served name on llama-swap; `embed` is the role alias aiws resolves.
    remote_model: str = "embed"
    key_env: str = "MARINA_LAB3_KEY"
    batch_size: int = 32
    query_prefix: str = ""
    doc_prefix: str = ""
    normalize: bool = True

    @property
    def api_key(self) -> str:
        return _secret(self.key_env)


@dataclass
class Config:
    data_dir: Path = field(default_factory=_data_dir)
    embed: EmbedConfig = field(default_factory=EmbedConfig)
    chunk_tokens: int = 350
    chunk_overlap: int = 60

    @property
    def db_path(self) -> Path:
        return self.data_dir / "rag.db"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"

    @property
    def sources_dir(self) -> Path:
        """Where file-based sources (notes, the HF dataset) are read from."""
        d = os.environ.get("RAG_SOURCES_DIR")
        return Path(d) if d else _root() / "sources_data"


def _secret(name: str) -> str:
    """API key from the environment, then ~/.marina/agent-keys.env."""
    if name in os.environ:
        return os.environ[name]
    env = Path.home() / ".marina" / "agent-keys.env"
    if env.exists():
        for line in env.read_text().splitlines():
            line = line.strip()
            if line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            if k.strip() == name:
                return v.strip().strip('"').strip("'")
    return ""


def load() -> Config:
    f = _load_file()
    cfg = Config()

    if "data_dir" in f:
        cfg.data_dir = Path(f["data_dir"])
    cfg.chunk_tokens = int(os.environ.get("RAG_CHUNK_TOKENS", f.get("chunk_tokens", cfg.chunk_tokens)))
    cfg.chunk_overlap = int(os.environ.get("RAG_CHUNK_OVERLAP", f.get("chunk_overlap", cfg.chunk_overlap)))

    fe = f.get("embed", {}) or {}
    e = cfg.embed
    e.provider = os.environ.get("RAG_EMBED_PROVIDER", fe.get("provider", e.provider))
    e.model = os.environ.get("RAG_EMBED_MODEL", fe.get("model", e.model))
    e.base_url = os.environ.get("RAG_EMBED_BASE_URL", fe.get("base_url", e.base_url)).rstrip("/")
    e.remote_model = os.environ.get("RAG_EMBED_REMOTE_MODEL", fe.get("remote_model", e.remote_model))
    e.key_env = os.environ.get("RAG_EMBED_KEY_ENV", fe.get("key_env", e.key_env))
    e.batch_size = int(os.environ.get("RAG_EMBED_BATCH", fe.get("batch_size", e.batch_size)))

    # Pull per-model defaults (dim, prefixes) from the registry, then let the
    # file/env override. dim is locked to the model unless explicitly set.
    spec = EMBED_MODELS.get(e.model)
    if spec:
        e.dim = int(spec["dim"])
        e.query_prefix = spec.get("query_prefix", "")
        e.doc_prefix = spec.get("doc_prefix", "")
        e.normalize = bool(spec.get("normalize", True))
    if "dim" in fe:
        e.dim = int(fe["dim"])
    if "RAG_EMBED_DIM" in os.environ:
        e.dim = int(os.environ["RAG_EMBED_DIM"])
    if "query_prefix" in fe:
        e.query_prefix = fe["query_prefix"]
    if "doc_prefix" in fe:
        e.doc_prefix = fe["doc_prefix"]

    return cfg
