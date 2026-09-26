"""Layer 1, product support: one LLM call over the retrieved help sections and past tickets.

TODO(phase 4): Pydantic AI Agent(pydantic_ai_model("layer1"), output_type=Layer1Answer); check in
code that every cited ID is in state["retrieved"]; if nothing scores above the threshold, nothing
is cited, or confident is false, the draft goes to a person (approve node).
"""

from app.events import ModelOutputEvent
from app.graph.state import TicketState
from app.graph.stream import emit
from app.models import Layer1Answer


async def run(state: TicketState) -> dict:
    answer = Layer1Answer(  # stub
        answer="(stub) Thanks for reaching out. A support engineer will follow up shortly.",
        cited_ids=[],
        confident=False,
    )
    emit(
        ModelOutputEvent(
            stage="layer1", name="Layer1Answer", data=answer.model_dump(), model="stub"
        )
    )
    return {
        "layer1": answer,
        "reply": answer.answer,
        "_summary": f"{len(answer.cited_ids)} citations, confident={answer.confident}",
    }
