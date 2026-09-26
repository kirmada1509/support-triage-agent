"""Verdict: one call on the strongest model over both analysts' Findings.

TODO(phase 6): Pydantic AI Agent(pydantic_ai_model("verdict"), output_type=Verdict). A verdict
without evidence from at least two independent sources is inconclusive; it never guesses.
"""

from app.events import ModelOutputEvent
from app.graph.state import TicketState
from app.graph.stream import emit
from app.models import Verdict


async def run(state: TicketState) -> dict:
    v = Verdict(  # stub
        kind="inconclusive",
        root_cause="(stub) analysts not implemented",
        owning_service=state["brief"].suspected_service,
        confidence=0.0,
        customer_reply="(stub) We're looking into this and will update you shortly.",
    )
    emit(ModelOutputEvent(stage="verdict", name="Verdict", data=v.model_dump(), model="stub"))
    return {"verdict": v, "reply": v.customer_reply, "_summary": f"{v.kind} ({v.confidence:.0%})"}
