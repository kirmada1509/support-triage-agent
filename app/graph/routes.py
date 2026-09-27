"""The four routing functions: pure functions of the state, no side effects."""

from typing import Literal

from app.graph.state import TicketState

LANE_TO_NODE = {"how_to": "layer1", "request": "requests", "tech_issue": "duplicates"}


def pick_lane(state: TicketState) -> Literal["layer1", "requests", "duplicates", "approve"]:
    c = state["classification"]
    if c.needs_human:  # The classifier was unsure or returned an unknown service.
        return "approve"
    return LANE_TO_NODE[c.ticket_type]


def is_duplicate(state: TicketState) -> Literal["reply", "brief"]:
    return "reply" if state.get("duplicate_of") else "brief"


def pick_handoff(state: TicketState) -> Literal["code_followup", "data_followup", "verdict"]:
    h = state.get("handoff")
    if h is None:
        return "verdict"
    return "code_followup" if h.to_agent == "codebase_analyst" else "data_followup"


def pick_outcome(state: TicketState) -> Literal["layer3", "approve"]:
    kind = state["verdict"].kind
    return "layer3" if kind in ("confirmed_bug", "config_incident") else "approve"
