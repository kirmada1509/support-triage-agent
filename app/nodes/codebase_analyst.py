"""Codebase analyst: mini-swe-agent in the read-only codebox container (codebox/), with helper
commands over the code index: repo-map, lookup-error, find-symbol, rpc-handler.

TODO(phase 6): start the container on the deployed version's worktree (read-only, no network);
task prompt = brief + ownership entry + service card + repo map + change summary since the
previous deploy; model litellm_model("codebase_analyst"); 90 s timeout, 15 steps; emit a
ToolCallEvent per command (TerminalOut, CodeOut or DiffOut) from a small agent subclass;
convert the answer with findings.to_findings().
"""

import uuid

from app.events import TerminalOut, ToolCallEvent
from app.graph.state import TicketState
from app.graph.stream import emit
from app.models import Findings
from app.nodes._config import ownership

STAGE = "codebase_analyst"


async def run(state: TicketState) -> dict:
    service = state["brief"].suspected_service
    path = ownership().get(service, {}).get("path", "src/")
    call_id = uuid.uuid4().hex[:8]
    cmd = f"repo-map {path}"
    emit(
        ToolCallEvent(
            stage=STAGE, call_id=call_id, tool="shell", args={"command": cmd}, status="running"
        )
    )
    emit(
        ToolCallEvent(
            stage=STAGE,
            call_id=call_id,
            tool="shell",
            args={"command": cmd},
            status="ok",
            duration_ms=0,
            output=TerminalOut(command=cmd, output="(stub) codebox not built yet"),
        )
    )
    f = Findings(
        agent="codebase_analyst", hypothesis="(stub) not investigated", evidence=[], confidence=0.0
    )
    return {"findings": [f], "_summary": "stub: 1 command"}
