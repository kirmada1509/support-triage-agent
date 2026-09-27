"""Codebase analyst: mini-swe-agent in the read-only codebox (app/analysts/codebox.py) at the
deployed tag, with the previous tag at /prev and the deployed commit's code index at /index. The
task is the brief plus the service's ownership entry, its service card (orientation, not
evidence) and the changes since the previous deploy. Each command is streamed; a run that hits
its budget is inconclusive, never a guess.
"""

from app import db, models_config
from app.analysts import AnalystLimit, AnalystRun
from app.analysts.codebox import investigate as codebox_investigate
from app.events import ModelOutputEvent
from app.graph.state import TicketState
from app.graph.stream import emit
from app.indexer import build
from app.indexer.__main__ import sandbox_dir, service_path
from app.nodes import data_analyst, findings
from app.nodes._config import ownership

STAGE = "codebase_analyst"
TIMEOUT_S = 120
MAX_COMMANDS = 20


async def investigate(task: str, brief, on_call, **budget) -> AnalystRun:
    """The codebox with a budget; tests replace it."""
    return await codebox_investigate(task, brief, on_call, **budget)


async def service_card(service: str, version: str) -> str | None:
    cards = await db.service_cards(build.resolve(sandbox_dir(), version))
    return cards.get(service)


def change_summary(service: str, previous: str | None, deployed: str) -> str:
    if not previous:
        return ""
    return build.change_summary(sandbox_dir(), service_path(service), previous, deployed)


def task(state: TicketState, card: str | None, changes: str) -> str:
    b = state["brief"]
    owner = ownership().get(b.suspected_service, {})
    path = owner.get("path", "src/")
    parts = [
        b.text,
        f"\nService: {b.suspected_service} ({path}), {owner.get('description', '')}".rstrip(", "),
        f"Deployed: {b.deployed_version} (/repo)."
        + (f" Previous deploy: {b.previous_version} (/prev)." if b.previous_version else ""),
    ]
    if card:
        parts.append(f"\nService card (orientation only, not evidence):\n{card}")
    if changes:
        parts.append(f"\nChanges since the previous deploy:\n{changes}")
    parts.append(
        "\nIs the behaviour the customer describes intended, or a regression? Find where it "
        "comes from, and whether a recent commit changed it."
    )
    return "\n".join(parts)


async def run(state: TicketState) -> dict:
    b = state["brief"]
    card = await service_card(b.suspected_service, b.deployed_version)
    changes = change_summary(b.suspected_service, b.previous_version, b.deployed_version)
    try:
        result = await investigate(
            task(state, card, changes),
            b,
            emit,
            max_commands=MAX_COMMANDS,
            timeout_s=models_config.time_budget("codebase_analyst", TIMEOUT_S),
        )
    except AnalystLimit as e:
        f = findings.limit_hit(STAGE, str(e))
        emit(ModelOutputEvent(stage=STAGE, name="Findings", data=f.model_dump()))
        return {"findings": [f], "_summary": f"inconclusive: {e}"}
    claimed = await findings.convert(
        STAGE, result.answer, result.calls, symptom=data_analyst.symptom(state)
    )
    f = findings.check_evidence(claimed, result.calls)
    emit(
        ModelOutputEvent(
            stage=STAGE, name="Findings", data=f.model_dump(), cost_usd=result.cost_usd
        )
    )
    return {
        "findings": [f],
        "_summary": f"{len(result.calls)} commands, {len(f.evidence)} evidence",
    }
