"""Against a real Postgres: migrations, queries, the NOTIFY trigger, and the worker end to end.

Run with `make test-db`. It uses a throwaway database whose name must end in `_test`, because
the first thing these tests do is migrate it down to nothing and back up.
"""

import asyncio
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from alembic import command
from sqlalchemy import text, update
from sqlalchemy.engine import make_url

from app import db, tasks
from app.alembic_config import alembic_config
from app.events import JevEvent, StageEvent, ToolCallEvent
from app.migrate import setup_libraries
from app.models import Ticket
from app.settings import settings
from app.tables import DeployRow
from tests.conftest import demo_ticket

pytestmark = pytest.mark.db

TABLES = "tickets, events, verdicts, deploys, flag_changes, investigations, tenants"


@pytest.fixture(scope="module", autouse=True)
def migrated():
    if not (make_url(settings.database_url).database or "").endswith("_test"):
        pytest.fail("DATABASE_URL must name a database ending in _test (make test-db)")
    cfg = alembic_config()
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")  # the downgrade works too...
    command.upgrade(cfg, "head")  # ...and upgrading again from nothing
    asyncio.run(setup_libraries())  # queue and checkpoint tables


@pytest.fixture(autouse=True)
async def clean():
    async with db.Session.begin() as s:
        await s.execute(text(f"TRUNCATE {TABLES} CASCADE"))
    await db.upsert_tenant("figma-merch", "Figma Merch Store", "figma-shopper")
    yield
    await tasks.close_checkpointer()
    await db.engine.dispose()  # each test has its own event loop


def ticket(n: str, id: str | None = None) -> Ticket:
    return demo_ticket(n).model_copy(update={"id": id or f"T-{n}"})


def test_models_match_migrations():
    command.check(alembic_config())  # raises if app/tables.py has changes with no migration


async def test_ticket_row_lifecycle():
    t = ticket("4")
    assert await db.insert_ticket(t, raw={"id": t.id}) is True
    assert await db.insert_ticket(t) is False  # redelivery is ignored

    await db.record_event(t.id, StageEvent(stage="context", status="running"))
    await db.record_event(t.id, StageEvent(stage="context", status="done", summary="ok"))
    await db.record_event(t.id, StageEvent(stage="enrich", status="running"))
    await db.update_ticket(t.id, status="running", lane="tech_issue", severity=2)
    await db.add_cost(t.id, 0.0123)

    row = await db.get_ticket(t.id)
    assert (row.status, row.current_stage, row.stages_done) == ("running", "enrich", 1)
    assert (row.lane, row.severity, float(row.cost_usd)) == ("tech_issue", 2, 0.0123)
    assert [r.id for r in await db.list_tickets("running")] == [t.id]
    assert await db.list_tickets("done") == []

    events = await db.list_events(t.id)
    assert [e.event.status for e in events] == ["running", "done", "running"]
    assert isinstance(events[1].event, StageEvent) and events[1].event.summary == "ok"
    assert await db.list_events(t.id, after_id=events[1].id) == events[2:]
    assert await db.stages_seen(t.id) == {"context", "enrich"}


async def test_status_is_constrained():
    t = ticket("1")
    await db.insert_ticket(t)
    with pytest.raises(Exception, match="ck_tickets_status"):
        await db.update_ticket(t.id, status="banana")


async def test_fetch_context_keeps_last_24_hours():
    await db.insert_deploy("payment", "v1.4.0", "v1.3.0", "a1b2c3d", ["refactor: expiry check"])
    old = await db.insert_deploy("quote", "v1.2.0", "v1.1.0", "0ld", [])
    async with db.Session.begin() as s:
        await s.execute(
            update(DeployRow)
            .where(DeployRow.id == old.id)
            .values(deployed_at=datetime.now(UTC) - timedelta(days=3))
        )
    await db.insert_flag_change("paymentFailure", "off", "25%")
    await db.insert_ticket(ticket("3"))
    t = ticket("4")
    await db.insert_ticket(t)

    ctx = await db.fetch_context(t, services={"payment": "Payments team"})
    assert [d.version for d in ctx.deploys] == ["v1.4.0"]
    assert ctx.deploys[0].commit_titles == ["refactor: expiry check"]
    assert ctx.flag_changes[0].new_variant == "25%"
    assert ctx.tenant["name"] == "Figma Merch Store"
    assert [r["id"] for r in ctx.recent_tickets] == ["T-3"]


async def test_insert_notifies_listeners():
    t = ticket("2")
    await db.insert_ticket(t)
    async with await psycopg.AsyncConnection.connect(settings.database_url, autocommit=True) as c:
        await c.execute("LISTEN ticket_events")
        event_id = await db.record_event(t.id, StageEvent(stage="context", status="running"))
        note = await anext(c.notifies(timeout=5))
    assert note.payload == f"{t.id}:{event_id}"


async def test_worker_runs_pauses_and_resumes():
    # A request goes straight through.
    t2 = ticket("2", "T-W2")
    await db.insert_ticket(t2)
    await tasks.run_ticket(t2.id)
    row = await db.get_ticket(t2.id)
    assert (row.status, row.lane, row.verdict_kind) == ("done", "request", None)
    assert row.completed_at is not None

    # A tech issue pauses for approval, then resumes from its Postgres checkpoint.
    t4 = ticket("4", "T-W4")
    await db.insert_ticket(t4)
    await tasks.run_ticket(t4.id)
    row = await db.get_ticket(t4.id)
    assert (row.status, row.current_stage, row.lane) == ("needs_approval", "approve", "tech_issue")
    events = [e.event for e in await db.list_events(t4.id)]
    assert any(isinstance(e, JevEvent) for e in events)
    assert any(isinstance(e, ToolCallEvent) and e.stage == "data_analyst" for e in events)
    assert events[-1].kind == "approval_required"

    await tasks.resume_ticket(t4.id, {"approved": True, "edited_reply": "We're on it."})
    row = await db.get_ticket(t4.id)
    assert (row.status, row.verdict_kind) == ("done", "inconclusive")
    stages = [e.event for e in await db.list_events(t4.id) if e.event.kind == "stage"]
    assert {e.stage for e in stages if e.status == "skipped"} == {"layer1", "requests", "layer3"}
