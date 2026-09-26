"""Round 2: if the data analyst found an exact error message or span, send it to the codebase
analyst for a short check of that one code path. Waits for both round-1 branches.

TODO(phase 6).
"""

from app.graph.state import TicketState


async def run(state: TicketState) -> dict:
    return {"_summary": f"{len(state.get('findings', []))} findings; round 2 not needed"}  # stub
