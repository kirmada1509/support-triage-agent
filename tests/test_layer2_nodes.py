"""Layer 2's nodes against TicketState, with the model, the analysts' containers, retrieval and
Postgres replaced by fakes. The live runs are `make test-layer2`."""

from datetime import timedelta

import pytest

from app.analysts import AnalystLimit, AnalystRun
from app.events import ModelOutputEvent, ToolCallEvent
from app.models import (
    Brief,
    Classification,
    ContextBundle,
    Deploy,
    DuplicateCheck,
    Enrichment,
    Evidence,
    Findings,
    Handoff,
    Retrieved,
    ToolRecord,
    Verdict,
)
from app.nodes import (
    brief,
    code_followup,
    codebase_analyst,
    data_analyst,
    data_followup,
    duplicates,
    findings,
    handoff,
    remember,
    verdict,
)
from tests.conftest import NOW, demo_ticket

EXPIRED = "The credit card (ending 4242) expired on 9/2026."
TRACE = "4bf92f3577b34da6a3ce929d0e0e4736"
SHA = "b7d87ca7e1f0c2d3a4b5c6d7e8f9a0b1c2d3e4f5"


@pytest.fixture
def events(monkeypatch):
    """Events a node emits, without a running graph."""
    seen = []
    for module in (
        brief,
        data_analyst,
        codebase_analyst,
        duplicates,
        handoff,
        code_followup,
        data_followup,
        verdict,
        remember,
    ):
        monkeypatch.setattr(module, "emit", seen.append, raising=False)
    return seen


def state(n: str = "4", **extra) -> dict:
    ticket = demo_ticket(n)
    base = {
        "ticket": ticket,
        "enrichment": Enrichment(
            identifiers={"user_ids": ["figma-shopper-03", "figma-shopper-11"]},
            window_start=NOW - timedelta(hours=3),
            window_end=NOW,
            window_basis="this morning",
            symptom="card rejected as expired",
            likely_services=["payment"],
            relevant_changes=["deploy:1"],
        ),
        "classification": Classification(
            ticket_type="tech_issue",
            ticket_type_confidence=0.9,
            service="payment",
            severity=2,
            revenue_blocking=True,
            revenue_blocking_confidence=0.9,
        ),
        "context": ContextBundle(
            services={"payment": "charges cards"},
            deploys=[
                Deploy(
                    id=1,
                    service="payment",
                    version="v1.4.0",
                    previous_version="v1.3.0",
                    deployed_at=NOW - timedelta(minutes=50),
                    commit_titles=["refactor: simplify card expiry comparison"],
                )
            ],
        ),
        "retrieved": [
            Retrieved(
                kind="ticket",
                id="PT-042",
                title="Card declined after deploy",
                text="Root cause: a comparison changed in the payment service.",
                status="resolved",
                score=0.8,
            ),
            Retrieved(kind="help_section", id="payments", title="Cards", text="Visa", score=0.9),
        ],
    }
    return {**base, **extra}


def the_brief(**kw) -> Brief:
    base = dict(
        text="Customer says: expired",
        suspected_service="payment",
        deployed_version="v1.4.0",
        previous_version="v1.3.0",
    )
    return Brief(**{**base, **kw})


# --- brief ------------------------------------------------------------------------------------


async def test_the_brief_holds_the_case_and_versions(events):
    out = await brief.run(state())
    b = out["brief"]
    assert (b.suspected_service, b.deployed_version, b.previous_version) == (
        "payment",
        "v1.4.0",
        "v1.3.0",
    )
    assert "<ticket>" in b.text and "figma-shopper-03" in b.text
    assert "refactor: simplify card expiry comparison" in b.text
    assert b.past_investigations == [
        "PT-042: Root cause: a comparison changed in the payment service."
    ]


async def test_without_a_recent_deploy_the_brief_uses_whats_running(events, monkeypatch):
    monkeypatch.setattr(brief, "running_version", lambda service: "v1.3.0")
    out = await brief.run(state(context=ContextBundle(services={"payment": "charges cards"})))
    assert (out["brief"].deployed_version, out["brief"].previous_version) == ("v1.3.0", None)


