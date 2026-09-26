"""Data analyst: HolmesGPT (Python SDK) with the Prometheus, OpenSearch and PostgreSQL toolsets
plus the custom jaeger and history toolsets (holmes/toolsets.yaml).

TODO(phase 6): build the HolmesGPT config with litellm_model("data_analyst") and only those
toolsets; ask one question (brief + enrichment + telemetry guide) in a worker thread with a 90 s
timeout and at most 15 tool calls; emit a ToolCallEvent per tool call (wrap its tool executor,
or send its tool log when it finishes); convert the answer with findings.to_findings().
The stub shows the deploy history from the context bundle, so the console has real rows.
"""

import uuid

from app.events import TableOut, ToolCallEvent
from app.graph.state import TicketState
from app.graph.stream import emit
from app.models import Findings

STAGE = "data_analyst"


async def run(state: TicketState) -> dict:
    call_id = uuid.uuid4().hex[:8]
    args = {"hours": 24}
    emit(
        ToolCallEvent(
            stage=STAGE, call_id=call_id, tool="history.deploys", args=args, status="running"
        )
    )
    deploys = state["context"].deploys
    emit(
        ToolCallEvent(
            stage=STAGE,
            call_id=call_id,
            tool="history.deploys",
            args=args,
            status="ok",
            duration_ms=0,
            output=TableOut(
                columns=["service", "from", "to", "deployed_at"],
                rows=[
                    [d.service, d.previous_version, d.version, d.deployed_at.isoformat()]
                    for d in deploys
                ],
            ),
        )
    )
    f = Findings(
        agent="data_analyst", hypothesis="(stub) not investigated", evidence=[], confidence=0.0
    )
    return {"findings": [f], "_summary": "stub: 1 tool call"}
