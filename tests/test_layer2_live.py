"""Phase 6's "done when", live: each Layer 2 demo ticket is reproduced against the running shop
(scenarios/scenario.py), then run through the whole graph with real models, HolmesGPT and the
codebox. Ticket 3 is a false positive, 4 and 5 are bugs with the right file and commit, 6 is a
config incident, and 7 links to ticket 4's open issue.

Run with `make test-layer2` (needs make shop-up, make sandbox-images analyst-images and a model
key; about 25 minutes and well under a dollar). The tests run in order: 7 needs 4's memory.
"""

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from sqlalchemy.engine import make_url

from app import db, models_config
from app.events import StageEvent
from app.graph.build import build_graph, checkpoint_serde
from app.graph.stream import run_graph
from app.indexer.__main__ import index_service, sandbox_dir
from app.models import Ticket
from app.nodes._config import ownership
from app.nodes.findings import same_commit
from app.nodes.retrieve import embedder
from app.retrieval import cli as retrieval_cli
from app.retrieval.index import index_help, index_tickets
from app.settings import ROOT, settings

sys.path.insert(0, str(ROOT / "scenarios"))
import scenario  # noqa: E402

pytestmark = pytest.mark.layer2

SANDBOX = sandbox_dir().resolve()
RUNS: dict[str, dict] = {}  # ticket -> final graph state, for the later tickets


def commit_of(title: str) -> str:
    return subprocess.run(
        [
            "git",
            "-C",
            str(SANDBOX),
            "log",
            "--format=%H",
            "-1",
            "--fixed-strings",
            f"--grep={title}",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


@pytest.fixture(scope="module", autouse=True)
def prepared():
    """A fresh _test database with help, ticket memory, and the code index (cards for the two
    services with planted bugs) at both tags."""
    if not (make_url(settings.database_url).database or "").endswith("_test"):
        pytest.fail("DATABASE_URL must name a database ending in _test (make test-layer2)")
    if missing := models_config.missing_keys():
        pytest.fail(f"set {', '.join(sorted(missing))} in .env.agent")
    if not scenario.Shop(scenario.SHOP_URL).reachable():
        pytest.fail("the shop isn't up; run make shop-up")

    async def fill():
        await index_help(retrieval_cli.help_sections(), embedder())
        await index_tickets(retrieval_cli.past_tickets(), embedder())
        for tag in ("v1.3.0", "v1.4.0"):
            for service in ownership():
                cards = tag == "v1.4.0" and service in ("payment", "quote")
                print(await index_service(SANDBOX, service, tag, cards=cards))
        await db.engine.dispose()

    asyncio.run(fill())


@pytest.fixture(autouse=True)
async def fresh_connections():
    yield
    await db.engine.dispose()  # each test has its own event loop


def reproduce(n: str) -> tuple[str, str]:
    """Run scenario n against the shop; the ticket's subject and body with its real times."""
    shop = scenario.Shop(scenario.SHOP_URL)
    check = scenario.Checks(shop)
    replacements = scenario.SCENARIOS[n](
        shop, check, argparse.Namespace(gap=15, rounds=2, spacing=3, shop=scenario.SHOP_URL)
    )
    assert check.passed, f"scenario {n} did not reproduce"
    t = scenario.template(n)
    subject, body = t["subject"], t["body"]
    for phrase, value in (replacements or {}).items():
        subject, body = subject.replace(phrase, value), body.replace(phrase, value)
    return subject, body


async def investigate(n: str, subject: str, body: str) -> dict:
    """The whole graph on one ticket, approved when it pauses, so remember runs."""
    ticket = Ticket(
        id=f"T-{n}",
        tenant_id="figma-merch",
        subject=subject,
        body=body,
        received_at=datetime.now(UTC),
    )
    await db.insert_ticket(ticket)
    graph = build_graph(InMemorySaver(serde=checkpoint_serde()))
    events = []

    async def sink(event):
        events.append(event)

    t0 = time.monotonic()
    paused = await run_graph(graph, {"ticket": ticket}, ticket.id, sink)
    if paused:
        await run_graph(graph, Command(resume={"approved": True}), ticket.id, sink)
    state = (await graph.aget_state({"configurable": {"thread_id": ticket.id}})).values
    v = state.get("verdict")
    print(
        f"\nticket {n}: {time.monotonic() - t0:.0f} s, "
        + (f"{v.kind} {v.file_line} {v.commit} ({v.confidence:.0%})" if v else "no verdict")
        + f", duplicate_of={state.get('duplicate_of')}"
    )
    for e in events:
        if isinstance(e, StageEvent) and e.status in ("done", "failed") and e.duration_ms:
            print(f"  {e.stage}: {e.summary} ({e.duration_ms / 1000:.0f} s)")
    for f in state.get("findings", []):
        print(f"  {f.agent} r{f.round}: {f.hypothesis[:160]} [{len(f.evidence)} evidence]")
    if v:
        print(f"  root cause: {v.root_cause[:300]}\n  reply: {v.customer_reply[:300]}")
    if dump := os.environ.get("LAYER2_DUMP"):  # the whole run, for reading a failure
        path = Path(dump) / f"T-{n}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "state": {k: v for k, v in state.items() if k != "context"},
                    "events": [e.model_dump() for e in events],
                },
                default=lambda o: o.model_dump() if hasattr(o, "model_dump") else str(o),
                indent=1,
            )
        )
    RUNS[n] = state
    return state


async def test_ticket_3_is_a_false_positive():
    state = await investigate("3", *reproduce("3"))
    assert state["verdict"].kind == "false_positive"
    assert state["verdict"].owning_service == "payment"


async def test_ticket_4_is_the_expiry_bug():
    state = await investigate("4", *reproduce("4"))
    v = state["verdict"]
    assert v.kind == "confirmed_bug" and v.owning_service == "payment"
    assert v.file_line and "src/payment/charge.js" in v.file_line
    assert v.commit and same_commit(
        v.commit, commit_of("refactor: simplify card expiry comparison")
    )


async def test_ticket_5_is_the_bulk_quote_bug():
    state = await investigate("5", *reproduce("5"))
    v = state["verdict"]
    assert v.kind == "confirmed_bug" and v.owning_service == "quote"
    assert v.file_line and "src/quote/" in v.file_line
    assert v.commit and same_commit(v.commit, commit_of("perf: batch quote calculation"))


async def test_ticket_6_is_a_config_incident():
    try:
        state = await investigate("6", *reproduce("6"))
    finally:  # the scenario leaves paymentFailure at 25%, and the fork dirty
        subprocess.run([ROOT / "scenarios" / "flag.sh", "paymentFailure", "off"], check=False)
        subprocess.run(["git", "-C", str(SANDBOX), "checkout", "--", "src/flagd"], check=False)
    assert state["verdict"].kind == "config_incident"
    assert state["verdict"].owning_service == "payment"


async def test_ticket_7_links_to_ticket_4():
    if RUNS.get("4", {}).get("verdict") is None:
        pytest.skip("ticket 4 didn't run")
    t = scenario.template("7")
    state = await investigate("7", t["subject"], t["body"])
    assert state["duplicate_of"] == "T-4"
    assert "verdict" not in state  # the analysts didn't run
