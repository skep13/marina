"""Embedding providers.

Three providers behind one interface so the pipeline is identical everywhere:

- ``llamacpp``            — lab3 default. POSTs to an OpenAI-compatible
                            ``/v1/embeddings`` served by llama.cpp through
                            llama-swap. This is where the appliance runs.
- ``sentence-transformers`` — Mac fallback. Runs the matching model locally so
                            you can build and test without lab3.
- ``hash``                — deterministic, no model, no network. Vectors are
                            meaningless for retrieval quality but let the whole
                            ingest/query path be tested offline and in CI.

All providers return L2-normalized float32 vectors of ``cfg.embed.dim`` so the
store can treat cosine similarity as a dot product and distances are comparable
across providers (though vectors only match between the llama.cpp and
sentence-transformers runs of the *same* model).
"""
from __future__ import annotations

import hashlib
import math
from typing import List, Sequence

from .config import Config


class EmbedError(RuntimeError):
    pass


def _normalize(vec: List[float]) -> List[float]:
    n = math.sqrt(sum(x * x for x in vec))
    if n == 0:
        return vec
    return [x / n for x in vec]


class Embedder:
    """Base: subclasses implement ``_embed(texts) -> list[list[float]]``."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.dim = cfg.embed.dim

    # public entry points apply the model's document/query instructions
    def embed_documents(self, texts: Sequence[str]) -> List[List[float]]:
        pfx = self.cfg.embed.doc_prefix
        return self._run([pfx + t for t in texts])

    def embed_query(self, text: str) -> List[float]:
        pfx = self.cfg.embed.query_prefix
        return self._run([pfx + text])[0]

    def _run(self, texts: Sequence[str]) -> List[List[float]]:
        out: List[List[float]] = []
        bs = max(1, self.cfg.embed.batch_size)
        for i in range(0, len(texts), bs):
            out.extend(self._embed(list(texts[i : i + bs])))
        if self.cfg.embed.normalize:
            out = [_normalize(v) for v in out]
        for v in out:
            if len(v) != self.dim:
                raise EmbedError(
                    f"embedder returned dim {len(v)} but config expects {self.dim}; "
                    f"check RAG_EMBED_MODEL / the lab3 embed model"
                )
        return out

    def _embed(self, texts: List[str]) -> List[List[float]]:  # pragma: no cover
        raise NotImplementedError


class HashEmbedder(Embedder):
    """Deterministic bag-of-hashed-tokens. Test-only; do not ship as the real
    retriever. Lets ``rag ingest``/``rag query`` run with zero dependencies."""

    def _embed(self, texts: List[str]) -> List[List[float]]:
        vecs = []
        for t in texts:
            v = [0.0] * self.dim
            for tok in t.lower().split():
                h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
                v[h % self.dim] += 1.0
            vecs.append(v)
        return vecs


class SentenceTransformerEmbedder(Embedder):
    def __init__(self, cfg: Config):
        super().__init__(cfg)
        from .config import EMBED_MODELS

        spec = EMBED_MODELS.get(cfg.embed.model)
        model_id = spec["st_model"] if spec else cfg.embed.model
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as e:  # pragma: no cover
            raise EmbedError(
                "sentence-transformers not installed; `pip install -r "
                "rag/requirements-st.txt` or use the llamacpp/hash provider"
            ) from e
        # nomic needs trust_remote_code; bge does not. Try without, retry with.
        try:
            self._model = SentenceTransformer(model_id)
        except Exception:
            self._model = SentenceTransformer(model_id, trust_remote_code=True)

    def _embed(self, texts: List[str]) -> List[List[float]]:
        # normalize ourselves in _run to stay consistent across providers
        arr = self._model.encode(texts, normalize_embeddings=False)
        return [list(map(float, row)) for row in arr]


class LlamaCppEmbedder(Embedder):
    """OpenAI-compatible ``/v1/embeddings`` served by llama.cpp via llama-swap.

    The served model name is ``cfg.embed.remote_model`` (``embed`` resolves to
    whatever model carries the ``embed`` role in the aiws library). Requires an
    embedder entry in llama-swap with ``--embeddings`` (see the README)."""

    def __init__(self, cfg: Config):
        super().__init__(cfg)
        try:
            import requests  # noqa: F401
        except ImportError as e:  # pragma: no cover
            raise EmbedError("requests not installed; `pip install -r rag/requirements.txt`") from e

    def _embed(self, texts: List[str]) -> List[List[float]]:
        import requests

        e = self.cfg.embed
        headers = {"Content-Type": "application/json"}
        if e.api_key:
            headers["Authorization"] = f"Bearer {e.api_key}"
        try:
            r = requests.post(
                f"{e.base_url}/v1/embeddings",
                headers=headers,
                json={"model": e.remote_model, "input": texts},
                timeout=120,
            )
        except requests.RequestException as ex:
            raise EmbedError(f"embeddings request to {e.base_url} failed: {ex}") from ex
        if r.status_code != 200:
            raise EmbedError(
                f"embeddings endpoint {e.base_url} returned {r.status_code}: {r.text[:300]}"
            )
        data = r.json().get("data", [])
        # preserve input order via the index field when present
        data = sorted(data, key=lambda d: d.get("index", 0))
        return [d["embedding"] for d in data]


_PROVIDERS = {
    "hash": HashEmbedder,
    "sentence-transformers": SentenceTransformerEmbedder,
    "st": SentenceTransformerEmbedder,
    "llamacpp": LlamaCppEmbedder,
    "llama.cpp": LlamaCppEmbedder,
}


def get_embedder(cfg: Config) -> Embedder:
    provider = cfg.embed.provider.lower()
    cls = _PROVIDERS.get(provider)
    if not cls:
        raise EmbedError(
            f"unknown embed provider {provider!r}; one of {sorted(set(_PROVIDERS))}"
        )
    return cls(cfg)
