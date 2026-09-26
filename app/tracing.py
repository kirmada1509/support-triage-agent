"""OpenTelemetry export of the agent's own spans: one per ticket run, one per graph node
(app/graph/stream.py), and one per Pydantic AI model call.

Off unless OTEL_EXPORTER_OTLP_ENDPOINT is set. From the host, the shop's collector takes OTLP over
HTTP through its frontend proxy: OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:8080/otlp-http.
The agent's traces then land in the same Jaeger as the shop's, as service support-triage-agent.
"""

import functools
import os

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from pydantic_ai import Agent


@functools.cache  # once per process
def setup_tracing(service_name: str = "support-triage-agent") -> bool:
    if not os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"):
        return False
    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)
    Agent.instrument_all()
    return True
