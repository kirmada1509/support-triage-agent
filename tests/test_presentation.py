"""The API can improve stored analyst output without changing its evidence payload."""

import json
from datetime import UTC, datetime
from pathlib import Path

from app.api.presentation import present_stored_event
from app.api.schemas import Pipeline, TicketDetail
from app.events import StoredEvent, TerminalOut, ToolCallEvent


def call(tool: str, command: str, output: str, stage: str = "data_analyst") -> StoredEvent:
    return StoredEvent(
        id=7,
        ticket_id="T-demo",
        ts=datetime.now(UTC),
        event=ToolCallEvent(
            stage=stage,
            call_id="c1",
            tool=tool,
            args={"command": command},
            status="ok",
            output=TerminalOut(command=command, output=output),
        ),
    )


def test_prometheus_matrix_and_vector_preserve_raw():
    matrix = (
        '{"status":"success","data":{"resultType":"matrix","result":['
        '{"metric":{"service":"payment"},"values":[[1790485967,"2"],[1790486027,"3"]]}]}}'
    )
    vector = (
        '{"status":"success","data":{"resultType":"vector","result":['
        '{"metric":{"status":"error"},"value":[1790485967,"5"]}]}}'
    )
    for raw, expected in ((matrix, "series"), (vector, "table")):
        original = call("execute_prometheus_query", "rate(errors[5m])", raw)
        shown = present_stored_event(original)
        assert shown.event.output.render == expected
        assert shown.event.raw_output == raw
        assert original.event.output.render == "terminal"
        assert original.event.raw_output is None
        assert present_stored_event(shown) == shown


def test_malformed_prometheus_stays_terminal():
    original = call(
        "execute_prometheus_query",
        "bad",
        '{"status":"success","data":{"resultType":"matrix","result":[{"values":[[1,"oops"]]}]}}',
    )
    assert present_stored_event(original) == original
    nonfinite = call(
        "execute_prometheus_query",
        "rate(errors[5m])",
        '{"status":"success","data":{"resultType":"vector","result":'
        '[{"metric":{},"value":[1790485967,"NaN"]}]}}',
    )
    assert present_stored_event(nonfinite) == nonfinite


def test_logs_and_mixed_diff():
    logs = call("search_logs", "query", "payment declined\nexpiry validation failed")
    shown = present_stored_event(logs)
    assert shown.event.output.render == "log"
    assert shown.event.output.lines == ["payment declined", "expiry validation failed"]
    assert shown.event.raw_output == logs.event.output.output

    mixed = call(
        "bash",
        "git log -5 && git diff v1..v2",
        "abc commit\n---DIFF---\ndiff --git a/x b/x\n-old\n+new",
        "codebase_analyst",
    )
    shown = present_stored_event(mixed)
    assert shown.event.output.render == "terminal"
    assert shown.event.output.language == "diff"
    assert shown.event.output.output == mixed.event.output.output


def test_unambiguous_code_and_diff():
    code = call(
        "bash",
        "cd /repo && sed -n '30,110p' src/payment/charge.js",
        "const expired = true;",
        "codebase_analyst",
    )
    shown = present_stored_event(code)
    assert shown.event.output.render == "code"
    assert shown.event.output.language == "javascript"
    assert shown.event.raw_output == "const expired = true;"
    diff = call("bash", "git diff", "diff --git a/x b/x\n-old\n+new", "codebase_analyst")
    assert present_stored_event(diff).event.output.render == "diff"


def test_offline_fixture_matches_api_models_and_has_local_outcome():
    path = Path(__file__).resolve().parents[1] / "web/fixtures/payment-investigation.json"
    fixture = json.loads(path.read_text())
    ticket = TicketDetail.model_validate(fixture["ticket"])
    Pipeline.model_validate(fixture["pipeline"])
    events = [StoredEvent.model_validate(item) for item in fixture["events"]]
    assert len(events) > 100
    assert all(item.ticket_id == ticket.id for item in events)
    assert [item.id for item in events] == sorted(item.id for item in events)
    assert any(item.event.kind == "approval_required" for item in events)
    assert events[-1].event.kind == "outcome"
    assert events[-1].event.engineering_handoff == "local_only"
    assert events[-1].event.reply_delivery == "logged"


def test_captured_analyst_outputs_are_representable_without_data_loss():
    path = Path(__file__).resolve().parents[1] / "web/fixtures/payment-investigation.json"
    fixture = json.loads(path.read_text())
    events = [StoredEvent.model_validate(item) for item in fixture["events"]]
    seen = set()
    for item in events:
        shown = item.event
        if not isinstance(shown, ToolCallEvent) or shown.raw_output is None:
            continue
        original = item.model_copy(
            update={
                "event": shown.model_copy(
                    update={
                        "output": TerminalOut(
                            command=str(shown.args.get("command", "")),
                            output=shown.raw_output,
                        ),
                        "raw_output": None,
                    }
                )
            }
        )
        adapted = present_stored_event(original)
        assert adapted.event.output.render == shown.output.render
        assert adapted.event.raw_output == shown.raw_output
        seen.add(shown.output.render)
    assert {"code", "series", "table", "log", "terminal"} <= seen
