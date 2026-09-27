import operator
from typing import Annotated, TypedDict

from app.models import (
    Brief,
    Classification,
    ContextBundle,
    Enrichment,
    Findings,
    Handoff,
    Lane,
    Layer1Answer,
    RequestTriage,
    Retrieved,
    Ticket,
    Verdict,
)


class TicketState(TypedDict, total=False):
    """The graph's state. Each node returns only the keys it changes."""

    ticket: Ticket
    context: ContextBundle
    enrichment: Enrichment
    retrieved: list[Retrieved]
    classification: Classification
    lane: Lane
    layer1: Layer1Answer
    request: RequestTriage
    duplicate_of: str | None  # open issue this ticket repeats
    brief: Brief
    findings: Annotated[list[Findings], operator.add]  # both analysts add to it
    handoff: Handoff | None  # the question the next follow-up answers, if any
    handoffs: Annotated[list[Handoff], operator.add]  # every question asked so far
    verdict: Verdict
    linear_issue: str | None
    reply: str | None  # the draft, then the sent reply
    reply_delivery: str  # sent | logged | not_sent
    approval_reasons: list[str]
    approved: bool | None
