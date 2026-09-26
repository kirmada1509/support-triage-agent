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
from app.events import JevEvent, ModelOutputEvent, StageEvent, ToolCallEvent
from app.history_access import history_url_for_database, setup_history_reader
from app.migrate import setup_libraries
from app.models import Enrichment, RequestTriage, Ticket
from app.nodes import enrich, jev, requests, retrieve
from app.retrieval.chunk import HelpSection, content_hash
from app.retrieval.index import index_help, index_tickets
from app.retrieval.search import search
from app.settings import settings
from app.tables import DeployRow
from tests.conftest import demo_ticket

pytestmark = pytest.mark.db

TABLES = (
    "tickets, events, verdicts, deploys, flag_changes, investigations, tenants, retrieval_docs, "
    "code_symbols, error_strings, rpc_map, flag_reads, service_cards"
)


@pytest.fixture(scope="module", autouse=True)
def migrated():
    if not (make_url(settings.database_url).database or "").endswith("_test"):
        pytest.fail("DATABASE_URL must name a database ending in _test (make test-db)")
    cfg = alembic_config()
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")  # the downgrade works too...
    command.upgrade(cfg, "head")  # ...and upgrading again from nothing
    asyncio.run(setup_history_reader())
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


class FakeEmbeddings:
    def __init__(self):
        self.documents: list[str] = []

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.documents.extend(texts)
        return [self._vector(text) for text in texts]

    async def embed_query(self, text: str) -> list[float]:
        return self._vector(text)

    @staticmethod
    def _vector(text: str) -> list[float]:
        v = [0.0] * 384
        v[0 if any(word in text.lower() for word in ("card", "visa")) else 1] = 1.0
        return v


async def test_retrieval_index_only_embeds_changed_text_and_updates_metadata():
    embedder = FakeEmbeddings()
    section = HelpSection(
        id="payment-cards#accepted-cards",
        title="Payment cards — Accepted cards",
        body="Payment cards\nAccepted cards\nVisa and Mastercard are accepted.",
        content_hash=content_hash(
            "Payment cards\nAccepted cards\nVisa and Mastercard are accepted."
        ),
    )
    assert await index_help([section], embedder) == 1
    assert await index_help([section], embedder) == 0
    assert len(embedder.documents) == 1
    changed = section.__class__(
        id=section.id,
        title=section.title,
        body=section.body + " American Express is not accepted.",
        content_hash=content_hash(section.body + " American Express is not accepted."),
    )
    assert await index_help([changed], embedder) == 1
    assert len(embedder.documents) == 2
    ticket = {
        "id": "SYN-01-01",
        "subject": "Which cards?",
        "body": "Is Visa accepted?",
        "summary": "Visa accepted",
        "status": "open",
        "service": "payment",
        "version": None,
        "verdict": None,
        "root_cause": None,
        "linear_issue": None,
        "tenant": "synthetic",
    }
    assert await index_tickets([ticket], embedder) == 1
    ticket["status"] = "resolved"
    assert await index_tickets([ticket], embedder) == 0
    assert len(embedder.documents) == 3
    async with db.Session() as session:
        assert (
            await session.scalar(text("SELECT status FROM retrieval_docs WHERE id = 'SYN-01-01'"))
            == "resolved"
        )


async def test_hybrid_search_filters_before_ranking():
    embedder = FakeEmbeddings()
    await index_help(
        [
            HelpSection("cards#accepted", "Accepted cards", "Visa Mastercard payment cards", "h1"),
            HelpSection("shipping#quote", "Shipping quotes", "Shipping quote for items", "h2"),
        ],
        embedder,
    )
    tickets = [
        {
            "id": id,
            "subject": subject,
            "body": subject,
            "summary": subject,
            "status": status,
            "service": service,
            "version": None,
            "verdict": None,
            "root_cause": None,
            "linear_issue": None,
            "tenant": "synthetic",
        }
        for id, subject, status, service in (
            ("pay-open", "Visa card rejected", "open", "payment"),
            ("pay-closed", "Visa card rejected", "resolved", "payment"),
            ("quote-open", "Shipping cost rejected", "open", "quote"),
        )
    ]
    await index_tickets(tickets, embedder)
    help_hits = await search("Which Visa cards?", embedder, kind="help_section", limit=5)
    assert help_hits[0].id == "cards#accepted"
    open_hits = await search(
        "Visa card rejected",
        embedder,
        kind="ticket",
        status="open",
        services=["payment"],
        limit=3,
    )
    assert [hit.id for hit in open_hits] == ["pay-open"]


