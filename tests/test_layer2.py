"""Layer 2's rules, as code: error signatures, evidence checks, round 2's trigger and the
verdict's guardrails. No model, container or database."""

import re

import pytest

from app.models import Evidence, Findings, ToolRecord, Verdict
from app.nodes.duplicates import error_signature, quoted_messages
from app.nodes.findings import check_evidence, limit_hit
from app.nodes.round2 import round2_target
from app.nodes.verdict import apply_rules

SERVICES = {"payment", "quote", "checkout", "cart", "product-catalog"}
EXPIRED = "The credit card (ending 4242) expired on 9/2026."
AMEX = "Sorry, we cannot process amex credit cards. Only VISA or MasterCard is accepted."
TRACE = "4bf92f3577b34da6a3ce929d0e0e4736"
SHA = "b7d87ca7e1f0c2d3a4b5c6d7e8f9a0b1c2d3e4f5"

# --- error signatures -------------------------------------------------------------------------


def test_one_message_with_different_values_has_one_signature():
    assert error_signature(EXPIRED) == error_signature(
        "The credit card (ending 1881)  expired on 10/2026"
    )


def test_different_messages_have_different_signatures():
    assert error_signature(EXPIRED) != error_signature(AMEX)
    assert error_signature("Payment request failed. Invalid token.") != error_signature(EXPIRED)


def test_ids_and_hex_are_normalized():
    a = error_signature(f"order 3f2a9c1e-5b6d-4e7f-8a9b-0c1d2e3f4a5b failed, trace {TRACE}")
    b = error_signature(f"order 11111111-2222-3333-4444-555555555555 failed, trace {'a' * 32}")
    assert a == b


@pytest.mark.parametrize(
    "template",
    [
        "The credit card (ending ${lastFourDigits}) expired on ${month}/${year}.",
        "The credit card (ending %s) expired on %d/%d.",
        "The credit card (ending {0}) expired on {1}/{2}.",
    ],
)
def test_a_code_template_has_the_signature_of_what_it_produces(template):
    assert error_signature(template) == error_signature(EXPIRED)


def test_quoted_messages_come_from_the_ticket_text():
    body = f'They see "{EXPIRED}" at checkout, or “{AMEX}”. Also "ok".'
    assert quoted_messages(body) == [EXPIRED, AMEX]  # too short to be an error message: "ok"


# --- evidence checks --------------------------------------------------------------------------


def data_findings(*evidence: Evidence, error_text: str | None = None) -> Findings:
    return Findings(
        agent="data_analyst",
        hypothesis="h",
        evidence=list(evidence),
        confidence=0.9,
        error_text=error_text,
    )


def code_findings(*evidence: Evidence, error_text: str | None = None, rnd: int = 1) -> Findings:
    return Findings(
        agent="codebase_analyst",
        hypothesis="h",
        evidence=list(evidence),
        confidence=0.9,
        error_text=error_text,
        round=rnd,
    )


HOLMES_CALLS = [
    ToolRecord(
        call_id="t1",
        tool="find_error_traces",
        args={"service": "payment"},
        output=f"{TRACE} charge error: {EXPIRED}",
    ),
    ToolRecord(
        call_id="m1",
        tool="execute_prometheus_range_query",
        args={"query": "rate(x[5m])"},
        output="payment v1.4.0 0.2",
    ),
    ToolRecord(
        call_id="d1",
        tool="deploys",
        args={"since": "2026-09-26"},
        output="payment | v1.3.0 | v1.4.0",
    ),
]
CODEBOX_CALLS = [
    ToolRecord(
        call_id="c1",
        tool="bash",
        args={"command": 'lookup-error "expired on"'},
        output="src/payment/charge.js:89 payment: The credit card ...",
    ),
    ToolRecord(
        call_id="c2",
        tool="bash",
        args={"command": "git blame -L 86,90 src/payment/charge.js"},
        output=f"{SHA[:8]} (dev 2026-09-20) if (currentPeriod >= expiryPeriod)",
    ),
]


def test_evidence_must_point_at_a_call_that_happened():
    f = data_findings(
        Evidence(source="trace", ref=TRACE, observation="o", call_id="t1"),
        Evidence(source="log", ref="q", observation="made up", call_id="nope"),
    )
    assert [e.call_id for e in check_evidence(f, HOLMES_CALLS).evidence] == ["t1"]


