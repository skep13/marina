# rag — local cybersecurity RAG for Marina / Songbird

Retrieval-augmented generation so the **Songbird** (security) and **Marina**
(general) assistants can pull vetted cybersecurity reference material at query
time, instead of being fine-tuned on it. No model weights are touched here: this
is an ingestion pipeline, a local vector store, and a query CLI.

The whole thing is designed to run **self-contained on lab3** (where the models
are served, and which is slated to become a standalone portable appliance) but
to be fully **testable on a Mac** without lab3 — using either a local
sentence-transformers embedder or an offline deterministic one.

```
rag/
  bin/rag                     CLI entry point
  src/rag/
    config.py                 env/YAML config, embedding-model registry
    embed.py                  embedders: llamacpp | sentence-transformers | hash
    store.py                  sqlite-vec vector store
    chunk.py                  word-based chunking with overlap
    ingest.py                 orchestration + incremental re-ingest
    query.py                  query -> stable result JSON
    cli.py                    argparse CLI
    sources/                  pluggable source registry (one module per source)
  deploy/                     lab3 embedding-model config (aiws + raw llama-swap)
  sources_data/               file-based source inputs (sample notes tracked)
  tests/test_smoke.py         offline end-to-end test
  data/                       vector DB + caches (gitignored)
```

## Design choices

**Vector store: [sqlite-vec].** A single C extension loaded into Python's stdlib
`sqlite3` — no server, no daemon, the whole index is one `rag.db` file you can
copy. That is the right fit for an appliance: nothing extra to run beside the
models, and KNN over a few hundred thousand chunks is fast enough locally.
Chroma pulls a large dependency tree (and historically a server process);
LanceDB is excellent but heavier and columnar-file-based. We filter by `domain`
and `source` using sqlite-vec metadata columns so `--domain web` is a true
filtered KNN, not a post-filter.

**Embeddings: one interface, three providers** (`rag/src/rag/embed.py`):

| provider | use | notes |
|---|---|---|
| `llamacpp` | **lab3 default** | OpenAI-compatible `/v1/embeddings` served by llama.cpp via llama-swap |
| `sentence-transformers` | Mac fallback | runs the matching model locally; heavy (torch) |
| `hash` | offline / CI | deterministic, no model, no network — pipeline test only |

All providers return L2-normalized vectors of a fixed dimension, so cosine
similarity is a dot product and scores are comparable. The default model is
**`bge-small-en-v1.5`** (384-dim): small, fast on CPU, available both as a GGUF
(for llama.cpp on lab3) and as a sentence-transformers model (for the Mac) so
the two produce matching vectors. `nomic-embed-text-v1.5` (768-dim) is also in
the registry — switch with `RAG_EMBED_MODEL`.

> The store records the model + dimension it was built with and refuses to serve
> queries from a different model. Changing models means re-ingesting into a fresh
> `data_dir`.

[sqlite-vec]: https://github.com/asg017/sqlite-vec

## Setup

