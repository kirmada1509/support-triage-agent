"""The stub graph end to end: lanes, parallel analysts, interrupt and resume, events."""

from datetime import timedelta

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from app.events import ApprovalRequiredEvent, StageEvent, ToolCallEvent
from app.graph import build as graph_build
from app.graph.build import build_graph, checkpoint_serde
from app.graph.stream import run_graph
from app.models import Classification, Enrichment, Layer1Answer, RequestTriage, Verdict
from tests.conftest import demo_ticket


@pytest.fixture(autouse=True)
def front_stage_fakes(monkeypatch):
    """The skeleton graph tests exercise lanes without network or a retrieval database."""

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
        monkeypatch.setitem(graph_build.NODES, name, fn)


class Recorder:
    def __init__(self):
        self.events = []

    async def __call__(self, event):
        self.events.append(event)

    def stages(self, status):
        return [e.stage for e in self.events if isinstance(e, StageEvent) and e.status == status]


async def run(graph, ticket_id, graph_input, seen=None):
    rec = Recorder()
    paused = await run_graph(graph, graph_input, ticket_id, rec, seen)
    return rec, paused


async def state_of(graph, ticket_id):
    return (await graph.aget_state({"configurable": {"thread_id": ticket_id}})).values


async def test_request_lane_runs_without_approval():
    graph = build_graph(InMemorySaver(serde=checkpoint_serde()))
    rec, paused = await run(graph, "T-2", {"ticket": demo_ticket("2")})
    assert paused is None
    done = rec.stages("done")
    assert done[:2] == ["context", "enrich"]
    assert {"retrieve", "jev", "route", "requests", "approve", "reply", "remember"} <= set(done)
    assert {"layer1", "duplicates", "brief", "data_analyst", "verdict"} <= set(
        rec.stages("skipped")
    )
    state = await state_of(graph, "T-2")
    assert state["lane"] == "request"
    assert state["approved"] is True


async def test_how_to_lane_pauses_then_resumes():
    graph = build_graph(InMemorySaver(serde=checkpoint_serde()))
    rec, paused = await run(graph, "T-1", {"ticket": demo_ticket("1")})
    assert paused is not None and "Layer 1 answer not confident or uncited" in paused["reasons"]
    assert isinstance(rec.events[-1], ApprovalRequiredEvent)
    assert "reply" not in rec.stages("done")
    assert not rec.stages("skipped")  # nothing is skipped while paused

    seen = {e.stage for e in rec.events if isinstance(e, StageEvent)}
    rec2, paused2 = await run(
        graph, "T-1", Command(resume={"approved": True, "reviewer": "kk"}), seen
    )
    assert paused2 is None
    assert rec2.stages("done") == ["approve", "reply", "remember"]
    assert "brief" in rec2.stages("skipped") and "approve" not in rec2.stages("skipped")
    state = await state_of(graph, "T-1")
    assert state["approved"] is True and state["reply"]


async def test_tech_issue_runs_both_analysts_and_uses_edited_reply():
    graph = build_graph(InMemorySaver(serde=checkpoint_serde()))
    rec, paused = await run(graph, "T-4", {"ticket": demo_ticket("4")})
    assert paused is not None
    done = rec.stages("done")
    assert {"duplicates", "brief", "data_analyst", "codebase_analyst", "round2", "verdict"} <= set(
        done
    )
    assert done.index("round2") > max(done.index("data_analyst"), done.index("codebase_analyst"))
    assert any(isinstance(e, ToolCallEvent) and e.stage == "codebase_analyst" for e in rec.events)
    state = await state_of(graph, "T-4")
    assert {f.agent for f in state["findings"]} == {"data_analyst", "codebase_analyst"}
    assert "revenue blocking" in paused["reasons"]

    await run(graph, "T-4", Command(resume={"approved": True, "edited_reply": "Edited."}))
    assert (await state_of(graph, "T-4"))["reply"] == "Edited."


async def test_confirmed_bug_goes_to_layer3(monkeypatch):
    async def confirmed(state):
        return {
            "verdict": Verdict(
                kind="confirmed_bug",
                root_cause="> became >=",
                owning_service="payment",
                confidence=0.9,
                customer_reply="We found the bug.",
            ),
            "reply": "We found the bug.",
        }

    monkeypatch.setitem(
        __import__("app.graph.build", fromlist=["NODES"]).NODES, "verdict", confirmed
    )
    graph = build_graph(InMemorySaver(serde=checkpoint_serde()))
    rec, paused = await run(graph, "T-4b", {"ticket": demo_ticket("4")})
    assert "layer3" in rec.stages("done")
    state = await state_of(graph, "T-4b")
    assert state["linear_issue"] == "PAY-STUB"
    assert paused["linear_issue"] == "PAY-STUB"


async def test_failed_node_emits_failed_stage(monkeypatch):
    async def boom(state):
        raise RuntimeError("model timed out")

    monkeypatch.setitem(__import__("app.graph.build", fromlist=["NODES"]).NODES, "requests", boom)
    monkeypatch.setitem(__import__("app.graph.build", fromlist=["RETRY"]).RETRY, "requests", None)
    graph = build_graph(InMemorySaver(serde=checkpoint_serde()))
    rec = Recorder()
    with pytest.raises(RuntimeError):
        await run_graph(graph, {"ticket": demo_ticket("2")}, "T-err", rec)
    assert "requests" in rec.stages("failed")
    assert any(e.kind == "error" for e in rec.events)
