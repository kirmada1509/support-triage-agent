"""Write-back to ticket memory: the ticket joins retrieval_docs (status open until its issue is
resolved), and a finished Layer 2 verdict becomes an investigations row for duplicate checks.

TODO(phase 6): app.retrieval.memory.add_ticket(...) and an investigations insert.
"""

from app.graph.state import TicketState


async def run(state: TicketState) -> dict:
    return {"_summary": "stub: nothing written"}