# --- data analyst -----------------------------------------------------------------------------

HOLMES_CALLS = [
    ToolRecord(
        call_id="h1", tool="deploys", args={"since": "x"}, output="payment | v1.3.0 | v1.4.0"
    ),
    ToolRecord(call_id="h2", tool="find_error_traces", args={}, output=f"{TRACE} {EXPIRED}"),
]


@pytest.fixture
def fake_findings(monkeypatch):
    """The findings conversion (a model call), returning what the analyst claimed."""
    claimed = {}

    async def convert(agent, answer, calls, round=1, symptom=""):
        claimed["symptoms"] = [*claimed.get("symptoms", []), symptom]
        return claimed[agent].model_copy(update={"round": round})

    monkeypatch.setattr(findings, "convert", convert)
    return claimed


async def test_the_data_analyst_streams_its_calls_and_keeps_checked_evidence(
    events, monkeypatch, fake_findings
):
    asked = {}

    async def ask(question, on_call):
        asked["question"] = question
        for c in HOLMES_CALLS:
            on_call(
                ToolCallEvent(
                    stage="data_analyst", call_id=c.call_id, tool=c.tool, status="running"
                )
            )
        return AnalystRun(answer="payment v1.4.0 fails", calls=HOLMES_CALLS, cost_usd=0.01)

    monkeypatch.setattr(data_analyst, "ask", ask)
    fake_findings["data_analyst"] = Findings(
        agent="data_analyst",
        hypothesis="expiry regression in payment v1.4.0",
        confidence=0.8,
        error_text=EXPIRED,
        evidence=[
            Evidence(source="trace", ref=TRACE, observation="o", call_id="h2"),
            Evidence(source="deploy", ref="payment v1.4.0", observation="o", call_id="h1"),
            Evidence(source="code", ref="charge.js:89", observation="guess", call_id="h2"),
        ],
    )
    out = await data_analyst.run(state(brief=the_brief()))
    (f,) = out["findings"]
    assert [e.source for e in f.evidence] == ["trace", "deploy"] and f.error_text == EXPIRED
    question = " ".join(asked["question"].split())
    assert the_brief().text in question and "Don't guess about code" in question
    calls = [e for e in events if isinstance(e, ToolCallEvent)]
    assert {(e.call_id, e.status) for e in calls} >= {("h1", "running"), ("h1", "ok")}
    assert any(isinstance(e, ModelOutputEvent) and e.cost_usd == 0.01 for e in events)


async def test_a_data_analyst_that_hits_its_budget_is_inconclusive(events, monkeypatch):
    async def ask(question, on_call):
        raise AnalystLimit("stopped at 16 tool calls (budget 15)")

    monkeypatch.setattr(data_analyst, "ask", ask)
    (f,) = (await data_analyst.run(state(brief=the_brief())))["findings"]
    assert f.completed is False and f.confidence == 0.0 and "budget 15" in f.hypothesis


def test_a_wrong_amount_question_starts_with_successful_quote_traces():
    prompt = data_analyst.question(
        state(
            "5",
            brief=the_brief(
                text="Bulk shipping amount doubled after quote deploy",
                suspected_service="quote",
            ),
        )
    )
    assert "find_traces" in prompt
    assert "quote/calculate-quote" in prompt
    assert "before and after" in prompt
    assert "payment errors" in prompt


# --- codebase analyst -------------------------------------------------------------------------

CODE_CALLS = [
    ToolRecord(
        call_id="c1",
        tool="bash",
        args={"command": 'lookup-error "expired on"'},
        output="src/payment/charge.js:89 payment: The credit card ...",
    ),
    ToolRecord(
        call_id="c2",
        tool="bash",
        args={"command": "git blame -L 89,89 src/payment/charge.js"},
        output=f"{SHA[:8]} (dev) if (currentPeriod >= expiryPeriod)",
    ),
]


