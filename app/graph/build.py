"""The pipeline as one LangGraph StateGraph. Every stage is a node; lanes are conditional edges."""

from functools import cache
from pathlib import Path

import yaml
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy
from pydantic import BaseModel

from app import models
from app.graph.routes import is_duplicate, pick_lane, pick_outcome
from app.graph.state import TicketState
from app.graph.stream import staged
from app.nodes import (
    approve,
    brief,
    codebase_analyst,
    context,
    data_analyst,
    duplicates,
    enrich,
    jev,
    layer1,
    layer3,
    remember,
    reply,
    requests,
    retrieve,
    round2,
    route,
    verdict,
)

NODES = {
    "context": context.run,
    "enrich": enrich.run,
    "retrieve": retrieve.run,
    "jev": jev.run,
    "route": route.run,
    "layer1": layer1.run,
    "requests": requests.run,
    "duplicates": duplicates.run,
    "brief": brief.run,
    "data_analyst": data_analyst.run,
    "codebase_analyst": codebase_analyst.run,
    "round2": round2.run,
    "verdict": verdict.run,
    "layer3": layer3.run,
    "approve": approve.run,
    "reply": reply.run,
    "remember": remember.run,
}

# Nodes that call outside services retry on their own, not the whole ticket.
_CALLS_OUT = RetryPolicy(max_attempts=3, initial_interval=1.0)
_AGENT = RetryPolicy(max_attempts=2, initial_interval=2.0)
RETRY = {
    "enrich": _CALLS_OUT,
    "retrieve": _CALLS_OUT,
    "jev": _CALLS_OUT,
    "layer1": _CALLS_OUT,
    "requests": _CALLS_OUT,
    "duplicates": _CALLS_OUT,
    "verdict": _CALLS_OUT,
    "layer3": _CALLS_OUT,
    "reply": _CALLS_OUT,
    "remember": _CALLS_OUT,
    "data_analyst": _AGENT,
    "codebase_analyst": _AGENT,
    "round2": _AGENT,
}


def checkpoint_serde() -> JsonPlusSerializer:
    """Checkpoints store our Pydantic models; allow exactly those classes to be loaded back."""
    allowed = [
        (cls.__module__, cls.__name__)
        for cls in vars(models).values()
        if isinstance(cls, type)
        and issubclass(cls, BaseModel)
        and cls.__module__ == models.__name__
    ]
    return JsonPlusSerializer(allowed_msgpack_modules=allowed)


def build_graph(checkpointer=None):
    g = StateGraph(TicketState)
    for name, fn in NODES.items():
        g.add_node(name, staged(name, fn), retry_policy=RETRY.get(name))

    g.add_edge(START, "context")
    g.add_edge("context", "enrich")
    g.add_edge("enrich", "retrieve")
    g.add_edge("enrich", "jev")  # retrieval and classification run side by side
    g.add_edge(["retrieve", "jev"], "route")  # waits for both
    g.add_conditional_edges("route", pick_lane, ["layer1", "requests", "duplicates", "approve"])
    g.add_conditional_edges("duplicates", is_duplicate, ["reply", "brief"])
    g.add_edge("brief", "data_analyst")
    g.add_edge("brief", "codebase_analyst")  # the two analysts run in parallel
    g.add_edge(["data_analyst", "codebase_analyst"], "round2")
    g.add_edge("round2", "verdict")
    g.add_conditional_edges("verdict", pick_outcome, ["layer3", "approve"])
    for n in ("layer1", "requests", "layer3"):
        g.add_edge(n, "approve")
    g.add_edge("approve", "reply")
    g.add_edge("reply", "remember")
    g.add_edge("remember", END)
    return g.compile(checkpointer=checkpointer)


@cache
def stage_count() -> int:
    """Stages a ticket can pass through (the flowchart's nodes minus start and end)."""
    return len(build_graph().get_graph().nodes) - 2


@cache
def _layout() -> dict[str, dict]:
    return yaml.safe_load((Path(__file__).parent / "layout.yaml").read_text())


def pipeline_shape() -> dict:
    """Nodes and edges for the console's flowchart, straight from the compiled graph."""
    drawn = build_graph().get_graph()
    layout = _layout()
    return {
        "nodes": [
            {
                "id": n,
                "label": n.replace("_", " ").strip(),
                "position": layout.get(n, {"x": 0, "y": 0}),
            }
            for n in drawn.nodes
        ],
        "edges": [
            {
                "id": f"{e.source}->{e.target}",
                "source": e.source,
                "target": e.target,
                "conditional": e.conditional,
            }
            for e in drawn.edges
        ],
    }