def test_a_trace_id_must_appear_in_that_calls_output():
    f = data_findings(Evidence(source="trace", ref="f" * 32, observation="o", call_id="t1"))
    checked = check_evidence(f, HOLMES_CALLS)
    assert checked.evidence == [] and checked.confidence == 0.3


def test_successful_trace_search_can_support_a_wrong_amount():
    call = ToolRecord(
        call_id="q1",
        tool="find_traces",
        args={"service": "quote", "operation": "calculate-quote"},
        output=f"{TRACE} quote@v1.4.0 items=11 total=197.78; unrelated {EXPIRED}",
    )
    finding = data_findings(
        Evidence(source="trace", ref=TRACE, observation="17.98/item", call_id="q1")
    )
    assert check_evidence(finding, [call]).evidence == finding.evidence
    assert check_evidence(data_findings(error_text=EXPIRED), [call]).error_text is None


def test_evidence_must_come_from_a_matching_tool():
    f = data_findings(
        Evidence(source="metric", ref="rate(x[5m])", observation="o", call_id="m1"),
        Evidence(source="deploy", ref="payment v1.4.0", observation="o", call_id="d1"),
        Evidence(source="log", ref="expired", observation="o", call_id="m1"),  # a metric call
    )
    assert [e.source for e in check_evidence(f, HOLMES_CALLS).evidence] == ["metric", "deploy"]


def test_the_data_analyst_cannot_cite_code():
    """HolmesGPT guesses about code it never read; those claims are dropped."""
    f = data_findings(
        Evidence(source="code", ref="charge.js:89", observation="likely >=", call_id="t1"),
        Evidence(source="trace", ref=TRACE, observation="o", call_id="t1"),
    )
    assert [e.source for e in check_evidence(f, HOLMES_CALLS).evidence] == ["trace"]


def test_code_and_commits_must_be_in_what_the_command_showed():
    f = code_findings(
        Evidence(source="code", ref="src/payment/charge.js:89", observation="o", call_id="c1"),
        Evidence(source="git", ref=SHA[:8], observation="o", call_id="c2"),
        Evidence(source="git", ref="deadbeef", observation="invented", call_id="c2"),
        Evidence(source="code", ref="src/quote/app/routes.php:40", observation="o", call_id="c1"),
        Evidence(source="trace", ref=TRACE, observation="no telemetry here", call_id="c1"),
    )
    kept = check_evidence(f, CODEBOX_CALLS).evidence
    assert [(e.source, e.ref) for e in kept] == [
        ("code", "src/payment/charge.js:89"),
        ("git", SHA[:8]),
    ]


def test_a_failed_call_supports_nothing():
    failed = ToolRecord(call_id="t9", tool="find_error_traces", output=f"{TRACE} ...", ok=False)
    f = data_findings(Evidence(source="trace", ref=TRACE, observation="o", call_id="t9"))
    assert check_evidence(f, [failed]).evidence == []


def test_git_evidence_is_a_commit():
    f = code_findings(
        Evidence(source="git", ref="v1.3.0:src/payment/charge.js", observation="o", call_id="c2")
    )
    calls = [
        ToolRecord(
            call_id="c2",
            tool="bash",
            args={"command": "git show v1.3.0:src/payment/charge.js"},
            output="x",
        )
    ]
    assert check_evidence(f, calls).evidence == []


def test_the_data_analysts_error_is_the_shops_not_a_tools():
    """A query's own error (here OpenSearch's) is not the error the customer's requests hit."""
    tool_error = "OpenSearch error: illegal_argument_exception Text fields are not optimised"
    calls = [
        *HOLMES_CALLS,
        ToolRecord(call_id="l1", tool="search_logs", output=tool_error, ok=False),
        ToolRecord(call_id="m2", tool="execute_prometheus_range_query", output=f"note {AMEX}"),
    ]
    assert check_evidence(data_findings(error_text=tool_error), calls).error_text is None
    assert check_evidence(data_findings(error_text=AMEX), calls).error_text is None  # a metric
    assert check_evidence(data_findings(error_text=EXPIRED), calls).error_text == EXPIRED


def test_an_error_text_nobody_saw_is_dropped():
    seen = data_findings(error_text="The credit card (ending 1111) expired on 9/2026")
    assert check_evidence(seen, HOLMES_CALLS).error_text
    assert check_evidence(data_findings(error_text=AMEX), HOLMES_CALLS).error_text is None


