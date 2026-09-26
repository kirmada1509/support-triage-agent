"""Layer 3, engineering router: owning team from ownership.yaml, a Linear issue with the root
cause, evidence and diff link, and an acknowledgement for the customer.

TODO(phase 7): create the issue with the Linear API (LINEAR_API_KEY) and emit a LinkEvent.
"""

from app.graph.state import TicketState
from app.nodes._config import ownership


async def run(state: TicketState) -> dict:
    v = state["verdict"]
    owner = ownership().get(v.owning_service, {"team": "Unassigned", "linear_team": "TRI"})
    issue = f"{owner['linear_team']}-STUB"  # stub: no Linear call yet
    return {"linear_issue": issue, "_summary": f"{owner['team']} team, {issue}"}
