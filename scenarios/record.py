"""Write deploy and flag history into the agent's Postgres. Called by deploy.sh and flag.sh.

uv run python scenarios/record.py deploy payment v1.4.0 v1.3.0 <git_sha> < commit_titles.txt
uv run python scenarios/record.py flag <path/to/demo.flagd.json> paymentFailure 25%
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import db  # noqa: E402


def run(coro) -> None:
    async def main():
        try:
            await coro
        finally:
            await db.engine.dispose()

    asyncio.run(main())


def deploy(service: str, version: str, previous: str, sha: str) -> None:
    titles = [line.strip() for line in sys.stdin if line.strip()]
    run(db.insert_deploy(service, version, previous, sha, titles))
    print(f"recorded deploy {service} {previous} -> {version} ({len(titles)} commits)")


def flag(flagd_file: str, name: str, variant: str) -> None:
    path = Path(flagd_file)
    data = json.loads(path.read_text())
    f = data["flags"][name]
    if variant not in f["variants"]:
        sys.exit(f"{name} has no variant {variant!r}; choose from {list(f['variants'])}")
    old = f["defaultVariant"]
    f["defaultVariant"] = variant
    path.write_text(json.dumps(data, indent=2) + "\n")  # flagd watches the file
    run(db.insert_flag_change(name, old, variant))
    print(f"flag {name}: {old} -> {variant}")


if __name__ == "__main__":
    cmd, *args = sys.argv[1:]
    {"deploy": deploy, "flag": flag}[cmd](*args)
