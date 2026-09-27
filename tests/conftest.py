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
from app.settings import ROOT, settings

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
    # Unit and live Layer 2 suites never write to configured external accounts.
    monkeypatch.setattr(settings, "linear_api_key", "")
    monkeypatch.setattr(settings, "pylon_api_token", "")
    monkeypatch.setattr(settings, "roadmap_linear_team", "")

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
def front_stage_fakes(monkeypatch, layer2_fakes):
    """Fake front stages (and Layer 2's outside calls), so graph tests exercise lanes without a
    model, container or database."""

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


@pytest.fixture
def layer2_fakes(monkeypatch):
    """Layer 2's outside calls faked: no analyst containers, models, retrieval or Postgres. Each
    analyst makes one call and claims nothing, so the verdict is inconclusive without a model."""
    from app.analysts import AnalystRun
    from app.events import ToolCallEvent
    from app.models import Findings, ToolRecord
    from app.nodes import (
        brief,
        codebase_analyst,
        data_analyst,
        duplicates,
        findings,
        remember,
        round2,
    )

    def one_call(stage: str, tool: str, on_call) -> AnalystRun:
        on_call(ToolCallEvent(stage=stage, call_id="x1", tool=tool, status="running"))
        return AnalystRun(answer="(fake)", calls=[ToolRecord(call_id="x1", tool=tool)])

    async def ask(question, on_call):
        return one_call("data_analyst", "deploys", on_call)

    async def investigate(task, b, on_call, **budget):
        return one_call("codebase_analyst", "bash", on_call)

    async def convert(agent, answer, calls, round=1):
        return Findings(agent=agent, hypothesis="(fake)", evidence=[], confidence=0.5, round=round)

    async def empty(*args, **kwargs):
        return []

    async def nothing(*args, **kwargs):
        return None

    monkeypatch.setattr(data_analyst, "ask", ask)
    for module in (codebase_analyst, round2):
        monkeypatch.setattr(module, "investigate", investigate)
    monkeypatch.setattr(codebase_analyst, "service_card", nothing)
    monkeypatch.setattr(codebase_analyst, "change_summary", lambda *a: "")
    monkeypatch.setattr(findings, "convert", convert)
    monkeypatch.setattr(brief, "running_version", lambda service: "v1.4.0")
    monkeypatch.setattr(duplicates, "open_investigations", empty)
    monkeypatch.setattr(duplicates, "open_tickets", empty)
    monkeypatch.setattr(remember, "write_doc", nothing)
    monkeypatch.setattr(remember, "add_investigation", nothing)
