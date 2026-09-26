"""Context fetch (code, no LLM): tenant, recent tickets, deploys and flag changes from the last
24 h, open incidents, and the service catalog. Gathered, not interpreted."""

from app.db import fetch_context
from app.graph.state import TicketState
from app.nodes._config import service_glossary


async def run(state: TicketState) -> dict:
    services = service_glossary()
    ctx = await fetch_context(state["ticket"], services)
    return {
        "context": ctx,
        "_summary": f"{len(ctx.deploys)} deploys, {len(ctx.flag_changes)} flag changes in 24 h",
    }
