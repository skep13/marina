"""Offline end-to-end smoke test: notes source -> hash embedder -> sqlite-vec
-> query. No network, no model downloads. Run with:

    RAG_EMBED_PROVIDER=hash pytest rag/tests
    (or)  python rag/tests/test_smoke.py

Needs sqlite-vec and a Python whose sqlite3 can load extensions.
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def _cfg(tmp):
    os.environ["RAG_EMBED_PROVIDER"] = "hash"
    os.environ["RAG_EMBED_MODEL"] = "bge-small-en-v1.5"
    os.environ["RAG_DATA_DIR"] = str(Path(tmp) / "data")
    os.environ["RAG_SOURCES_DIR"] = str(
        Path(__file__).resolve().parent.parent / "sources_data"
    )
    from rag.config import load

    return load()


def run():
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _cfg(tmp)
        from rag.ingest import ingest
        from rag.query import query
        from rag.store import Store

        stats = ingest(["notes"], cfg, prune=True)
        assert stats[0].docs_embedded >= 2, stats
        assert stats[0].chunks >= 2, stats

        # re-run is incremental: nothing re-embedded
        stats2 = ingest(["notes"], cfg)
        assert stats2[0].docs_embedded == 0, stats2
        assert stats2[0].docs_skipped >= 2, stats2

        out = query("how do I prevent SSRF to the cloud metadata endpoint?", cfg, k=3)
        assert out["results"], out
        assert out["count"] <= 3
        top = out["results"][0]
        for key in ("rank", "score", "text", "source", "url", "domain", "title", "chunk_id"):
            assert key in top, f"missing {key} in result"
        assert top["source"] == "notes"

        # domain filter returns only that domain
        web = query("ssrf", cfg, k=5, domain="web")
        assert all(r["domain"] == "web" for r in web["results"]), web
        net = query("pivoting", cfg, k=5, domain="network")
        assert all(r["domain"] == "network" for r in net["results"]), net

        with Store(cfg) as store:
            s = store.stats()
            assert s["chunks"] >= 2
            assert "notes" in s["by_source"]

    print("smoke OK")


def test_smoke():
    run()


if __name__ == "__main__":
    run()