def test_a_run_that_hits_its_limit_is_not_a_guess():
    f = limit_hit("data_analyst", "timed out after 90 s")
    assert f.completed is False and f.evidence == [] and f.confidence == 0.0
    assert "timed out after 90 s" in f.hypothesis


# --- round 2 ----------------------------------------------------------------------------------


def test_round2_checks_the_data_analysts_exact_error():
    findings = [data_findings(error_text=EXPIRED), code_findings()]
    assert round2_target(findings) == EXPIRED


def test_no_round2_without_an_exact_error():
    assert round2_target([data_findings(), code_findings()]) is None


def test_no_round2_when_the_code_was_already_located():
    located = code_findings(
        Evidence(source="code", ref="src/payment/charge.js:89", observation="o", call_id="c1"),
        error_text="The credit card (ending 0000) expired on 1/2027.",
    )
    assert round2_target([data_findings(error_text=EXPIRED), located]) is None


def test_round2_runs_once():
    done = code_findings(rnd=2)
    assert round2_target([data_findings(error_text=EXPIRED), code_findings(), done]) is None


# --- verdict rules ----------------------------------------------------------------------------


def verdict(kind: str, **kw) -> Verdict:
    base = dict(
        kind=kind,
        root_cause="rc",
        owning_service="payment",
        confidence=0.9,
        customer_reply="We found it.",
    )
    return Verdict(**{**base, **kw})


TRACE_EV = Evidence(source="trace", ref=TRACE, observation="o", call_id="t1")
DEPLOY_EV = Evidence(source="deploy", ref="payment v1.4.0", observation="o", call_id="d1")
FLAG_EV = Evidence(source="flag", ref="paymentFailure 25%", observation="o", call_id="f1")
METRIC_EV = Evidence(source="metric", ref="rate(x[5m])", observation="o", call_id="m1")
CODE_EV = Evidence(source="code", ref="src/payment/charge.js:89", observation="o", call_id="c1")
GIT_EV = Evidence(source="git", ref=SHA[:8], observation="o", call_id="c2")


def test_a_supported_bug_stands():
    findings = [data_findings(TRACE_EV, DEPLOY_EV), code_findings(CODE_EV, GIT_EV)]
    v = apply_rules(
        verdict("confirmed_bug", file_line="src/payment/charge.js:89", commit=SHA),
        findings,
        SERVICES,
    )
    assert v.kind == "confirmed_bug" and v.file_line == "src/payment/charge.js:89"
    assert v.commit == SHA


def test_one_source_is_not_enough():
    v = apply_rules(verdict("config_incident"), [data_findings(FLAG_EV)], SERVICES)
    assert v.kind == "inconclusive" and v.confidence <= 0.5
    assert "two independent sources" in (v.engineering_summary or "")


def test_a_bug_needs_the_file_and_commit_the_code_analyst_saw():
    findings = [data_findings(TRACE_EV, DEPLOY_EV), code_findings(CODE_EV, GIT_EV)]
    unseen = apply_rules(
        verdict("confirmed_bug", file_line="src/payment/index.js:20", commit=SHA),
        findings,
        SERVICES,
    )
    assert unseen.kind == "inconclusive" and unseen.file_line is None
    no_commit = apply_rules(
        verdict("confirmed_bug", file_line="src/payment/charge.js:89"), findings, SERVICES
    )
    assert no_commit.kind == "inconclusive"


def test_a_config_incident_needs_a_flag_change():
    findings = [data_findings(TRACE_EV, METRIC_EV)]
    assert apply_rules(verdict("config_incident"), findings, SERVICES).kind == "inconclusive"
    findings = [data_findings(TRACE_EV, METRIC_EV, FLAG_EV)]
    assert apply_rules(verdict("config_incident"), findings, SERVICES).kind == "config_incident"


def test_a_false_positive_needs_the_code_that_does_it():
    assert (
        apply_rules(verdict("false_positive"), [data_findings(TRACE_EV, METRIC_EV)], SERVICES).kind
        == "inconclusive"
    )
    findings = [data_findings(TRACE_EV), code_findings(CODE_EV)]
    assert apply_rules(verdict("false_positive"), findings, SERVICES).kind == "false_positive"


def test_a_bug_needs_production_to_show_it():
    """Code and git alone come from one analyst; a bug needs the symptom in telemetry too."""
    findings = [data_findings(DEPLOY_EV), code_findings(CODE_EV, GIT_EV)]
    v = apply_rules(
        verdict("confirmed_bug", file_line="src/payment/charge.js:89", commit=SHA),
        findings,
        SERVICES,
    )
    assert v.kind == "inconclusive" and "production" in (v.engineering_summary or "")


