"""Human approval. Pauses the run with interrupt() when a person must check the reply; the
console's Approve button resumes it from the checkpoint with an ApprovalDecision.

Approval is required for: Sev1, revenue_blocking above 0.8, categorization below 0.7, an
inconclusive verdict or one below 0.7, an unconfident Layer 1
answer, and no draft reply at all.
"""

from langgraph.types import interrupt

from app.graph.state import TicketState
from app.models import ApprovalDecision


def approval_reasons(state: TicketState) -> list[str]:
    reasons = []
    c = state.get("classification")
    if c:
        if c.severity == 1:
            reasons.append("Sev1")
        if c.revenue_blocking and c.revenue_blocking_confidence > 0.8:
            reasons.append("revenue blocking")
        if c.needs_human or c.ticket_type_confidence < 0.7:
            reasons.append("categorization unsure")
    if (v := state.get("verdict")) and (v.kind == "inconclusive" or v.confidence < 0.7):
        reasons.append(f"verdict {v.kind} at {v.confidence:.0%}")
    if state.get("verdict") and state["verdict"].kind in {"confirmed_bug", "config_incident"}:
        if not state.get("linear_issue"):
            reasons.append("engineering handoff not created")
    if (a := state.get("layer1")) and (not a.confident or not a.cited_ids):
        reasons.append("Layer 1 answer not confident or uncited")
    if not state.get("reply"):
        reasons.append("no draft reply")
    return reasons


async def run(state: TicketState) -> dict:
    reasons = approval_reasons(state)
    if not reasons:
        return {"approved": True, "approval_reasons": [], "_summary": "auto-approved"}
    raw = interrupt(
        {
            "draft_reply": state.get("reply") or "",
            "reasons": reasons,
            "linear_issue": state.get("linear_issue"),
        }
    )
    decision = ApprovalDecision.model_validate(raw)
    reply = decision.edited_reply or state.get("reply")
    return {
        "approved": decision.approved,
        "approval_reasons": reasons,
        "reply": reply if decision.approved else None,
        "_summary": ("approved" if decision.approved else "rejected")
        + (" with edits" if decision.edited_reply else "")
        + (f" by {decision.reviewer}" if decision.reviewer else ""),
    }
