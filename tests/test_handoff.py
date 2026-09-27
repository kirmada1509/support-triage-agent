"""The analysts' two-way handoff, as code: who asks whom what between rounds, and when it stops.
No model, container or database."""

import pytest

from app.models import Evidence, Findings, Handoff
from app.nodes.findings import request_in
from app.nodes.handoff import MAX_HANDOFFS, next_handoff, origin, shared_findings

EXPIRED = "The credit card (ending 4242) expired on 9/2026."
SHA = "b7d87ca7e1f0c2d3a4b5c6d7e8f9a0b1c2d3e4f5"
TRACE_EV = Evidence(source="trace", ref="4bf92f35", observation="expired", call_id="h2")
DEPLOY_EV = Evidence(source="deploy", ref="checkout v1.4.0", observation="o", call_id="h1")
CODE_EV = Evidence(
    source="code", ref="src/checkout/main.go:544", observation="returns early", call_id="c3"
)
GIT_EV = Evidence(source="git", ref=SHA[:8], observation="chore: tidy up", call_id="c4")


def data(*evidence, error_text=None, request=None, rnd=1, completed=True) -> Findings:
    return Findings(
        agent="data_analyst",
        hypothesis="payment v1.4.0 declines cards",
        evidence=list(evidence),
        confidence=0.8,
        error_text=error_text,
        request=request,
        round=rnd,
        completed=completed,
    )


def code(*evidence, intended=None, request=None, rnd=1, error_text=None, completed=True):
    return Findings(
        agent="codebase_analyst",
        hypothesis="non-USD orders return before EmptyCart",
        evidence=list(evidence),
        confidence=0.7,
        intended=intended,
        request=request,
        round=rnd,
        error_text=error_text,
        completed=completed,
    )


def asked(*pairs) -> list[Handoff]:
    """Handoffs already made, as (to_agent, question)."""
    other = {"data_analyst": "codebase_analyst", "codebase_analyst": "data_analyst"}
    return [
        Handoff(round=n, from_agent=other[to], to_agent=to, question=q, reason="request")
        for n, (to, q) in enumerate(pairs, 2)
    ]


# --- data -> code: the exact error production showed ------------------------------------------


def test_the_data_analysts_exact_error_goes_to_the_code():
    h = next_handoff([data(TRACE_EV, error_text=EXPIRED), code()], [])
    assert h.from_agent == "data_analyst" and h.to_agent == "codebase_analyst"
    assert h.reason == "error_text" and EXPIRED in h.question and h.round == 2


def test_an_error_the_code_already_located_is_not_sent_again():
    located = code(CODE_EV, error_text="The credit card (ending 0000) expired on 1/2027.")
    assert next_handoff([data(TRACE_EV, error_text=EXPIRED), located], []) is None


def test_the_same_error_is_sent_once():
    first = next_handoff([data(TRACE_EV, error_text=EXPIRED), code()], [])
    answered = code(rnd=2)  # the codebase analyst looked, and still found nothing
    assert next_handoff([data(TRACE_EV, error_text=EXPIRED), code(), answered], [first]) is None


# --- code -> data: what the code implies production should show -------------------------------


def test_an_explicit_request_goes_to_the_other_analyst():
    ask = "Do EUR and CAD orders since 10:00 have an EmptyCart span?"
    h = next_handoff([data(DEPLOY_EV), code(CODE_EV, request=ask)], [])
    assert (h.from_agent, h.to_agent, h.reason) == ("codebase_analyst", "data_analyst", "request")
    assert h.question == ask


def test_a_regression_production_hasnt_shown_is_checked_in_the_data():
    """The safety net for a model that forgets to ask: the code says regression, the data shows
    nothing of the symptom (a deploy record alone doesn't count)."""
    h = next_handoff([data(DEPLOY_EV), code(CODE_EV, GIT_EV, intended=False)], [])
    assert h.to_agent == "data_analyst" and h.reason == "confirm_regression"
    assert "src/checkout/main.go:544" in h.question and "before" in h.question


def test_a_regression_production_already_shows_needs_no_check():
    assert next_handoff([data(TRACE_EV), code(CODE_EV, GIT_EV, intended=False)], []) is None


def test_intended_behaviour_needs_no_data_check():
    assert next_handoff([data(DEPLOY_EV), code(CODE_EV, intended=True)], []) is None


def test_a_regression_without_code_evidence_is_not_sent():
    assert next_handoff([data(DEPLOY_EV), code(intended=False)], []) is None


# --- back and forth ---------------------------------------------------------------------------


def test_data_to_code_then_code_to_data():
    """Ticket 4's shape: the error goes to the code, the code asks production a question back."""
    found = [data(TRACE_EV, error_text=EXPIRED), code()]
    first = next_handoff(found, [])
    ask = "Are only cards expiring this month declined?"
    found.append(code(CODE_EV, GIT_EV, intended=False, rnd=2, request=ask, error_text=EXPIRED))
    second = next_handoff(found, [first])
    assert (second.to_agent, second.question, second.round) == ("data_analyst", ask, 3)


