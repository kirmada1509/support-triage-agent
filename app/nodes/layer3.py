"""Route a checked bug or incident to the owning Linear team."""

from urllib.parse import quote

from app import db
from app.events import DeliveryEvent, LinkEvent
from app.graph.state import TicketState
from app.graph.stream import emit
from app.integrations import linear
from app.nodes._config import ownership
from app.settings import settings

PRIORITY_NAMES = {1: "urgent", 2: "high", 3: "medium", 4: "low"}


def issue_description(state: TicketState) -> str:
    ticket, verdict = state["ticket"], state["verdict"]
    lines = [
        f"Source ticket: {ticket.id}",
        f"Tenant: {ticket.tenant_id or 'unknown'}",
        f"Service: {verdict.owning_service}",
        f"Root cause: {verdict.root_cause}",
        f"Engineering summary: {verdict.engineering_summary or verdict.root_cause}",
        "Affected count: at least 1 (this ticket); total not measured",
        f"Reported symptom: {ticket.subject} — {ticket.body}",
        "Reproduction: follow the customer report above; check linked evidence before changing "
        "code.",
    ]
    if verdict.file_line:
        location = verdict.file_line
        if settings.github_repo_url and verdict.commit:
            path, _, line = location.partition(":")
            location += (
                f" ({settings.github_repo_url.rstrip('/')}/blob/{verdict.commit}/"
                f"{quote(path, safe='/')}#L{line})"
            )
        lines.append(f"Code: {location}")
    if verdict.commit:
        commit = verdict.commit
        if settings.github_repo_url:
            commit += f" ({settings.github_repo_url.rstrip('/')}/commit/{verdict.commit})"
        lines.append(f"Introduced by: {commit}")
    lines.append("Evidence:")
    if settings.grafana_panel_url and any(
        evidence.source == "metric"
        for finding in state.get("findings", [])
        for evidence in finding.evidence
    ):
        lines.append(f"Grafana panel: {settings.grafana_panel_url}")
    for finding in state.get("findings", []):
        for evidence in finding.evidence:
            ref = evidence.ref
            if (
                evidence.source == "trace"
                and len(ref) >= 16
                and all(c in "0123456789abcdef" for c in ref.lower())
            ):
                ref += f" ({settings.jaeger_base_url.rstrip('/')}/trace/{ref})"
            lines.append(f"- {evidence.source}: {evidence.observation} [{ref}]")
    return "\n\n".join(lines)


async def run(state: TicketState) -> dict:
    verdict = state["verdict"]
    owner = ownership().get(verdict.owning_service)
    if not owner:
        raise ValueError(f"no owning team for {verdict.owning_service!r}")
    ticket = state["ticket"]
    priority = state.get("classification").severity if state.get("classification") else 3
    draft = state.get("reply") or verdict.customer_reply
    if "priority" not in draft.lower():
        draft = f"{draft.rstrip()} We've marked this as {PRIORITY_NAMES[priority]} priority."
    if not settings.linear_api_key:
        draft = (
            "We found an issue affecting your checkout. We've documented the finding "
            "and will follow up with an update."
        )
        emit(
            DeliveryEvent(
                stage="layer3",
                destination="linear",
                status="logged",
                detail=f"{owner['team']} finding for {ticket.id} kept locally; no Linear key",
            )
        )
        return {
            "linear_issue": None,
            "reply": draft,
            "_summary": f"{owner['team']} finding recorded locally",
        }
    prior = await db.delivery_receipt(ticket.id, "linear")
    if prior:
        return {
            "linear_issue": prior.external_id,
            "reply": draft,
            "_summary": f"{owner['team']} team, {prior.external_id}",
        }
    issue = await linear.create_issue(
        settings.linear_api_key,
        owner["linear_team"],
        f"[{ticket.id}] {ticket.subject}",
        issue_description(state),
        priority,
    )
    emit(
        DeliveryEvent(
            stage="layer3",
            destination="linear",
            status="sent",
            external_id=issue.identifier,
            detail=issue.url,
        )
    )
    emit(LinkEvent(stage="layer3", label=f"Linear {issue.identifier}", url=issue.url))
    return {
        "linear_issue": issue.identifier,
        "reply": draft,
        "_summary": f"{owner['team']} team, {issue.identifier}",
    }
