"""Context fetch (code, no LLM): tenant, recent tickets, deploys and flag changes from the last
24 h, open incidents, and the service catalog. Gathered, not interpreted."""

from app.db import fetch_context
from app.graph.state import TicketState
from app.nodes._config import ownership


async def run(state: TicketState) -> dict:
    services = {name: f"{o['team']} team, {o['path']}" for name, o in ownership().items()}
    ctx = await fetch_context(state["ticket"], services)
    return {
        "context": ctx,
        "_summary": f"{len(ctx.deploys)} deploys, {len(ctx.flag_changes)} flag changes in 24 h",
    }
