"""Send the reply to the customer. For a linked duplicate, the reply is the open issue's status.

TODO(phase 7): post to the Pylon conversation (or log it when no Pylon account is configured).
"""

from app.graph.state import TicketState


async def run(state: TicketState) -> dict:
    if dup := state.get("duplicate_of"):
        reply = (
            f"This matches an issue we're already working on ({dup}). "
            "We'll update you as soon as it's fixed."
        )
        return {"reply": reply, "_summary": f"linked to {dup}"}
    if not state.get("reply"):
        return {"_summary": "no reply sent (handed to a person)"}
    return {"_summary": "reply sent (stub)"}
