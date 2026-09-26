"""Enrichment: one LLM call with the context bundle -> Enrichment, then validation in code.

TODO(phase 4): Pydantic AI Agent(pydantic_ai_model("enrichment"), output_type=Enrichment) with the
ticket and context bundle in the prompt; stream text via emit(ModelDeltaEvent); then validate:
likely_services must be ownership.yaml keys, relevant_changes must be IDs in the bundle, the window
must be sane. Drop anything invalid instead of trusting it.
"""

from datetime import UTC, datetime, timedelta

from app.events import ModelOutputEvent
from app.graph.state import TicketState
from app.graph.stream import emit
from app.models import Enrichment


async def run(state: TicketState) -> dict:
    t = state["ticket"]
    end = t.received_at or datetime.now(UTC)
    enrichment = Enrichment(  # stub
        window_start=end - timedelta(hours=3),
        window_end=end,
        window_basis="default: 3 hours before the ticket",
        symptom=t.subject,
    )
    emit(
        ModelOutputEvent(
            stage="enrich", name="Enrichment", data=enrichment.model_dump(mode="json"), model="stub"
        )
    )
    return {"enrichment": enrichment, "_summary": enrichment.symptom}
