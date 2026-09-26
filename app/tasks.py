"""Procrastinate tasks: start a ticket's graph run, resume it after approval.

Run the worker with `make worker` (python -m procrastinate, so `app` is importable).
Each task takes a lock on the ticket ID, so a run and its resume never overlap.
LangGraph checkpoints every step in Postgres (thread_id = ticket ID).
"""

from datetime import UTC, datetime

import procrastinate
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.types import Command
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app import db
from app.events import ErrorEvent, Event, JevEvent
from app.graph.build import build_graph, checkpoint_serde
from app.graph.stream import run_graph
from app.models import Ticket
from app.settings import settings
from app.tracing import setup_tracing

app = procrastinate.App(
    connector=procrastinate.PsycopgConnector(conninfo=settings.database_url),
)

# The LangGraph checkpointer talks to psycopg directly (not through SQLAlchemy), so the worker
# keeps a small psycopg pool for it, with the connection settings it requires.
_checkpoint_pool: AsyncConnectionPool | None = None


async def checkpointer() -> AsyncPostgresSaver:
    global _checkpoint_pool
    if _checkpoint_pool is None:
        _checkpoint_pool = AsyncConnectionPool(
            settings.database_url,
            open=False,
            max_size=4,
            kwargs={"autocommit": True, "row_factory": dict_row, "prepare_threshold": 0},
        )
        await _checkpoint_pool.open(wait=True)
    return AsyncPostgresSaver(_checkpoint_pool, serde=checkpoint_serde())


async def close_checkpointer() -> None:
    global _checkpoint_pool
    if _checkpoint_pool is not None:
        await _checkpoint_pool.close()
        _checkpoint_pool = None


def _sink(ticket_id: str):
    async def sink(event: Event) -> None:
        await db.record_event(ticket_id, event)
        if isinstance(event, JevEvent):  # legacy event name; show lane and severity immediately
            answers = {a.question: a.answer for a in event.answers}
            await db.update_ticket(
                ticket_id, lane=answers.get("ticket_type"), severity=answers.get("severity")
            )

    return sink


async def _drive(ticket_id: str, graph_input, seen: set[str] | None = None) -> None:
    setup_tracing()  # here, not at import: the API and tests import this module too
    graph = build_graph(await checkpointer())
    await db.update_ticket(ticket_id, status="running")
    try:
        paused = await run_graph(graph, graph_input, ticket_id, _sink(ticket_id), seen)
    except Exception as e:
        await db.record_event(ticket_id, ErrorEvent(message=f"run failed: {e}"))
        await db.update_ticket(ticket_id, status="failed")
        raise
    if paused is not None:
        await db.update_ticket(ticket_id, status="needs_approval")
        return
    state = (await graph.aget_state({"configurable": {"thread_id": ticket_id}})).values
    verdict = state.get("verdict")
    await db.update_ticket(
        ticket_id,
        status="done",
        completed_at=datetime.now(UTC),
        verdict_kind=verdict.kind
        if verdict
        else ("duplicate" if state.get("duplicate_of") else None),
    )


@app.task(name="run_ticket", queue="tickets")
async def run_ticket(ticket_id: str) -> None:
    ticket = Ticket.model_validate(await db.get_ticket(ticket_id), from_attributes=True)
    await _drive(ticket_id, {"ticket": ticket})


@app.task(name="resume_ticket", queue="tickets")
async def resume_ticket(ticket_id: str, decision: dict) -> None:
    await _drive(ticket_id, Command(resume=decision), seen=await db.stages_seen(ticket_id))


async def enqueue_run(ticket_id: str) -> None:
    await run_ticket.configure(lock=ticket_id).defer_async(ticket_id=ticket_id)


async def enqueue_resume(ticket_id: str, decision: dict) -> None:
    await resume_ticket.configure(lock=ticket_id).defer_async(
        ticket_id=ticket_id, decision=decision
    )