Needs a Python whose `sqlite3` can load extensions (Homebrew/pyenv Python, or the
repo's `.venv` — the system macOS `python3` cannot). `rag/bin/rag` auto-selects
`rag/.venv`, then the repo `.venv`, then `python3`; override with `$RAG_PYTHON`.

```bash
python3 -m venv rag/.venv
rag/.venv/bin/pip install -r rag/requirements.txt
# optional Mac fallback embedder (pulls torch):
rag/.venv/bin/pip install -r rag/requirements-st.txt
```

Configure via environment variables or `rag/rag.yaml` (copy `rag.yaml.example`).
Env wins over the file. The lab3 API key is **never** in the YAML — it comes from
`$MARINA_LAB3_KEY` or `~/.marina/agent-keys.env`.

## Quickstart (offline, no lab3, no downloads)

```bash
export RAG_EMBED_PROVIDER=hash          # deterministic test embedder
rag/bin/rag ingest notes                # ingest the sample notes
rag/bin/rag query "how do I prevent SSRF?" --k 3 --domain web
rag/bin/rag stats
```

The offline smoke test exercises ingest → incremental re-ingest → query →
domain filter:

```bash
RAG_EMBED_PROVIDER=hash rag/.venv/bin/python rag/tests/test_smoke.py
```

## Real embeddings on a Mac (no lab3)

```bash
export RAG_EMBED_PROVIDER=sentence-transformers
export RAG_EMBED_MODEL=bge-small-en-v1.5
rag/bin/rag ingest notes mitre_attack owasp_cheatsheets
rag/bin/rag query "privilege escalation on windows" --k 6
```

## Embedding model on lab3 (the real deployment)

lab3 currently serves **no** embedding model. Add a small GGUF embedder as a
resident llama-swap entry so retrieval never evicts the chat models.

1. **Download the GGUF** (lab3 has `curl`, no `hf` CLI):
   ```bash
   curl -fL -o /models/bge-small-en-v1.5-q8_0.gguf \
     https://huggingface.co/CompendiumLabs/bge-small-en-v1.5-gguf/resolve/main/bge-small-en-v1.5-q8_0.gguf
   ```
2. **Register it with llama-swap.** Two ways, depending on how lab3's config is
   managed:
   - **aiws-managed:** copy `deploy/aiws-models.d/bge-small-en.yaml` to
     `~/.config/aiws/models.d/` (or `/etc/aiws/models.d/`) and let `aiwsd`
     rewrite the llama-swap config. The `embed` role adds `--embeddings`;
     `resident: true` puts it in the non-swapping group.
   - **hand-maintained `config.yaml`:** merge `deploy/llama-swap-embed.snippet.yaml`
     into `/opt/llama-swap/config.yaml`, then
     `llama-swap -validate /opt/llama-swap/config.yaml` and let `-watch-config`
     reload. (Back up first; see the `modelctl` tooling for the safe
     backup+validate+atomic-mv flow.)
3. **Point rag at it** (defaults already match):
   ```bash
   export RAG_EMBED_PROVIDER=llamacpp
   export RAG_EMBED_BASE_URL=http://192.168.1.15:8080
   export RAG_EMBED_REMOTE_MODEL=embed      # llama-swap served name
   # key read from $MARINA_LAB3_KEY or ~/.marina/agent-keys.env
   rag/bin/rag embed-check "smoke"          # confirms the endpoint + dim
   rag/bin/rag ingest --all
   ```

`embed-check` is the quickest way to confirm the endpoint is up and returning
the expected dimension.

## Sources

`rag/bin/rag sources` lists what's registered:

| source | domain | intake |
|---|---|---|
| `notes` | per-file | `.md`/`.txt` under `sources_data/notes/` (sample notes included) |
| `mitre_attack` | `att&ck` | Enterprise ATT&CK STIX bundle (fetched + cached) |
| `nvd_cve` | `cve` | local NVD feed files in `sources_data/nvd/`, else NVD API 2.0 |
| `owasp_cheatsheets` | `web` | OWASP Cheat Sheet Series markdown (GitHub) |
| `portswigger` | `web` | Web Security Academy topic pages (curated list) |
| `hf_vyber` | `misc` | cleaned subset of the gated HF dataset (manual download) |

Ingest is **re-runnable and incremental**: each document is hashed, and an
unchanged document is skipped (no re-embedding). `--prune` removes documents
that disappeared from a source; `--force` re-embeds everything.

```bash
rag/bin/rag ingest mitre_attack --prune      # refresh ATT&CK, drop removed
rag/bin/rag ingest --all                     # everything that's configured
```

Network fetches are cached under `data/cache/<source>/`. Set `RAG_OFFLINE=1` to
use only the cache (fail on a miss) — handy for reproducible runs and for lab3
where you may pre-seed the cache with `curl`.

### The Hugging Face dataset (`Vyber07/cyber-security`) — manual, gated

This dataset is **gated** and of **uncertain provenance** (tagged apache-2.0 but
assembled from third-party sources like HackTheBox/PortSwigger). You must accept
its terms and download it yourself; it is not fetched automatically and the
download is `.gitignore`d.

1. Accept the terms at `https://huggingface.co/datasets/Vyber07/cyber-security`.
2. Download the files into `rag/sources_data/hf_vyber/` (any layout; `*.json`
   are discovered recursively). It has 507 files; ~113 are invalid JSON.
3. `rag/bin/rag ingest hf_vyber` — the loader parses every `*.json` and **drops
   the invalid ones** (the count shows as `notes.skipped` in the ingest report).

Keep this index private given the licensing uncertainty.

## Adding a source

1. Create `rag/src/rag/sources/my_source.py` with a `Source` subclass that
   yields `Document`s:
   ```python
   from .base import Document, Source

   class MySource(Source):
       name = "my_source"
       default_domain = "web"      # coarse topic tag for its chunks

       def documents(self):
           yield self._doc(
               doc_id="my_source:some-stable-id",   # stable across runs
               text="...",
               url="https://...",
               title="...",
           )
   ```
   `doc_id` must be **stable** (a URL or path) so re-ingest overwrites in place.
   `content_hash` (text+title) drives incrementality automatically.
2. Register it in `rag/src/rag/sources/__init__.py` — import the class and add
   one line to `REGISTRY`.
3. `rag/bin/rag ingest my_source`.

Source options pass through the loader, e.g. `NotesSource(path=...)`,
`NvdCveSource(keyword="openssh", limit=50)`, `PortSwiggerSource(urls=[...])`.

## Query JSON contract

This is the **stable interface** a Songbird/Marina agent tool will call
(`server/agent/` wiring is a separate step). Keys are append-only — fields may be
added, never renamed or removed.

```bash
rag/bin/rag query "how does SSRF reach cloud metadata?" --k 6 --domain web
```

```json
{
  "query": "how does SSRF reach cloud metadata?",
  "k": 6,
  "domain": "web",
  "source": null,
  "model": "bge-small-en-v1.5",
  "provider": "llamacpp",
  "count": 6,
  "results": [
    {
      "rank": 1,
      "score": 0.83,
      "text": "…chunk text…",
      "source": "portswigger",
      "url": "https://portswigger.net/web-security/ssrf",
      "domain": "web",
      "title": "Ssrf",
      "chunk_id": "portswigger:ssrf#002"
    }
  ]
}
```

- `score` is cosine similarity in `[-1, 1]`, higher is better (derived from the
  L2 distance of normalized vectors: `1 - d²/2`).
- `--domain` / `--source` are filtered KNN (correct top-k within the filter).
- `--max-chars N` truncates each chunk's `text` (metadata is untouched).
- `--compact` emits single-line JSON (for programmatic callers).

Flags: `--k` (default 6), `--domain`, `--source`, `--max-chars`, `--compact`.

## Environment variables

| var | meaning |
|---|---|
| `RAG_PYTHON` | Python interpreter for `bin/rag` |
| `RAG_DATA_DIR` | where `rag.db` + caches live (default `rag/data`) |
| `RAG_SOURCES_DIR` | file-source inputs root (default `rag/sources_data`) |
| `RAG_CONFIG` | path to a YAML config (default `rag/rag.yaml`) |
| `RAG_EMBED_PROVIDER` | `llamacpp` \| `sentence-transformers` \| `hash` |
| `RAG_EMBED_MODEL` | `bge-small-en-v1.5` \| `nomic-embed-text-v1.5` |
| `RAG_EMBED_BASE_URL` | llama-swap base URL (llamacpp provider) |
| `RAG_EMBED_REMOTE_MODEL` | served model name on llama-swap (default `embed`) |
| `RAG_EMBED_KEY_ENV` | env var holding the API key (default `MARINA_LAB3_KEY`) |
| `RAG_OFFLINE` | `1` = use only cached fetches |
| `NVD_API_KEY`, `GITHUB_TOKEN` | lift rate limits for those sources |
