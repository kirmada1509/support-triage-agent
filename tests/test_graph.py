"""The stub graph end to end: lanes, parallel analysts, interrupt and resume, events."""

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from app.events import ApprovalRequiredEvent, StageEvent, ToolCallEvent
from app.graph.build import build_graph, checkpoint_serde
from app.graph.stream import run_graph
from app.models import Verdict
from tests.conftest import demo_ticket

pytestmark = pytest.mark.usefixtures("front_stage_fakes")


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
    assert {"duplicates", "brief", "data_analyst", "codebase_analyst", "handoff", "verdict"} <= set(
        done
    )
    assert done.index("handoff") > max(done.index("data_analyst"), done.index("codebase_analyst"))
    assert not {"code_followup", "data_followup"} & set(done)  # nobody asked anything
    assert any(isinstance(e, ToolCallEvent) and e.stage == "codebase_analyst" for e in rec.events)
    state = await state_of(graph, "T-4")
    assert {f.agent for f in state["findings"]} == {"data_analyst", "codebase_analyst"}
    assert "revenue blocking" in paused["reasons"]

    await run(graph, "T-4", Command(resume={"approved": True, "edited_reply": "Edited."}))
    assert (await state_of(graph, "T-4"))["reply"] == "Edited."


EXPIRED = "The credit card (ending 4242) expired on 9/2026."


async def test_the_analysts_ask_each_other_before_the_verdict(monkeypatch):
    """Ticket 4's shape: production's error goes to the code, and the code asks production a
    question back. Each answer comes back to handoff, which has nothing left, then the verdict."""
    from app.analysts import AnalystRun
    from app.models import Findings, ToolRecord
    from app.nodes import data_analyst, findings

    async def convert(agent, answer, calls, round=1, symptom=""):
        said = {
            ("data_analyst", 1): {"error_text": EXPIRED},
            ("codebase_analyst", 2): {"request": "Are only this month's cards declined?"},
        }.get((agent, round), {})
        return Findings(
            agent=agent, hypothesis="h", evidence=[], confidence=0.5, round=round, **said
        )

    async def ask(question, on_call):  # the error is only kept if a trace call showed it
        trace = ToolRecord(call_id="h1", tool="find_error_traces", output=f"abc {EXPIRED}")
        return AnalystRun(answer="(fake)", calls=[trace])

    monkeypatch.setattr(findings, "convert", convert)
    monkeypatch.setattr(data_analyst, "ask", ask)
    graph = build_graph(InMemorySaver(serde=checkpoint_serde()))
    rec, _ = await run(graph, "T-4h", {"ticket": demo_ticket("4")})
    done = rec.stages("done")
    after = done[max(done.index("data_analyst"), done.index("codebase_analyst")) + 1 :]
    assert after[:6] == [
        "handoff",
        "code_followup",
        "handoff",
        "data_followup",
        "handoff",
        "verdict",
    ]
    assert any(isinstance(e, ToolCallEvent) and e.stage == "data_followup" for e in rec.events)
    state = await state_of(graph, "T-4h")
    assert [(h.to_agent, h.reason) for h in state["handoffs"]] == [
        ("codebase_analyst", "error_text"),
        ("data_analyst", "request"),
    ]
    assert [(f.agent, f.round) for f in state["findings"]][-2:] == [
        ("codebase_analyst", 2),
        ("data_analyst", 3),
    ]


async def test_analysts_that_keep_asking_stop_at_the_cap(monkeypatch):
    from itertools import count

    from app.models import Findings
    from app.nodes import findings
    from app.nodes.handoff import MAX_HANDOFFS

    n = count()

    async def convert(agent, answer, calls, round=1, symptom=""):
        return Findings(
            agent=agent,
            hypothesis="h",
            evidence=[],
            confidence=0.5,
            round=round,
            request=f"question {next(n)}?",
        )

    monkeypatch.setattr(findings, "convert", convert)
    graph = build_graph(InMemorySaver(serde=checkpoint_serde()))
    rec, _ = await run(graph, "T-4c", {"ticket": demo_ticket("4")})
    done = rec.stages("done")
    assert done.count("handoff") == MAX_HANDOFFS + 1 and "verdict" in done
    assert len((await state_of(graph, "T-4c"))["handoffs"]) == MAX_HANDOFFS


async def test_confirmed_bug_goes_to_layer3(monkeypatch):
    from app.integrations.linear import Issue
    from app.nodes import layer3
    from app.settings import settings

    async def no_receipt(*args):
        return None

    async def created(*args):
        return Issue("PAY-42", "https://linear.app/demo/issue/PAY-42")

    monkeypatch.setattr(settings, "linear_api_key", "test-key")
    monkeypatch.setattr(layer3.db, "delivery_receipt", no_receipt)
    monkeypatch.setattr(layer3.linear, "create_issue", created)

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
    assert state["linear_issue"] == "PAY-42"
    assert paused["linear_issue"] == "PAY-42"


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
