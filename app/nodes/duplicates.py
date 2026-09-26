"""Duplicate check before Layer 2: exact signature match (service, version, normalized error
text) against open investigations, then retrieval over open tickets, confirmed by a Jev yes/no
question. On a match the ticket is linked and the analysts don't run.

TODO(phase 6).
"""

from app.graph.state import TicketState


async def run(state: TicketState) -> dict:
    return {"duplicate_of": None, "_summary": "no open issue matches"}  # stub
