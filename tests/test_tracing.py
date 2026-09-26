"""The agent's own traces: one span per ticket run, one child span per graph node."""

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from app.graph import build
from app.graph.build import build_graph, checkpoint_serde
from app.graph.stream import run_graph
from tests.conftest import demo_ticket

EXPORTER = InMemorySpanExporter()


@pytest.fixture(scope="module", autouse=True)
def provider():
    p = TracerProvider()
    p.add_span_processor(SimpleSpanProcessor(EXPORTER))
    trace.set_tracer_provider(p)  # once per process; the default suite sets no other


@pytest.fixture(autouse=True)
def clear():
    EXPORTER.clear()


async def sink(event):
    pass


async def test_a_run_is_one_trace_with_a_span_per_node():
    graph = build_graph(InMemorySaver(serde=checkpoint_serde()))
    await run_graph(graph, {"ticket": demo_ticket("2")}, "T-2", sink)
    spans = EXPORTER.get_finished_spans()
    [root] = [s for s in spans if s.name == "ticket T-2"]
    nodes = {s.attributes["langgraph.node"]: s for s in spans if s.name.startswith("node ")}
    assert {"context", "enrich", "retrieve", "jev", "route", "requests", "reply"} <= set(nodes)
    assert all(s.context.trace_id == root.context.trace_id for s in nodes.values())
    assert all(s.parent.span_id == root.context.span_id for s in nodes.values())
    assert nodes["context"].attributes["ticket.id"] == "T-2"


async def test_a_failed_node_is_an_error_span(monkeypatch):
    async def broken(state):
        raise RuntimeError("jev is down")

    monkeypatch.setitem(build.NODES, "jev", broken)
    monkeypatch.setitem(build.RETRY, "jev", None)  # one attempt, one span
    graph = build_graph(InMemorySaver(serde=checkpoint_serde()))
    with pytest.raises(RuntimeError):
        await run_graph(graph, {"ticket": demo_ticket("2")}, "T-9", sink)
    [jev] = [s for s in EXPORTER.get_finished_spans() if s.name == "node jev"]
    assert jev.status.status_code == StatusCode.ERROR
    assert jev.events[0].name == "exception"
