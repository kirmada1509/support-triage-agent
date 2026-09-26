"""Request triage: one LLM call -> {kind, summary, roadmap_tag, acknowledgement}; code routes it
(feature -> roadmap list, billing/account -> account manager).

TODO(phase 4): Pydantic AI Agent(pydantic_ai_model("requests"), output_type=RequestTriage).
"""

from app.events import ModelOutputEvent
from app.graph.state import TicketState
from app.graph.stream import emit
from app.models import RequestTriage


async def run(state: TicketState) -> dict:
    t = state["ticket"]
    triage = RequestTriage(  # stub
        kind="feature",
        summary=t.subject,
        roadmap_tag="unsorted",
        acknowledgement="(stub) Thanks for the suggestion, we've shared it with our product team.",
    )
    emit(
        ModelOutputEvent(
            stage="requests", name="RequestTriage", data=triage.model_dump(), model="stub"
        )
    )
    return {
        "request": triage,
        "reply": triage.acknowledgement,
        "_summary": f"{triage.kind}: {triage.roadmap_tag}",
    }
