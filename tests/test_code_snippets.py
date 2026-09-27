"""Engineering snippets must come from checked code evidence and observed tool output."""

import json
from pathlib import Path

from app.code_snippets import extract_snippets, select_snippets, snippets_from_events
from app.events import ModelOutputEvent, StoredEvent, TerminalOut, ToolCallEvent
from app.models import Evidence, Findings, ToolRecord
from app.nodes.findings import check_evidence

FIXTURE = Path(__file__).resolve().parents[1] / "web/fixtures/payment-investigation.json"


def captured_code_run() -> tuple[Findings, list[ToolRecord]]:
    events = [
        StoredEvent.model_validate(item) for item in json.loads(FIXTURE.read_text())["events"]
    ]
    found = next(
        Findings.model_validate(item.event.data)
        for item in events
        if isinstance(item.event, ModelOutputEvent)
        and item.event.stage == "codebase_analyst"
        and item.event.name == "Findings"
    )
    calls = []
    for item in events:
        event = item.event
        if (
            isinstance(event, ToolCallEvent)
            and event.stage == "codebase_analyst"
            and event.status == "ok"
            and isinstance(event.output, TerminalOut)
        ):
            calls.append(
                ToolRecord(
                    call_id=event.call_id,
                    tool=event.tool,
                    args=event.args,
                    output=event.raw_output or event.output.output,
                )
            )
    return found, calls


def test_captured_payment_diff_is_a_source_backed_engineering_snippet():
    found, calls = captured_code_run()
    snippets = extract_snippets(found, calls)
    selected = select_snippets(
        "src/payment/charge.js:89", [found.model_copy(update={"code_snippets": snippets})]
    )
    assert selected
    snippet = selected[0]
    assert snippet.render == "diff"
    assert snippet.file == "src/payment/charge.js"
    assert snippet.call_id == "c1"
    assert "+    if (currentPeriod >= expiryPeriod) {" in snippet.content
    assert "-    if ((currentYear * 12 + currentMonth) >" in snippet.content
    assert "src/payment/index.js" not in snippet.content
    assert snippet.content in calls[0].output


def test_checked_findings_fill_snippets_from_calls_and_discard_model_supplied_excerpt():
    found, calls = captured_code_run()
    invented = found.model_copy(
        update={
            "code_snippets": [
                {
                    "render": "code",
                    "file": "src/payment/charge.js",
                    "start_line": 89,
                    "end_line": 89,
                    "language": "javascript",
                    "content": "invented code",
                    "call_id": "c2",
                }
            ]
        }
    )
    checked = check_evidence(invented, calls)
    assert checked.code_snippets
    assert all("invented code" not in item.content for item in checked.code_snippets)
    assert checked.code_snippets[0].content in calls[0].output


def test_snippet_requires_checked_code_reference_and_successful_observed_output():
    found, calls = captured_code_run()
    uncited = found.model_copy(update={"evidence": []})
    assert extract_snippets(uncited, calls) == []
    wrong = found.model_copy(
        update={
            "evidence": [
                Evidence(
                    source="code",
                    ref="src/other/file.js:89",
                    observation="unsupported",
                    call_id="c2",
                )
            ]
        }
    )
    assert extract_snippets(wrong, calls) == []
    assert extract_snippets(found, [call.model_copy(update={"ok": False}) for call in calls]) == []


def test_plain_source_excerpt_keeps_actual_lines_and_location():
    found = Findings(
        agent="codebase_analyst",
        hypothesis="Comparison is wrong",
        confidence=0.8,
        evidence=[
            Evidence(
                source="code",
                ref="src/payment/charge.js:88",
                observation="comparison",
                call_id="c1",
            )
        ],
    )
    call = ToolRecord(
        call_id="c1",
        tool="bash",
        args={"command": "sed -n '86,90p' src/payment/charge.js"},
        output=(
            "const currentPeriod = now;\nconst expiryPeriod = expiry;\n"
            "if (currentPeriod >= expiryPeriod) {\n  reject();\n}\n"
        ),
    )
    snippet = extract_snippets(found, [call])[0]
    assert snippet.render == "code"
    assert snippet.start_line == 86
    assert snippet.content.startswith("const currentPeriod = now;")
    assert "reject();" in snippet.content
    assert snippet.content in call.output


def test_historical_run_recovers_the_snippet_without_mutating_stored_events():
    events = [
        StoredEvent.model_validate(item) for item in json.loads(FIXTURE.read_text())["events"]
    ]
    original = events[-1].model_dump_json()
    snippets = snippets_from_events("src/payment/charge.js:88", events)
    assert snippets and snippets[0].render == "diff"
    assert "+    if (currentPeriod >= expiryPeriod) {" in snippets[0].content
    assert events[-1].model_dump_json() == original