def test_a_false_positive_needs_production_too():
    findings = [data_findings(), code_findings(CODE_EV, GIT_EV)]
    assert apply_rules(verdict("false_positive"), findings, SERVICES).kind == "inconclusive"


def test_a_config_incident_needs_the_symptom_as_well_as_the_flag():
    findings = [data_findings(FLAG_EV, DEPLOY_EV)]
    assert apply_rules(verdict("config_incident"), findings, SERVICES).kind == "inconclusive"


def test_round2s_judgment_of_the_production_error_decides():
    """Round 2 read the code path of the exact error production showed; round 1 may have
    followed something else (ticket 3: the Amex rule, not the expiry change)."""
    r1 = code_findings(CODE_EV, GIT_EV).model_copy(update={"intended": False})
    r2 = code_findings(CODE_EV, rnd=2).model_copy(update={"intended": True})
    found = [data_findings(TRACE_EV, DEPLOY_EV), r1, r2]
    bug = verdict("confirmed_bug", file_line="src/payment/charge.js:89", commit=SHA)
    v = apply_rules(bug, found, SERVICES)
    assert v.kind == "inconclusive" and "intended" in (v.engineering_summary or "")
    assert apply_rules(verdict("false_positive"), found, SERVICES).kind == "false_positive"


def test_a_false_positive_cant_stand_against_a_regression_in_the_code():
    r1 = code_findings(CODE_EV, GIT_EV).model_copy(update={"intended": False})
    v = apply_rules(verdict("false_positive"), [data_findings(TRACE_EV), r1], SERVICES)
    assert v.kind == "inconclusive"


def test_the_owner_must_be_a_known_service():
    findings = [data_findings(TRACE_EV), code_findings(CODE_EV)]
    v = apply_rules(verdict("false_positive", owning_service="billing"), findings, SERVICES)
    assert v.kind == "inconclusive"


def test_an_inconclusive_reply_promises_nothing():
    v = apply_rules(verdict("config_incident", customer_reply="Roll back the flag."), [], SERVICES)
    assert v.kind == "inconclusive" and "Roll back" not in v.customer_reply


@pytest.mark.parametrize("kind", ["inconclusive"])
def test_an_inconclusive_verdict_stays_inconclusive(kind):
    v = apply_rules(verdict(kind, confidence=0.9), [], SERVICES)
    assert v.kind == "inconclusive"


# --- HolmesGPT's output (tests/fixtures/holmes_ticket4.json: a real run, trimmed) --------------

import json  # noqa: E402

from app.analysts import holmes  # noqa: E402
from app.settings import ROOT  # noqa: E402

HOLMES_RESULT = json.loads((ROOT / "tests" / "fixtures" / "holmes_ticket4.json").read_text())


def test_holmes_calls_become_records_evidence_can_cite():
    calls = holmes.records(HOLMES_RESULT)
    assert [c.call_id for c in calls[:3]] == ["h1", "h2", "h3"]
    assert calls[0].tool == "deploys" and "payment | v1.3.0 | v1.4.0" in calls[0].output
    assert "psql" in calls[0].args["command"]
    traces = next(c for c in calls if c.tool == "find_error_traces")
    trace_id = re.search(r"\b[0-9a-f]{32}\b", traces.output).group(0)
    f = data_findings(
        Evidence(source="trace", ref=trace_id, observation="o", call_id=traces.call_id)
    )
    assert check_evidence(f, calls).evidence


def test_holmes_announces_each_call_as_it_starts():
    assert holmes.running_call("Running tool #12 find_error_traces: curl -s ...") == (
        12,
        "find_error_traces",
    )
    assert holmes.running_call("  Finished #12 in 1.36s, output length: 24") is None


def test_the_holmes_container_carries_no_secrets_on_its_command_line(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-secret")
    cmd = holmes.command("holmes-x", tmp_path)
    assert "sk-secret" not in " ".join(cmd)
    assert cmd[cmd.index("--add-host") + 1] == "host.docker.internal:host-gateway"
    assert "HISTORY_DB_URL" in cmd and not any(a.startswith("HISTORY_DB_URL=") for a in cmd)
    assert cmd[cmd.index("--network") + 1] == "opentelemetry-demo"
