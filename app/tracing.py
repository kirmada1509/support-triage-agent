"""OpenTelemetry export for Pydantic AI calls (a span per model call). Phase 2.

Off unless OTEL_EXPORTER_OTLP_ENDPOINT is set, e.g. the shop's collector at http://localhost:4318,
so the agent's own traces land in the same Jaeger as the shop's.
"""

import os


def setup_tracing(service_name: str = "support-triage-agent") -> None:
    if not os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"):
        return
    # uv add opentelemetry-sdk opentelemetry-exporter-otlp-proto-http
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from pydantic_ai import Agent

    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)
    Agent.instrument_all()
