"""Hybrid retrieval over help-center sections and past tickets (pgvector + full text, RRF).

TODO(phase 3): app.retrieval.search.search(query=ticket text + enrichment.symptom, ...).
"""

from app.events import RetrievalEvent
from app.graph.state import TicketState
from app.graph.stream import emit


async def run(state: TicketState) -> dict:
    query = f"{state['ticket'].subject}\n{state['enrichment'].symptom}"
    results: list = []  # stub
    emit(RetrievalEvent(stage="retrieve", query=query, results=results))
    return {"retrieved": results, "_summary": f"{len(results)} results"}
