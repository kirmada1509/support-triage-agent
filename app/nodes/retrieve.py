"""Hybrid retrieval over help sections and resolved past tickets."""

from functools import cache

from app.events import RetrievalEvent
from app.graph.state import TicketState
from app.graph.stream import emit
from app.retrieval.embed import LocalBGE
from app.retrieval.search import search


@cache
def embedder() -> LocalBGE:
    return LocalBGE()


async def run(state: TicketState) -> dict:
    ticket = state["ticket"]
    query = f"{ticket.subject}\n{ticket.body}\n{state['enrichment'].symptom}"
    help_hits = await search(query, embedder(), kind="help_section", limit=5)
    ticket_hits = await search(
        query,
        embedder(),
        kind="ticket",
        services=state["enrichment"].likely_services or None,
        limit=3,
    )
    results = help_hits + ticket_hits
    emit(RetrievalEvent(stage="retrieve", query=query, results=results))
    return {"retrieved": results, "_summary": f"{len(help_hits)} help, {len(ticket_hits)} tickets"}
