"""python -m app.indexer: one service at one commit of a fork, stored once, with its card."""

import subprocess
from pathlib import Path

import pytest

from app import db
from app.indexer import __main__ as cli
from app.indexer import card
from tests.test_indexer import FILES, PROTO


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
    ).stdout.strip()


@pytest.fixture
def fork(tmp_path) -> Path:
    for path, text in {**FILES, "pb/demo.proto": PROTO}.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(text)
    git(tmp_path, "init", "-q")
    git(tmp_path, "add", ".")
    git(tmp_path, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "v1.4.0")
    git(tmp_path, "tag", "v1.4.0")
    return tmp_path


@pytest.fixture
def store(monkeypatch) -> dict:
    """The index tables, in memory."""
    stored: dict = {"indexes": {}, "cards": {}}

    async def replace_code_index(index):
        stored["indexes"][(index.service, index.git_sha)] = index

    async def code_index_exists(service, sha):
        return (service, sha) in stored["indexes"]

    async def service_cards(sha):
        return {s: c for (s, h), c in stored["cards"].items() if h == sha}

    async def save_service_card(service, sha, text):
        stored["cards"][(service, sha)] = text

    for fn in (replace_code_index, code_index_exists, service_cards, save_service_card):
        monkeypatch.setattr(db, fn.__name__, fn)
    return stored


@pytest.fixture
def cards(monkeypatch) -> list[str]:
    written: list[str] = []

    async def write_card(index, description):
        written.append(index.service)
        return f"# {index.service}\n{description}"

    monkeypatch.setattr(card, "write_card", write_card)
    return written


async def test_a_service_is_indexed_at_the_tagged_commit_with_its_card(fork, store, cards):
    report = await cli.index_service(fork, "payment", "v1.4.0")
    sha = git(fork, "rev-parse", "v1.4.0")
    index = store["indexes"][("payment", sha)]
    assert [r.method for r in index.rpcs] == ["PaymentService/Charge"]
    assert "expired on" in " ".join(e.text for e in index.errors)
    assert store["cards"][("payment", sha)].startswith("# payment\nValidates card number")
    assert report.startswith(f"payment@{sha[:8]}: ") and report.endswith("service card written")


async def test_a_stored_index_and_card_are_not_rebuilt(fork, store, cards):
    await cli.index_service(fork, "payment", "v1.4.0")
    report = await cli.index_service(fork, "payment", "v1.4.0")
    assert report.endswith("already indexed") and cards == ["payment"]


async def test_a_failed_card_leaves_the_index(fork, store, monkeypatch):
    async def down(index, description):
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(card, "write_card", down)
    report = await cli.index_service(fork, "payment", "v1.4.0")
    assert "no service card (RuntimeError: model unavailable)" in report
    assert len(store["indexes"]) == 1 and not store["cards"]


async def test_cards_can_be_skipped(fork, store, cards):
    await cli.index_service(fork, "payment", "v1.4.0", cards=False)
    assert cards == [] and len(store["indexes"]) == 1


def test_an_unknown_service_is_refused():
    with pytest.raises(SystemExit, match="unknown service 'billing'"):
        cli.service_path("billing")
