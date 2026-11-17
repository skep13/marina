"""Command-line interface: ``rag <command>``.

Commands:
  query "<question>" [--k 6] [--domain web] [--source portswigger]
                                     retrieve top-k chunks as JSON
  ingest [source ...] [--all] [--prune] [--force]
                                     build/update the index
  sources                            list registered sources
  stats                              show what's in the store
  embed-check                        embed one probe string (diagnose embedder)
"""
from __future__ import annotations

import argparse
import json
import sys

from . import sources
from .config import load


def _print(obj, pretty=True):
    json.dump(obj, sys.stdout, indent=2 if pretty else None, ensure_ascii=False)
    sys.stdout.write("\n")


def cmd_query(args) -> int:
    from .query import query

    cfg = load()
    out = query(
        args.question, cfg, k=args.k, domain=args.domain,
        source=args.source, max_chars=args.max_chars,
    )
    _print(out, pretty=not args.compact)
    return 0


def cmd_ingest(args) -> int:
    from .ingest import ingest

    cfg = load()
    names = sources.names() if args.all else args.sources
    if not names:
        print("nothing to ingest; pass source names or --all. "
              f"Known: {', '.join(sources.names())}", file=sys.stderr)
        return 2
    unknown = [n for n in names if n not in sources.names()]
    if unknown:
        print(f"unknown source(s): {', '.join(unknown)}", file=sys.stderr)
        return 2
    log = (lambda m: print(m, file=sys.stderr)) if not args.quiet else (lambda m: None)
    results = ingest(names, cfg, prune=args.prune, force=args.force, log=log)
    _print(
        {
            "model": cfg.embed.model,
            "provider": cfg.embed.provider,
            "sources": [vars(r) for r in results],
        },
        pretty=not args.compact,
    )
    return 0


def cmd_sources(args) -> int:
    import sys as _sys

    cfg = load()
    out = []
    for name in sources.names():
        cls = sources.REGISTRY[name]
        mod = _sys.modules.get(cls.__module__)
        doc = (cls.__doc__ or (mod.__doc__ if mod else "") or "").strip()
        out.append(
            {
                "name": name,
                "default_domain": cls.default_domain,
                "doc": doc.split("\n")[0],
            }
        )
    _print({"sources": out}, pretty=not args.compact)
    return 0


def cmd_stats(args) -> int:
    from .store import Store

    cfg = load()
    with Store(cfg) as store:
        _print(store.stats(), pretty=not args.compact)
    return 0


def cmd_embed_check(args) -> int:
    from .embed import get_embedder

    cfg = load()
    emb = get_embedder(cfg)
    vec = emb.embed_query(args.text)
    _print(
        {
            "provider": cfg.embed.provider,
            "model": cfg.embed.model,
            "dim": len(vec),
            "preview": [round(x, 4) for x in vec[:8]],
        },
        pretty=not args.compact,
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    # --compact on a shared parent so it works before OR after the subcommand.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--compact", action="store_true", help="single-line JSON output")

    p = argparse.ArgumentParser(prog="rag", description="Local cybersecurity RAG",
                                parents=[common])
    sub = p.add_subparsers(dest="cmd", required=True)

    q = sub.add_parser("query", help="retrieve top-k chunks as JSON", parents=[common])
    q.add_argument("question")
    q.add_argument("--k", type=int, default=6)
    q.add_argument("--domain", default=None, help="filter by domain, e.g. web, cve, att&ck")
    q.add_argument("--source", default=None, help="filter by source name")
    q.add_argument("--max-chars", type=int, default=None, dest="max_chars",
                   help="truncate each chunk's text to N chars")
    q.set_defaults(func=cmd_query)

    i = sub.add_parser("ingest", help="build/update the index", parents=[common])
    i.add_argument("sources", nargs="*", help="source names (default: none; use --all)")
    i.add_argument("--all", action="store_true", help="ingest every registered source")
    i.add_argument("--prune", action="store_true", help="drop docs no longer in the source")
    i.add_argument("--force", action="store_true", help="re-embed even unchanged docs")
    i.add_argument("--quiet", action="store_true")
    i.set_defaults(func=cmd_ingest)

    s = sub.add_parser("sources", help="list registered sources", parents=[common])
    s.set_defaults(func=cmd_sources)

    st = sub.add_parser("stats", help="show store contents", parents=[common])
    st.set_defaults(func=cmd_stats)

    e = sub.add_parser("embed-check", help="embed one probe string", parents=[common])
    e.add_argument("text", nargs="?", default="hello world")
    e.set_defaults(func=cmd_embed_check)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