async def test_the_codebase_analyst_gets_the_card_and_the_changes(
    events, monkeypatch, fake_findings
):
    seen = {}

    async def investigate(task, b, on_call, *, max_commands, timeout_s, **kw):
        seen.update(task=task, versions=(b.deployed_version, b.previous_version))
        return AnalystRun(answer="regression at charge.js:89", calls=CODE_CALLS, cost_usd=0.002)

    monkeypatch.setattr(codebase_analyst, "investigate", investigate)

    async def card(service, version):
        return "# payment\nCharges cards."

    monkeypatch.setattr(codebase_analyst, "service_card", card)
    monkeypatch.setattr(
        codebase_analyst,
        "change_summary",
        lambda s, a, b: "b7d87ca7 refactor: simplify card expiry",
    )
    fake_findings["codebase_analyst"] = Findings(
        agent="codebase_analyst",
        hypothesis="regression",
        confidence=0.9,
        evidence=[
            Evidence(source="code", ref="src/payment/charge.js:89", observation="o", call_id="c1"),
            Evidence(source="git", ref=SHA[:8], observation="o", call_id="c2"),
        ],
    )
    (f,) = (await codebase_analyst.run(state(brief=the_brief())))["findings"]
    assert [e.source for e in f.evidence] == ["code", "git"]
    assert "Charges cards." in seen["task"] and "simplify card expiry" in seen["task"]
    assert "src/payment/" in seen["task"] and seen["versions"] == ("v1.4.0", "v1.3.0")


async def test_a_codebase_analyst_out_of_time_is_inconclusive(events, monkeypatch):
    async def investigate(task, b, on_call, *, max_commands, timeout_s, **kw):
        raise AnalystLimit(f"timed out after {timeout_s} s")

    monkeypatch.setattr(codebase_analyst, "investigate", investigate)

    async def no_card(service, version):
        return None

    monkeypatch.setattr(codebase_analyst, "service_card", no_card)
    monkeypatch.setattr(codebase_analyst, "change_summary", lambda s, a, b: "")
    (f,) = (await codebase_analyst.run(state(brief=the_brief())))["findings"]
    assert f.completed is False and "timed out" in f.hypothesis


# --- follow-ups: one analyst answers the other's question -----------------------------------


def data_found(error_text: str | None = EXPIRED) -> Findings:
    return Findings(
        agent="data_analyst",
        hypothesis="payment v1.4.0 declines this month's cards",
        evidence=[Evidence(source="trace", ref=TRACE, observation="expired", call_id="h2")],
        confidence=0.8,
        error_text=error_text,
    )


def code_found() -> Findings:
    return Findings(
        agent="codebase_analyst",
        hypothesis="the expiry check moved from > to >=",
        evidence=[
            Evidence(source="code", ref="src/payment/charge.js:88", observation="o", call_id="c1")
        ],
        confidence=0.7,
        intended=False,
    )


def asking(to: str, question: str, reason: str = "request", rnd: int = 2) -> Handoff:
    other = {"data_analyst": "codebase_analyst", "codebase_analyst": "data_analyst"}
    return Handoff(round=rnd, from_agent=other[to], to_agent=to, question=question, reason=reason)


async def test_the_codebase_analyst_answers_the_data_analysts_error(
    events, monkeypatch, fake_findings
):
    seen = {}

    async def investigate(task, b, on_call, *, max_commands, timeout_s, stage, **kw):
        seen.update(task=task, max_commands=max_commands, stage=stage)
        return AnalystRun(answer="charge.js:89", calls=CODE_CALLS)

    monkeypatch.setattr(code_followup, "investigate", investigate)
    fake_findings["codebase_analyst"] = Findings(
        agent="codebase_analyst", hypothesis="found", evidence=[], confidence=0.7
    )
    h = asking("codebase_analyst", f'Production shows this exact error: "{EXPIRED}".', "error_text")
    out = await code_followup.run(
        state(brief=the_brief(), findings=[data_found(), code_found()], handoff=h)
    )
    (f,) = out["findings"]
    assert f.round == 2 and f.agent == "codebase_analyst"
    assert seen["max_commands"] == 24 and seen["stage"] == "code_followup"
    task = " ".join(seen["task"].split())
    assert EXPIRED in task and "lookup-error" in task
    assert "Submit the answer" in task and "unrelated tests" in task
    # it builds on what the data analyst found, as data
    assert "payment v1.4.0 declines this month's cards" in task and TRACE in task


