"""Round 2: if the data analyst found an exact error message, send it to the codebase analyst for
a short check of that one code path. Waits for both round-1 branches, and runs at most once.
"""

from app.analysts import AnalystLimit, AnalystRun
from app.analysts.codebox import investigate as codebox_investigate
from app.events import ModelOutputEvent
from app.graph.state import TicketState
from app.graph.stream import emit
from app.models import Findings
from app.nodes import findings
from app.nodes.duplicates import error_signature

STAGE = "round2"
TIMEOUT_S = 90
MAX_COMMANDS = 16


async def investigate(task: str, brief, on_call, **budget) -> AnalystRun:
    """The codebox with round 2's budget; tests replace it."""
    return await codebox_investigate(task, brief, on_call, stage=STAGE, **budget)


def round2_target(found: list[Findings]) -> str | None:
    """The data analyst's exact error message, unless the codebase analyst already located it."""
    if any(f.round == 2 for f in found):
        return None
    text = next((f.error_text for f in found if f.agent == "data_analyst" and f.error_text), None)
    if not text:
        return None
    signature = error_signature(text)
    for f in found:
        located = any(e.source == "code" for e in f.evidence)
        if f.agent == "codebase_analyst" and f.error_text and located:
            if error_signature(f.error_text) == signature:
                return None
    return text


async def run(state: TicketState) -> dict:
    found = state.get("findings", [])
    text = round2_target(found)
    if not text:
        return {"_summary": f"{len(found)} findings; round 2 not needed"}
    b = state["brief"]
    task = (
        f"The data analyst saw this exact error in production for {b.suspected_service} at "
        f'{b.deployed_version}:\n"{text}"\n'
        "Find where the code produces it (lookup-error), read that code path, and say whether "
        "it is intended behaviour or a regression, with file:line and the commit (git blame)."
    )
    try:
        result = await investigate(task, b, emit, max_commands=MAX_COMMANDS, timeout_s=TIMEOUT_S)
    except AnalystLimit as e:
        f = findings.limit_hit("codebase_analyst", str(e)).model_copy(update={"round": 2})
        return {"findings": [f], "_summary": f"round 2 inconclusive: {e}"}
    claimed = await findings.convert("codebase_analyst", result.answer, result.calls, round=2)
    f = findings.check_evidence(claimed, result.calls)
    emit(
        ModelOutputEvent(
            stage=STAGE, name="Findings", data=f.model_dump(), cost_usd=result.cost_usd
        )
    )
    return {"findings": [f], "_summary": f"round 2: {len(f.evidence)} evidence"}
