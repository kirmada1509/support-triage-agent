"""Data analyst: HolmesGPT in its own container (holmes/Dockerfile) on the shop's network, with the
Prometheus, OpenSearch and PostgreSQL toolsets plus the custom jaeger and history toolsets
(holmes/toolsets.yaml). It can't be imported: its dependencies conflict with Pydantic AI's.

TODO(phase 6): in that container, run `holmes ask --config /etc/holmes/config.yaml --model
<litellm_model("data_analyst")> --json-output-file ...` with one question (brief + enrichment +
telemetry guide). Enforce the 90 s timeout and the tool-call budget here: its --max-steps counts
model turns, not calls. Emit a ToolCallEvent per entry of the output file's tool_calls, and convert
the answer with findings.to_findings(). tests/test_spike.py has a working run;
planning/Phase_2_Spike.md says what to watch.
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