async def test_history_reader_can_only_select_history():
    await db.insert_deploy("payment", "v1.4.0", "v1.3.0", None, [])
    url = history_url_for_database(settings.database_url)
    async with await psycopg.AsyncConnection.connect(url) as conn:
        service = await (await conn.execute("SELECT service FROM deploys")).fetchone()
        assert service == ("payment",)
        assert (await (await conn.execute("SELECT count(*) FROM flag_changes")).fetchone()) == (0,)
    for statement in ("SELECT id FROM tickets", "UPDATE deploys SET version = 'pwned'"):
        with pytest.raises(psycopg.Error):
            async with await psycopg.AsyncConnection.connect(url) as conn:
                await conn.execute(statement)
    async with await psycopg.AsyncConnection.connect(url, autocommit=True) as conn:
        await conn.execute("SET default_transaction_read_only = off")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            await conn.execute("UPDATE deploys SET version = 'pwned'")
    async with db.Session() as session:
        assert (await session.scalar(text("SELECT version FROM deploys LIMIT 1"))) == "v1.4.0"


async def test_code_index_is_stored_per_service_and_commit():
    from tests.test_indexer import payment_index

    index = payment_index()
    other = payment_index()
    other.git_sha = "e" * 40
    assert not await db.code_index_exists("payment", index.git_sha)
    await db.replace_code_index(index)
    await db.replace_code_index(other)
    await db.replace_code_index(index)  # replacing keeps one copy
    assert await db.code_index_exists("payment", index.git_sha)
    [loaded] = await db.load_code_index(index.git_sha)
    assert (loaded.service, loaded.git_sha) == ("payment", index.git_sha)
    assert sorted(loaded.symbols, key=lambda s: (s.file, s.line)) == sorted(
        index.symbols, key=lambda s: (s.file, s.line)
    )
    assert sorted(loaded.errors, key=lambda e: (e.file, e.line)) == sorted(
        index.errors, key=lambda e: (e.file, e.line)
    )
    assert loaded.rpcs == index.rpcs and loaded.flags == index.flags
    assert len(await db.load_code_index(other.git_sha)) == 1

    await db.save_service_card("payment", index.git_sha, "# first")
    await db.save_service_card("payment", index.git_sha, "# second")
    assert await db.service_cards(index.git_sha) == {"payment": "# second"}
    assert await db.service_cards(other.git_sha) == {}


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


async def test_worker_runs_pauses_and_resumes(monkeypatch, layer2_fakes):
    def is_request_ticket(prompt):
        return '"id":"T-W2"' in prompt.split("Ticket: ", 1)[1].split("\n", 1)[0]

    async def fake_enrich(role, output_type, prompt):
        source = ticket("2") if is_request_ticket(prompt) else ticket("4")
        end = source.received_at
        return Enrichment(
            window_start=end - timedelta(hours=3),
            window_end=end,
            window_basis="test",
            symptom=source.subject,
        ), "fake-model"

    async def fake_classify(role, output_type, prompt):
        request = is_request_ticket(prompt)
        return jev.Categorization(
            ticket_type="request" if request else "tech_issue",
            ticket_type_confidence=0.9,
            service="checkout" if request else "payment",
            service_confidence=0.9,
            severity=3,
            severity_confidence=0.8,
            revenue_blocking=not request,
            revenue_blocking_confidence=0.9,
        ), "fake-model"

    async def fake_request(role, output_type, prompt):
        return RequestTriage(
            kind="feature", summary="Apple Pay", acknowledgement="Thanks for the suggestion."
        ), "fake-model"

    async def no_hits(query, embedder, **kwargs):
        return []

    monkeypatch.setattr(enrich, "call", fake_enrich)
    monkeypatch.setattr(jev, "call", fake_classify)
    monkeypatch.setattr(requests, "call", fake_request)
    monkeypatch.setattr(retrieve, "search", no_hits)
    monkeypatch.setattr(retrieve, "embedder", lambda: None)
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


async def test_the_worker_adds_up_model_costs():
    t = ticket("4")
    await db.insert_ticket(t)
    sink = tasks._sink(t.id)
    await sink(ModelOutputEvent(stage="data_analyst", name="Findings", data={}, cost_usd=0.04))
    await sink(ModelOutputEvent(stage="codebase_analyst", name="Findings", data={}, cost_usd=0.002))
    await sink(ModelOutputEvent(stage="verdict", name="Verdict", data={}))
    assert float((await db.get_ticket(t.id)).cost_usd) == 0.042


async def test_open_investigations_by_service_and_version():
    for n in ("4", "5"):
        await db.insert_ticket(ticket(n))
    await db.add_investigation(
        ticket_id="T-4",
        service="payment",
        version="v1.4.0",
        error_signature="expired",
        status="open",
    )
    await db.add_investigation(
        ticket_id="T-5", service="payment", version="v1.4.0", status="resolved"
    )
    await db.add_investigation(service="quote", version="v1.4.0", status="open")
    assert [r.ticket_id for r in await db.open_investigations("payment", "v1.4.0")] == ["T-4"]
    assert await db.open_investigations("payment", "v1.3.0") == []
    assert len(await db.open_investigations("payment")) == 1