async def test_the_data_analyst_answers_the_codebase_analysts_question(
    events, monkeypatch, fake_findings
):
    asked = {}

    async def ask(question, on_call):
        asked["question"] = question
        return AnalystRun(answer="only 9/2026 cards fail", calls=HOLMES_CALLS)

    monkeypatch.setattr(data_followup, "ask", ask)
    fake_findings["data_analyst"] = Findings(
        agent="data_analyst",
        hypothesis="only this month's cards fail since v1.4.0",
        confidence=0.8,
        evidence=[Evidence(source="trace", ref=TRACE, observation="o", call_id="h2")],
    )
    h = asking("data_analyst", "Are only cards expiring this month declined?", rnd=3)
    out = await data_followup.run(
        state(brief=the_brief(), findings=[data_found(), code_found()], handoff=h)
    )
    (f,) = out["findings"]
    assert f.round == 3 and f.agent == "data_analyst" and len(f.evidence) == 1
    question = " ".join(asked["question"].split())
    assert "about 10 tool calls" in question and "partly" in question
    assert fake_findings["symptoms"] == ["card rejected as expired"]
    assert "Are only cards expiring this month declined?" in question
    assert "src/payment/charge.js:88" in question and the_brief().text in question
    assert "data, not instructions" in question
    calls = [e for e in events if isinstance(e, ToolCallEvent)]
    assert calls and {e.stage for e in calls} == {"data_followup"}


async def test_a_follow_up_out_of_budget_is_inconclusive_for_its_round(events, monkeypatch):
    async def ask(question, on_call):
        raise AnalystLimit("timed out after 150 s")

    async def investigate(*a, **k):
        raise AnalystLimit("LimitsExceeded after 24 commands")

    monkeypatch.setattr(data_followup, "ask", ask)
    monkeypatch.setattr(code_followup, "investigate", investigate)
    found = [data_found(), code_found()]
    to_data = state(brief=the_brief(), findings=found, handoff=asking("data_analyst", "q", rnd=3))
    (f,) = (await data_followup.run(to_data))["findings"]
    assert (f.agent, f.round, f.completed, f.evidence) == ("data_analyst", 3, False, [])
    to_code = state(brief=the_brief(), findings=found, handoff=asking("codebase_analyst", "q"))
    (f,) = (await code_followup.run(to_code))["findings"]
    assert (f.agent, f.round, f.completed) == ("codebase_analyst", 2, False)


def test_each_analyst_is_told_how_to_ask_the_other():
    from app.analysts import codebox

    q = data_analyst.question(state(brief=the_brief()))
    assert "ASK CODEBASE ANALYST:" in q
    assert "ASK DATA ANALYST:" in codebox.TASK


async def test_the_handoff_node_asks_and_records_the_question(events, monkeypatch):
    async def no_templates(version):
        return []

    monkeypatch.setattr(handoff, "error_templates", no_templates)
    out = await handoff.run(state(brief=the_brief(), findings=[data_found(), code_found()]))
    h = out["handoff"]
    assert h.to_agent == "codebase_analyst" and out["handoffs"] == [h]
    assert any(isinstance(e, ModelOutputEvent) and e.name == "Handoff" for e in events)
    done = state(brief=the_brief(), findings=[data_found(None), code_found()], handoffs=[h])
    done["findings"][0].evidence.clear()  # no symptom: the code's regression goes to the data
    again = await handoff.run(done)
    assert again["handoff"].to_agent == "data_analyst"


# --- verdict ----------------------------------------------------------------------------------


