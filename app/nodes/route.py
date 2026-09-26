"""Lane choice. The decision itself is the conditional edge (routes.pick_lane); this node records
it so the queue and the flowchart show the lane."""

from app.graph.routes import pick_lane
from app.graph.state import TicketState


async def run(state: TicketState) -> dict:
    c = state["classification"]
    return {"lane": c.ticket_type, "_summary": f"{c.ticket_type} -> {pick_lane(state)}"}