def test_the_newest_request_goes_first():
    found = [data(DEPLOY_EV, request="Which tag?"), code(CODE_EV, request="old", rnd=1)]
    found.append(code(CODE_EV, request="Is the count 9 since the deploy?", rnd=2))
    assert next_handoff(found, []).question == "Is the count 9 since the deploy?"


def test_a_question_is_never_asked_twice():
    ask = "Do EUR orders have an EmptyCart span?"
    first = next_handoff([code(CODE_EV, request=ask)], [])
    again = [code(CODE_EV, request=ask), data(DEPLOY_EV, rnd=2), code(request=ask.upper(), rnd=3)]
    assert next_handoff(again, [first]) is None


def test_the_loop_stops_at_its_cap():
    done = asked(("data_analyst", "a"), ("codebase_analyst", "b"), ("data_analyst", "c"))
    assert len(done) == MAX_HANDOFFS
    assert next_handoff([code(CODE_EV, request="d", rnd=4)], done) is None


def test_each_analyst_answers_at_most_two_questions():
    done = asked(("data_analyst", "a"), ("data_analyst", "b"))
    assert next_handoff([code(CODE_EV, request="c", rnd=3)], done) is None
    back = next_handoff([code(CODE_EV, rnd=3), data(DEPLOY_EV, request="d", rnd=3)], done)
    assert back.to_agent == "codebase_analyst"


def test_an_analyst_that_ran_out_of_budget_on_a_question_isnt_asked_again():
    done = asked(("data_analyst", "a"))
    found = [data(rnd=2, completed=False), code(CODE_EV, request="b", rnd=2)]
    assert next_handoff(found, done) is None


def test_nothing_to_hand_over():
    assert next_handoff([data(TRACE_EV), code(CODE_EV)], []) is None
    assert next_handoff([], []) is None


# --- what the asked analyst sees ---------------------------------------------------------------


def test_the_asked_analyst_sees_the_askers_checked_findings():
    text = shared_findings(
        [data(TRACE_EV, error_text=EXPIRED), code(CODE_EV, GIT_EV)], "codebase_analyst"
    )
    assert "non-USD orders return before EmptyCart" in text
    assert "src/checkout/main.go:544" in text and SHA[:8] in text
    assert "4bf92f35" not in text  # only the asker's findings


def test_an_inconclusive_run_shares_nothing():
    assert shared_findings([data(completed=False)], "data_analyst") == ""


# --- the ASK line an analyst ends its answer with ----------------------------------------------


@pytest.mark.parametrize(
    ("answer", "agent", "question"),
    [
        (
            "Early return at main.go:544.\nASK DATA ANALYST: Do EUR orders have EmptyCart?",
            "codebase_analyst",
            "Do EUR orders have EmptyCart?",
        ),
        (
            "Errors since 10:05.\n**Ask codebase analyst:** which line produces this?",
            "data_analyst",
            "which line produces this?",
        ),
        ("ASK DATA ANALYST: none", "codebase_analyst", None),
        ("No question here.", "codebase_analyst", None),
        # an analyst can only ask the other one
        ("ASK CODEBASE ANALYST: anything?", "codebase_analyst", None),
    ],
)
def test_an_analysts_question_is_read_from_its_answer(answer, agent, question):
    assert request_in(answer, agent) == question


def test_a_request_is_capped():
    assert len(request_in("ASK DATA ANALYST: " + "x" * 2000, "codebase_analyst")) == 500


# --- only production errors about the ticket's service go to the code -------------------------

TEMPLATES = [
    ("payment", "The credit card (ending ${lastFourDigits}) expired on ${month}/${year}."),
    ("checkout", "failed to charge card: %+v"),
    ("product-catalog", "Product Not Found: %s"),
]


def test_an_errors_origin_is_the_most_specific_template_it_contains():
    wrapped = f"failed to charge card: could not charge the card: rpc error: desc = {EXPIRED}"
    assert origin(wrapped, TEMPLATES) == "payment"
    assert origin("failed to charge card: timeout", TEMPLATES) == "checkout"
    assert origin("something the index doesn't know", TEMPLATES) is None


def test_another_services_error_is_not_sent_to_the_code():
    """Live ticket 8 (a checkout cart bug, payments fine): payment's expiry bug was live in the
    same window, the data analyst quoted another shopper's card error, and two follow-ups chased
    it. An error whose code is in another service stays with the data analyst."""
    found = [data(TRACE_EV, error_text=EXPIRED), code()]
    assert next_handoff(found, [], about=lambda text: False) is None
    assert next_handoff(found, [], about=lambda text: True).reason == "error_text"


async def test_the_handoff_node_checks_where_an_error_comes_from(monkeypatch):
    from app.models import Brief
    from app.nodes import handoff

    async def templates(version):
        return TEMPLATES

    monkeypatch.setattr(handoff, "error_templates", templates)
    monkeypatch.setattr(handoff, "emit", lambda e: None)
    found = [data(TRACE_EV, error_text=EXPIRED), code()]

    def brief(service):
        return Brief(text="t", suspected_service=service, deployed_version="v1.4.0")

    assert (await handoff.run({"brief": brief("checkout"), "findings": found}))["handoff"] is None
    out = await handoff.run({"brief": brief("payment"), "findings": found})
    assert out["handoff"].reason == "error_text"
