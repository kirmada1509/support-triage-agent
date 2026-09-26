from datetime import UTC, datetime, timedelta

import pytest
import yaml

from app.graph import build
from app.models import (
    Classification,
    ContextBundle,
    Deploy,
    Enrichment,
    Layer1Answer,
    RequestTriage,
    Ticket,
)
from app.settings import ROOT

NOW = datetime(2026, 9, 23, 10, 20, tzinfo=UTC)


def demo_ticket(n: str) -> Ticket:
    tickets = yaml.safe_load((ROOT / "scenarios" / "tickets.yaml").read_text())["tickets"]
    t = next(t for t in tickets if t["id"] == n)
    return Ticket(
        id=f"T-{n}", tenant_id="figma-merch", subject=t["subject"], body=t["body"], received_at=NOW
    )


@pytest.fixture(autouse=True)
def no_db(request, monkeypatch):
    """The context node reads Postgres; tests hand it a fixed bundle instead (except the
    `db` tests, which use the real thing)."""
    if request.node.get_closest_marker("db"):
        return

    async def fake_fetch_context(ticket, services, hours=24):
        return ContextBundle(
            services=services,
            deploys=[
                Deploy(
                    id=1,
                    service="payment",
                    version="v1.4.0",
                    previous_version="v1.3.0",
                    git_sha="a1b2c3d",
                    deployed_at=NOW - timedelta(minutes=50),
                    commit_titles=["refactor: simplify card expiry comparison"],
                )
            ],
        )

    monkeypatch.setattr("app.nodes.context.fetch_context", fake_fetch_context)


@pytest.fixture
def front_stage_fakes(monkeypatch):
    """Fake front stages, so graph tests exercise lanes without a model or retrieval database."""

    async def enriched(state):
        end = state["ticket"].received_at
        return {
            "enrichment": Enrichment(
                window_start=end - timedelta(hours=3),
                window_end=end,
                window_basis="test",
                symptom=state["ticket"].subject,
            )
        }

    async def retrieved(state):
        return {"retrieved": []}

    async def classified(state):
        ticket_id = state["ticket"].id
        kind = {"T-1": "how_to", "T-2": "request"}.get(ticket_id, "tech_issue")
        return {
            "classification": Classification(
                ticket_type=kind,
                ticket_type_confidence=0.9,
                service="checkout" if kind == "request" else "payment",
                severity=2,
                revenue_blocking=kind == "tech_issue",
                revenue_blocking_confidence=0.9,
            )
        }

    async def answered(state):
        answer = Layer1Answer(answer="A human will follow up.", cited_ids=[], confident=False)
        return {"layer1": answer, "reply": answer.answer}

    async def requested(state):
        triage = RequestTriage(
            kind="feature", summary="Apple Pay", acknowledgement="Thanks for the suggestion."
        )
        return {"request": triage, "reply": triage.acknowledgement}

    for name, fn in {
        "enrich": enriched,
        "retrieve": retrieved,
        "jev": classified,
        "layer1": answered,
        "requests": requested,
    }.items():
        monkeypatch.setitem(build.NODES, name, fn)
