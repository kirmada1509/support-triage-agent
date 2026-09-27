"""Pure, conservative presentation hints for tool output returned by the console API."""

import json
import math
import re
from datetime import UTC, datetime

from app.code_snippets import snippets_from_events
from app.events import (
    CodeOut,
    DiffOut,
    LogOut,
    OutcomeEvent,
    Series,
    SeriesOut,
    SeriesPoint,
    StoredEvent,
    TableOut,
    TerminalOut,
    ToolCallEvent,
)


def _finite(value: object) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("non-finite Prometheus sample")
    return number


def _prometheus(raw: str, command: str) -> SeriesOut | TableOut | None:
    try:
        payload = json.loads(raw)
        data = payload["data"]
        if payload["status"] != "success" or not isinstance(data["result"], list):
            return None
        kind = data["resultType"]
        results = data["result"]
        if kind == "matrix":
            series = []
            for result in results:
                metric = result["metric"]
                if not isinstance(metric, dict):
                    return None
                points = [
                    SeriesPoint(ts=datetime.fromtimestamp(_finite(ts), UTC), value=_finite(value))
                    for ts, value in result["values"]
                ]
                series.append(
                    Series(
                        name=", ".join(f"{k}={v}" for k, v in metric.items()) or "result",
                        points=points,
                    )
                )
            return SeriesOut(query=command, series=series)
        if kind == "vector":
            rows = []
            for result in results:
                metric = result["metric"]
                if not isinstance(metric, dict):
                    return None
                rows.append(
                    [
                        ", ".join(f"{k}={v}" for k, v in metric.items()) or "result",
                        _finite(result["value"][1]),
                    ]
                )
            return TableOut(columns=["Series", "Value"], rows=rows)
    except (ValueError, TypeError, KeyError, IndexError, OverflowError):
        return None
    return None


def present_stored_event(item: StoredEvent) -> StoredEvent:
    """Return a copy with a typed visual output; never modify the stored event or its raw text."""
    event = item.event
    if not isinstance(event, ToolCallEvent) or not isinstance(event.output, TerminalOut):
        return item
    output = event.output
    if event.status != "ok" or output.exit_code != 0 or not output.output:
        return item
    tool = event.tool.lower()
    command = str(event.args.get("command", output.command))
    raw = output.output
    replacement = None
    if "prometheus" in tool:
        replacement = _prometheus(raw, command)
    elif (
        tool in {"search_logs", "log_indices"}
        or "log" in tool
        and event.stage in {"data_analyst", "data_followup"}
    ):
        replacement = LogOut(source=event.tool, lines=raw.splitlines())
    elif event.stage in {"codebase_analyst", "code_followup", "round2"}:  # round2: older runs
        if raw.startswith("diff --git ") and "---DIFF---" not in raw:
            replacement = DiffOut(diff=raw)
        else:
            match = re.search(r"(?:sed -n '[^']+'|cat) (src/[\w./-]+\.(?:js|ts|py))\s*$", command)
            if match and "---" not in raw and "diff --git" not in raw:
                language = {"js": "javascript", "ts": "typescript", "py": "python"}[
                    match.group(1).rsplit(".", 1)[1]
                ]
                replacement = CodeOut(file=match.group(1), language=language, code=raw)
            elif "diff --git " in raw or "===DIFF===" in raw:
                replacement = output.model_copy(update={"language": "diff"})
    if replacement is None:
        return item
    return item.model_copy(
        update={"event": event.model_copy(update={"output": replacement, "raw_output": raw})}
    )


def present_run_events(items: list[StoredEvent]) -> list[StoredEvent]:
    """Present a complete stored run, including source-backed snippets for older outcomes."""
    result = []
    for item in items:
        event = item.event
        if isinstance(event, OutcomeEvent) and event.file_line and not event.code_snippets:
            snippets = snippets_from_events(event.file_line, items)
            if snippets:
                item = item.model_copy(
                    update={"event": event.model_copy(update={"code_snippets": snippets})}
                )
        result.append(present_stored_event(item))
    return result
