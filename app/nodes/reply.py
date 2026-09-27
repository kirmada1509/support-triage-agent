"""Deliver an approved reply through Pylon, or keep an auditable local log for demo tickets."""

import logging

from app import db
from app.events import DeliveryEvent, LinkEvent
from app.graph.state import TicketState
from app.graph.stream import emit
from app.integrations import linear, pylon
from app.settings import settings

log = logging.getLogger(__name__)


def needs_account_note(state: TicketState) -> bool:
    request = state.get("request")
    verdict = state.get("verdict")
    return bool(
        (request and request.kind in {"billing", "account"})
        or (verdict and verdict.kind in {"confirmed_bug", "config_incident"})
    )


async def _roadmap(state: TicketState) -> str | None:
    request = state.get("request")
    if not request or request.kind != "feature":
        return None
    ticket = state["ticket"]
    if not settings.linear_api_key or not settings.roadmap_linear_team:
        emit(
            DeliveryEvent(
                stage="reply",
                destination="linear",
                status="logged",
                detail=(
                    f"Roadmap request {ticket.id}: {request.summary}; "
                    "Linear roadmap team not configured"
                ),
            )
        )
        return None
    prior = await db.delivery_receipt(ticket.id, "linear")
    if prior:
        return prior.external_id
    issue = await linear.create_issue(
        settings.linear_api_key,
        settings.roadmap_linear_team,
        f"[{ticket.id}] Feature request: {request.summary}",
        f"Customer request: {ticket.subject}\n\n{ticket.body}\n\n"
        f"Tenant: {ticket.tenant_id or 'unknown'}\n"
        f"Roadmap tag: {request.roadmap_tag or 'unclassified'}",
        state.get("classification").severity if state.get("classification") else 3,
    )
    emit(
        DeliveryEvent(
            stage="reply",
            destination="linear",
            status="sent",
            external_id=issue.identifier,
            detail=issue.url,
        )
    )
    emit(LinkEvent(stage="reply", label=f"Linear {issue.identifier}", url=issue.url))
    return issue.identifier


async def _note(state: TicketState) -> None:
    ticket = state["ticket"]
    request = state.get("request")
    if not needs_account_note(state) or not ticket.pylon_issue_id:
        return
    if await db.delivery_receipt(ticket.id, "pylon_note"):
        return
    if request and request.kind in {"billing", "account"}:
        body = f"Account manager: {request.kind} request {ticket.id}. {request.summary}"
    else:
        severity = state.get("classification").severity if state.get("classification") else 3
        handoff = state.get("linear_issue") or "engineering review pending"
        body = (
            f"Account manager: {handoff} for {ticket.id}. "
            f"Priority {severity}. Root cause: {state['verdict'].root_cause}"
        )
    note = await pylon.send_note(settings.pylon_api_token, ticket.pylon_issue_id, body)
    emit(
        DeliveryEvent(
            stage="reply",
            destination="pylon_note",
            status="sent",
            external_id=note,
            detail=f"Internal account-manager note on {ticket.pylon_issue_id}",
        )
    )


async def run(state: TicketState) -> dict:
    if state.get("approved") is False:
        return {"reply_delivery": "not_sent", "_summary": "no reply sent (approval rejected)"}
    duplicate = state.get("duplicate_of")
    draft = state.get("reply")
    if duplicate:
        draft = (
            f"This matches an issue we're already working on ({duplicate}). "
            "We'll update you as soon as it's fixed."
        )
    if not draft:
        return {"reply_delivery": "not_sent", "_summary": "no reply sent (handed to a person)"}
    ticket = state["ticket"]
    roadmap_issue = await _roadmap(state)
    update = {"reply": draft}
    if roadmap_issue:
        update["linear_issue"] = roadmap_issue
    if not settings.pylon_api_token or not ticket.pylon_issue_id:
        if needs_account_note(state):
            log.info("Account manager handoff logged for ticket %s", ticket.id)
            emit(
                DeliveryEvent(
                    stage="reply",
                    destination="pylon_note",
                    status="logged",
                    detail=f"Account manager handoff for {ticket.id}",
                )
            )
        log.info("Customer reply logged for ticket %s: %s", ticket.id, draft)
        emit(
            DeliveryEvent(
                stage="reply",
                destination="pylon_reply",
                status="logged",
                detail="Pylon not configured"
                if not settings.pylon_api_token
                else "No Pylon issue ID",
            )
        )
        reason = "Pylon not configured" if not settings.pylon_api_token else "no Pylon issue ID"
        return {**update, "reply_delivery": "logged", "_summary": f"reply logged ({reason})"}
    await _note(state)
    prior = await db.delivery_receipt(ticket.id, "pylon_reply")
    if prior:
        return {
            **update,
            "reply_delivery": "sent",
            "_summary": f"reply already sent ({prior.external_id})",
        }
    sent = await pylon.send_reply(
        settings.pylon_api_token,
        ticket.pylon_issue_id,
        draft,
        ticket.requester,
        message_id=ticket.pylon_message_id,
    )
    emit(
        DeliveryEvent(
            stage="reply",
            destination="pylon_reply",
            status="sent",
            external_id=sent,
            detail=f"Customer reply on {ticket.pylon_issue_id}",
        )
    )
    return {**update, "reply_delivery": "sent", "_summary": f"reply sent ({sent})"}
