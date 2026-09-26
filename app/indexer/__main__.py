"""Index the fork's code once per deployed version, and export it for the codebox.

  uv run python -m app.indexer index payment v1.4.0     # one service (deploy.sh step 4)
  uv run python -m app.indexer index-all v1.4.0         # every service in ownership.yaml
  uv run python -m app.indexer export v1.4.0 <dir>      # the TSV files the helper commands read
  uv run python -m app.indexer changes payment v1.3.0 v1.4.0

The fork is SANDBOX_DIR (default ../opentelemetry-demo). An index already stored for a
(service, commit) is kept unless --force; a service card is written once per (service, commit),
and a failed card call leaves the rest of the index in place (INDEX_CARDS=0 skips cards).
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

from app import db
from app.indexer import build, card, export
from app.nodes._config import ownership
from app.settings import ROOT


def sandbox_dir() -> Path:
    return Path(os.environ.get("SANDBOX_DIR", ROOT.parent / "opentelemetry-demo"))


def service_path(service: str) -> str:
    services = ownership()
    if service not in services:
        raise SystemExit(f"unknown service {service!r}; choose from {', '.join(services)}")
    return services[service]["path"].rstrip("/")


async def index_service(
    repo: Path, service: str, rev: str, *, cards: bool = True, force: bool = False
) -> str:
    """Store one service's index at a commit; returns a one-line report."""
    sha = build.resolve(repo, rev)
    stored = await db.code_index_exists(service, sha)
    index = None
    if force or not stored:
        index = build.index_at(repo, service, service_path(service), sha)
        await db.replace_code_index(index)
    report = f"{service}@{sha[:8]}: " + (
        f"{len(index.symbols)} symbols, {len(index.errors)} errors, "
        f"{len(index.rpcs)} rpcs, {len(index.flags)} flag reads"
        if index
        else "already indexed"
    )
    if not cards or service in await db.service_cards(sha):
        return report
    index = index or build.index_at(repo, service, service_path(service), sha)
    try:
        text = await card.write_card(index, ownership()[service]["description"])
    except Exception as e:  # the card is orientation only; the index stands without it
        return f"{report}; no service card ({type(e).__name__}: {e})"
    await db.save_service_card(service, sha, text)
    return f"{report}; service card written"


async def export_index(repo: Path, rev: str, out: Path) -> int:
    sha = build.resolve(repo, rev)
    indexes = await db.load_code_index(sha)
    export.write(out, indexes, await db.service_cards(sha))
    return len(indexes)


async def main(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="python -m app.indexer")
    sub = parser.add_subparsers(dest="cmd", required=True)
    one = sub.add_parser("index")
    one.add_argument("service")
    one.add_argument("rev")
    every = sub.add_parser("index-all")
    every.add_argument("rev")
    for p in (one, every):
        p.add_argument("--force", action="store_true", help="rebuild a stored index")
    out = sub.add_parser("export")
    out.add_argument("rev")
    out.add_argument("out", type=Path)
    changes = sub.add_parser("changes")
    changes.add_argument("service")
    changes.add_argument("previous")
    changes.add_argument("rev")
    args = parser.parse_args(argv)

    repo = sandbox_dir()
    cards = os.environ.get("INDEX_CARDS", "1") != "0"
    if args.cmd == "index":
        print(await index_service(repo, args.service, args.rev, cards=cards, force=args.force))
    elif args.cmd == "index-all":
        for service in ownership():
            print(await index_service(repo, service, args.rev, cards=cards, force=args.force))
    elif args.cmd == "export":
        n = await export_index(repo, args.rev, args.out)
        print(f"exported {n} services at {args.rev} to {args.out}")
    else:
        print(build.change_summary(repo, service_path(args.service), args.previous, args.rev))


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
