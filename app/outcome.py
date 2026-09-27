"""Shape the final graph state into one readable outcome for API and SSE consumers."""

from app.events import OutcomeEvent
from app.graph.state import TicketState

VERDICT_NAMES = {
    "confirmed_bug": "Confirmed bug",
    "config_incident": "Configuration incident",
    "false_positive": "Expected behaviour",
    "inconclusive": "Investigation inconclusive",
}


def build_outcome(state: TicketState) -> OutcomeEvent:
    verdict = state.get("verdict")
    request = state.get("request")
    duplicate = state.get("duplicate_of")
    issue = state.get("linear_issue")
    if duplicate:
        summary = f"Linked to open issue {duplicate}"
    elif verdict:
        summary = f"{VERDICT_NAMES[verdict.kind]} in {verdict.owning_service}: {verdict.root_cause}"
    elif request:
        summary = f"{request.kind.capitalize()} request: {request.summary}"
    elif state.get("layer1"):
        summary = "Help answer prepared"
    else:
        summary = "Ticket triaged"
    needs_handoff = (verdict and verdict.kind in {"confirmed_bug", "config_incident"}) or (
        request and request.kind == "feature"
    )
    return OutcomeEvent(
        lane=state.get("lane"),
        summary=summary,
        verdict_kind=verdict.kind if verdict else ("duplicate" if duplicate else None),
        root_cause=verdict.root_cause if verdict else None,
        service=verdict.owning_service if verdict else None,
        file_line=verdict.file_line if verdict else None,
        commit=verdict.commit if verdict else None,
        duplicate_of=duplicate,
        linear_issue=issue,
        engineering_handoff=("created" if issue else "local_only")
        if needs_handoff
        else "not_needed",
        reply=state.get("reply"),
        reply_delivery=state.get("reply_delivery", "not_sent"),
        approved=state.get("approved"),
    )