async def test_the_verdict_is_checked_before_it_leaves(events, monkeypatch):
    async def call(role, output_type, prompt):
        assert role == "verdict" and "<findings>" in prompt
        return (
            Verdict(
                kind="confirmed_bug",
                root_cause="expiry compare",
                owning_service="payment",
                confidence=0.9,
                customer_reply="We found a bug.",
                file_line="src/payment/charge.js:89",
                commit="deadbeefcafe",  # no analyst saw it
            ),
            "deepseek-v4-pro",
        )

    monkeypatch.setattr(verdict, "call", call)
    found = [
        Findings(
            agent="data_analyst",
            hypothesis="h",
            confidence=0.8,
            evidence=[Evidence(source="trace", ref=TRACE, observation="o", call_id="h2")],
        ),
        Findings(
            agent="codebase_analyst",
            hypothesis="h",
            confidence=0.8,
            evidence=[
                Evidence(source="code", ref="src/payment/charge.js:89", observation="o"),
                Evidence(source="git", ref=SHA[:8], observation="o"),
            ],
        ),
    ]
    out = await verdict.run(state(brief=the_brief(), findings=found))
    assert out["verdict"].kind == "inconclusive" and out["verdict"].commit is None
    assert out["reply"] == verdict.HOLDING_REPLY
    assert any(isinstance(e, ModelOutputEvent) and e.name == "Verdict" for e in events)


async def test_both_analysts_out_of_budget_skip_the_model(events, monkeypatch):
    async def call(*a):
        raise AssertionError("no model call without evidence")

    monkeypatch.setattr(verdict, "call", call)
    found = [findings.limit_hit("data_analyst", "t"), findings.limit_hit("codebase_analyst", "t")]
    out = await verdict.run(state(brief=the_brief(), findings=found))
    assert out["verdict"].kind == "inconclusive" and out["verdict"].confidence == 0.0


# --- duplicates -------------------------------------------------------------------------------

OPEN_T4 = Retrieved(
    kind="ticket",
    id="T-4",
    title="Shoppers say their card is rejected as expired",
    text="Cards expiring this month are rejected after payment v1.4.0.",
    status="open",
    score=0.9,
)


@pytest.fixture
def no_open_work(monkeypatch):
    async def none(*a, **k):
        return []

    monkeypatch.setattr(duplicates, "open_investigations", none)
    monkeypatch.setattr(duplicates, "open_tickets", none)


async def test_an_exact_signature_links_without_a_model(events, monkeypatch, no_open_work):
    async def investigations(service, version):
        return [
            duplicates.OpenIssue(
                ticket_id="T-4",
                linear_issue="PAY-12",
                error_signature=duplicates.error_signature(EXPIRED),
            )
        ]

    async def call(*a):
        raise AssertionError("an exact match needs no model")

    monkeypatch.setattr(duplicates, "open_investigations", investigations)
    monkeypatch.setattr(duplicates, "call", call)
    t = demo_ticket("4").model_copy(
        update={"body": 'They see "The credit card (ending 1111) expired on 9/2026." at checkout.'}
    )
    out = await duplicates.run(state(ticket=t))
    assert out["duplicate_of"] == "PAY-12"


@pytest.mark.parametrize(
    ("answer", "linked"),
    [
        (
            DuplicateCheck(
                new_problem="n",
                closest_problem="c",
                same_problem=True,
                ticket_id="T-4",
                reason="same",
            ),
            "T-4",
        ),
        (
            DuplicateCheck(
                new_problem="n",
                closest_problem="c",
                same_problem=True,
                ticket_id="T-99",
                reason="invented",
            ),
            None,
        ),
        (
            DuplicateCheck(
                new_problem="n",
                closest_problem="c",
                same_problem=False,
                ticket_id=None,
                reason="different",
            ),
            None,
        ),
    ],
)
async def test_an_open_ticket_is_linked_only_when_confirmed(
    events, monkeypatch, no_open_work, answer, linked
):
    async def tickets(query, service):
        return [OPEN_T4]

    async def call(role, output_type, prompt):
        assert "T-4" in prompt and "<ticket>" in prompt
        return answer, "deepseek-flash"

    monkeypatch.setattr(duplicates, "open_tickets", tickets)
    monkeypatch.setattr(duplicates, "call", call)
    out = await duplicates.run(state("7"))
    assert out["duplicate_of"] == linked


async def test_no_candidates_no_model_call(events, monkeypatch, no_open_work):
    async def call(*a):
        raise AssertionError("nothing to confirm")

    monkeypatch.setattr(duplicates, "call", call)
    assert (await duplicates.run(state("4")))["duplicate_of"] is None


