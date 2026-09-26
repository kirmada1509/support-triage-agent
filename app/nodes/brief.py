"""The investigation brief both analysts receive: identifiers, time window, suspected service,
the customer's own words, and similar past investigations as hypotheses (never facts).

TODO(phase 6): one call on the verdict role's model, with the top 3 similar investigations.
"""

from app.graph.state import TicketState
from app.models import Brief


async def run(state: TicketState) -> dict:
    t, e, c = state["ticket"], state["enrichment"], state["classification"]
    text = (
        f"Customer says: {t.body}\n"
        f"Window: {e.window_start:%Y-%m-%d %H:%M} to {e.window_end:%H:%M} UTC ({e.window_basis})\n"
        f"Identifiers: {e.identifiers or 'none given'}\n"
        f"Suspected service: {c.service}"
    )
    return {
        "brief": Brief(text=text, suspected_service=c.service),
        "_summary": f"suspected: {c.service}",
    }
