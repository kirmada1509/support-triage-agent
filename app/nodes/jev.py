"""Categorization with Jev (TypeSafe): ticket_type, service, severity, revenue_blocking.

TODO(phase 4): typesafe-sdk call with model jev-latest; below 0.7 on ticket_type, an LLM re-read
with the same schema (role jev_fallback); still unsure -> needs_human. revenue_blocking above 0.8
raises severity. The stub below guesses from keywords so the graph takes realistic lanes.
"""

import re

from app.events import JevEvent
from app.graph.state import TicketState
from app.graph.stream import emit
from app.models import Classification, JevAnswer
from app.nodes._config import service_names

_HOW_TO = re.compile(r"^(which|how|what|where|can (i|we) (see|find|change))\b", re.I)
_SERVICE_HINTS = [
    (r"card|payment|expired", "payment"),
    (r"shipping|quote", "quote"),
    (r"search", "product-catalog"),
    (r"cart", "cart"),
]
_REQUEST = re.compile(r"\b(can you add|feature|would love|please add|support for)\b", re.I)


def _stub_classify(text: str) -> Classification:
    if _REQUEST.search(text):
        ticket_type = "request"
    elif _HOW_TO.search(text.strip()):
        ticket_type = "how_to"
    else:
        ticket_type = "tech_issue"
    lowered = text.lower()
    service = next((svc for pattern, svc in _SERVICE_HINTS if re.search(pattern, lowered)), None)
    if service is None:
        service = next((s for s in service_names() if s.replace("-", " ") in lowered), "other")
    blocking = ticket_type == "tech_issue" and bool(re.search(r"checkout|card|pay", lowered))
    severity = 2 if blocking else 3
    return Classification(
        ticket_type=ticket_type,
        ticket_type_confidence=0.9,
        service=service,
        severity=severity,
        revenue_blocking=blocking,
        revenue_blocking_confidence=0.85 if blocking else 0.6,
        source="stub",
        answers=[
            JevAnswer(question="ticket_type", answer=ticket_type, confidence=0.9),
            JevAnswer(question="service", answer=service, confidence=0.8),
            JevAnswer(question="severity", answer=severity, confidence=0.7),
            JevAnswer(
                question="revenue_blocking", answer=blocking, confidence=0.85 if blocking else 0.6
            ),
        ],
    )


async def run(state: TicketState) -> dict:
    t = state["ticket"]
    c = _stub_classify(f"{t.subject}\n{t.body}")
    emit(JevEvent(stage="jev", answers=c.answers, source=c.source))
    return {"classification": c, "_summary": f"{c.ticket_type} · {c.service} · sev {c.severity}"}
