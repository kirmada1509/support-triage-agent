"""Graph streaming -> events.

Nodes send events with `emit()` (LangGraph's custom stream). `staged()` wraps every node so the
flowchart gets running/done/failed. `run_graph()` drives one run and hands each event to a sink
(the worker's sink writes it to the events table, whose trigger NOTIFYs the SSE stream).
"""

import functools
import time
import traceback
from collections.abc import Awaitable, Callable
from typing import Any

from langgraph.config import get_stream_writer
from langgraph.errors import GraphBubbleUp
from langgraph.types import Command
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from pydantic import BaseModel

from app.events import ApprovalRequiredEvent, ErrorEvent, Event, EventAdapter, StageEvent

Sink = Callable[[Event], Awaitable[None]]
NodeFn = Callable[[dict], Awaitable[dict | None]]


def emit(event: Event) -> None:
    """Send one event from inside a node."""
    get_stream_writer()(event)


def _tracer() -> trace.Tracer:
    """Looked up on each use, so it's whatever provider setup_tracing (or a test) installed."""
    return trace.get_tracer("support-triage-agent")


def staged(name: str, fn: NodeFn) -> NodeFn:
    """Emit running/done/failed stage events around a node. A node may return `_summary`, the
    one line shown on its flowchart node; it's removed before the update reaches the state.
    Each run of a node is also a span, a child of its ticket's span (see run_graph)."""

    @functools.wraps(fn)
    async def node(state: dict) -> dict:
        emit(StageEvent(stage=name, status="running"))
        t0 = time.monotonic()
        ticket = state.get("ticket")
        attrs = {"langgraph.node": name, "ticket.id": ticket.id if ticket else ""}
        with _tracer().start_as_current_span(
            f"node {name}", attributes=attrs, record_exception=False, set_status_on_exception=False
        ) as span:
            try:
                update = dict(await fn(state) or {})
            except GraphBubbleUp:  # interrupt(): the run pauses, not a failure
                raise
            except Exception as e:
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                ms = int((time.monotonic() - t0) * 1000)
                emit(StageEvent(stage=name, status="failed", summary=str(e)[:200], duration_ms=ms))
                emit(ErrorEvent(stage=name, message=str(e), traceback=traceback.format_exc()))
                raise
        ms = int((time.monotonic() - t0) * 1000)
        emit(
            StageEvent(
                stage=name, status="done", summary=update.pop("_summary", None), duration_ms=ms
            )
        )
        return update

    return node


def _as_event(chunk: Any) -> Event:
    return chunk if isinstance(chunk, BaseModel) else EventAdapter.validate_python(chunk)


async def run_graph(
    graph: Any,
    graph_input: dict | Command,
    ticket_id: str,
    sink: Sink,
    seen: set[str] | None = None,
) -> dict | None:
    """Run (or resume) one ticket's graph. Returns the interrupt payload if the run paused for
    approval, else None. When the run finishes, stages that never ran are sent as skipped."""
    config = {"configurable": {"thread_id": ticket_id}}
    seen = set(seen or ())
    paused: dict | None = None

    resumed = isinstance(graph_input, Command)
    attrs = {"ticket.id": ticket_id, "langgraph.resumed": resumed}
    with _tracer().start_as_current_span(f"ticket {ticket_id}", attributes=attrs):
        stream = graph.astream(graph_input, config, stream_mode=["updates", "custom"])
        async for mode, chunk in stream:
            if mode == "custom":
                event = _as_event(chunk)
                if isinstance(event, StageEvent):
                    seen.add(event.stage)
                await sink(event)
            elif mode == "updates" and "__interrupt__" in chunk:
                for intr in chunk["__interrupt__"]:
                    paused = intr.value
                    await sink(ApprovalRequiredEvent(**intr.value))

    if paused is None:
        for stage in stage_names(graph):
            if stage not in seen:
                await sink(StageEvent(stage=stage, status="skipped"))
    return paused


def stage_names(graph: Any) -> list[str]:
    return [n for n in graph.get_graph().nodes if n not in ("__start__", "__end__")]