# --- remember ---------------------------------------------------------------------------------


@pytest.fixture
def memory(monkeypatch):
    written = {"docs": [], "investigations": []}

    async def write_doc(doc):
        written["docs"].append(doc)

    async def add_investigation(**row):
        written["investigations"].append(row)

    monkeypatch.setattr(remember, "write_doc", write_doc)
    monkeypatch.setattr(remember, "add_investigation", add_investigation)
    return written


def confirmed(kind: str = "confirmed_bug") -> Verdict:
    return Verdict(
        kind=kind,
        root_cause="the expiry comparison became >=",
        owning_service="payment",
        confidence=0.9,
        customer_reply="Fixing it.",
        file_line="src/payment/charge.js:89",
        commit=SHA,
    )


async def test_a_confirmed_bug_is_remembered_as_open_work(events, memory):
    s = state(
        brief=the_brief(),
        verdict=confirmed(),
        linear_issue="PAY-12",
        findings=[data_found()],
        reply="Fixing it.",
    )
    await remember.run(s)
    (doc,) = memory["docs"]
    assert doc["id"] == "T-4" and doc["status"] == "open" and doc["linear_issue"] == "PAY-12"
    assert doc["verdict"] == "confirmed_bug" and doc["service"] == "payment"
    (inv,) = memory["investigations"]
    assert inv["status"] == "open" and inv["file_line"] == "src/payment/charge.js:89"
    assert inv["error_signature"] == duplicates.error_signature(EXPIRED)
    assert inv["version"] == "v1.4.0" and SHA[:8] in inv["root_cause"]


async def test_a_false_positive_is_resolved(events, memory):
    s = state("3", brief=the_brief(), verdict=confirmed("false_positive"), reply="Amex isn't")
    await remember.run(s)
    assert memory["docs"][0]["status"] == "resolved"
    assert memory["investigations"][0]["status"] == "resolved"


async def test_other_lanes_join_ticket_memory_only(events, memory):
    s = state("1", reply="Visa and Mastercard.")
    s["classification"] = s["classification"].model_copy(update={"ticket_type": "how_to"})
    await remember.run(s)
    assert memory["docs"][0]["status"] == "resolved" and memory["investigations"] == []


async def test_a_linked_duplicate_is_open_with_its_issue(events, memory):
    await remember.run(state("7", duplicate_of="PAY-12", reply="Linked."))
    doc = memory["docs"][0]
    assert doc["status"] == "open" and doc["linear_issue"] == "PAY-12"
    assert memory["investigations"] == []


async def test_every_analyst_budget_is_scaled_for_its_model(events, monkeypatch, fake_findings):
    from app import models_config

    monkeypatch.setattr(models_config, "time_budget", lambda role, seconds: seconds * 10)
    seen = {}

    async def investigate(task, b, on_call, *, max_commands, timeout_s, **kw):
        seen[kw.get("stage", "codebase_analyst")] = timeout_s
        raise AnalystLimit("stop")

    monkeypatch.setattr(codebase_analyst, "investigate", investigate)
    monkeypatch.setattr(codebase_analyst, "service_card", lambda *a: _none())
    monkeypatch.setattr(codebase_analyst, "change_summary", lambda *a: "")
    monkeypatch.setattr(code_followup, "investigate", investigate)
    await codebase_analyst.run(state(brief=the_brief()))
    h = asking("codebase_analyst", "q")
    await code_followup.run(state(brief=the_brief(), findings=[], handoff=h))
    assert seen == {"codebase_analyst": 1200, "code_followup": 900}

    budgets = {}

    async def holmes_ask(question, on_call, *, timeout_s, max_calls, **kw):
        budgets[kw.get("stage", "data_analyst")] = timeout_s
        raise AnalystLimit("stop")

    monkeypatch.setattr(data_analyst, "holmes_ask", holmes_ask)
    monkeypatch.setattr(data_followup, "holmes_ask", holmes_ask)
    for module in (data_analyst, data_followup):
        with pytest.raises(AnalystLimit):
            await module.ask("q", None)
    assert budgets == {"data_analyst": 2400, "data_followup": 1500}


async def _none():
    return None
