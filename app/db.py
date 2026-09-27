"""Database access for our tables: SQLAlchemy 2.0 async, on the psycopg 3 driver.

Tables are defined in app/tables.py and migrated with Alembic (db/migrations). Two things stay
outside the ORM on purpose: the SSE stream LISTENs on a plain psycopg connection
(api/main.py), and the LangGraph checkpointer and Procrastinate manage their own tables.
"""

from datetime import timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.events import DeliveryEvent, Event, EventAdapter, StageEvent, StoredEvent
from app.models import ContextBundle, Deploy, FlagChange, Ticket
from app.settings import settings
from app.tables import (
    CodeSymbolRow,
    DeployRow,
    ErrorStringRow,
    EvalResultRow,
    EventRow,
    FlagChangeRow,
    FlagReadRow,
    InvestigationRow,
    RpcMapRow,
    ServiceCardRow,
    TenantRow,
    TicketRow,
)

if TYPE_CHECKING:
    from app.indexer.build import CodeIndex

engine = create_async_engine(settings.sqlalchemy_url, pool_pre_ping=True)
Session = async_sessionmaker(engine, expire_on_commit=False)


# --- tenants and tickets ----------------------------------------------------------------------


async def upsert_tenant(id: str, name: str, user_prefix: str, plan: str | None = None) -> None:
    stmt = insert(TenantRow).values(id=id, name=name, user_prefix=user_prefix, plan=plan)
    stmt = stmt.on_conflict_do_update(
        index_elements=[TenantRow.id],
        set_={
            "name": stmt.excluded.name,
            "user_prefix": stmt.excluded.user_prefix,
            "plan": stmt.excluded.plan,
        },
    )
    async with Session.begin() as s:
        await s.execute(stmt)


async def insert_ticket(ticket: Ticket, raw: dict | None = None) -> bool:
    """Store a new ticket. Returns False if the ID already exists (Pylon redelivery)."""
    stmt = (
        insert(TicketRow)
        .values(
            id=ticket.id,
            tenant_id=ticket.tenant_id,
            subject=ticket.subject,
            body=ticket.body,
            requester=ticket.requester,
            raw=raw or {},
        )
        .on_conflict_do_nothing(index_elements=[TicketRow.id])
        .returning(TicketRow.id)  # no row back means it already existed
    )
    async with Session.begin() as s:
        return await s.scalar(stmt) is not None


async def get_ticket(ticket_id: str) -> TicketRow | None:
    async with Session() as s:
        return await s.get(TicketRow, ticket_id)


async def list_tickets(status: str | None = None, limit: int = 200) -> list[TicketRow]:
    stmt = select(TicketRow).order_by(TicketRow.received_at.desc()).limit(limit)
    if status:
        stmt = stmt.where(TicketRow.status == status)
    async with Session() as s:
        return list(await s.scalars(stmt))


async def update_ticket(ticket_id: str, **fields: Any) -> None:
    """Set columns on one ticket, e.g. update_ticket(id, status="done"). Unknown names raise."""
    if fields:
        async with Session.begin() as s:
            await s.execute(update(TicketRow).where(TicketRow.id == ticket_id).values(**fields))


async def add_cost(ticket_id: str, usd: float) -> None:
    async with Session.begin() as s:
        await s.execute(
            update(TicketRow)
            .where(TicketRow.id == ticket_id)
            .values(cost_usd=TicketRow.cost_usd + Decimal(str(usd)))
        )


# --- events -----------------------------------------------------------------------------------


async def record_event(ticket_id: str, event: Event) -> int:
    """Insert one event (a trigger NOTIFYs the SSE stream) and keep the queue row current."""
    row = EventRow(
        ticket_id=ticket_id,
        kind=event.kind,
        stage=getattr(event, "stage", None),
        payload=event.model_dump(mode="json"),
    )
    progress = None
    if isinstance(event, StageEvent) and event.status == "running":
        progress = {"current_stage": event.stage}
    elif isinstance(event, StageEvent) and event.status == "done":
        progress = {"stages_done": TicketRow.stages_done + 1}
    async with Session.begin() as s:
        s.add(row)
        if progress:
            await s.execute(update(TicketRow).where(TicketRow.id == ticket_id).values(**progress))
        await s.flush()
        return row.id


def to_stored(row: EventRow) -> StoredEvent:
    return StoredEvent(
        id=row.id,
        ticket_id=row.ticket_id,
        ts=row.ts,
        event=EventAdapter.validate_python(row.payload),
    )


async def list_events(ticket_id: str, after_id: int = 0) -> list[StoredEvent]:
    stmt = (
        select(EventRow)
        .where(EventRow.ticket_id == ticket_id, EventRow.id > after_id)
        .order_by(EventRow.id)
    )
    async with Session() as s:
        return [to_stored(r) for r in await s.scalars(stmt)]


async def delivery_receipt(ticket_id: str, destination: str) -> DeliveryEvent | None:
    """Return the last successful outbound receipt, including one from a retried graph node."""
    stmt = (
        select(EventRow.payload)
        .where(
            EventRow.ticket_id == ticket_id,
            EventRow.kind == "delivery",
            EventRow.payload["destination"].astext == destination,
            EventRow.payload["status"].astext == "sent",
        )
        .order_by(EventRow.id.desc())
        .limit(1)
    )
    async with Session() as s:
        payload = await s.scalar(stmt)
    return DeliveryEvent.model_validate(payload) if payload else None


async def stages_seen(ticket_id: str) -> set[str]:
    stmt = (
        select(EventRow.stage)
        .distinct()
        .where(EventRow.ticket_id == ticket_id, EventRow.kind == "stage")
    )
    async with Session() as s:
        return set(await s.scalars(stmt))


# --- deploy and flag history ------------------------------------------------------------------


async def insert_deploy(
    service: str,
    version: str,
    previous_version: str | None,
    git_sha: str | None,
    commit_titles: list[str],
) -> DeployRow:
    row = DeployRow(
        service=service,
        version=version,
        previous_version=previous_version,
        git_sha=git_sha,
        commit_titles=commit_titles,
    )
    async with Session.begin() as s:
        s.add(row)
    return row


async def insert_flag_change(flag: str, old_variant: str | None, new_variant: str) -> FlagChangeRow:
    row = FlagChangeRow(flag=flag, old_variant=old_variant, new_variant=new_variant)
    async with Session.begin() as s:
        s.add(row)
    return row


# --- context for the context node -------------------------------------------------------------


async def fetch_context(ticket: Ticket, services: dict[str, str], hours: int = 24) -> ContextBundle:
    since = func.now() - timedelta(hours=hours)
    async with Session() as s:
        tenant = await s.get(TenantRow, ticket.tenant_id) if ticket.tenant_id else None
        recent = await s.scalars(
            select(TicketRow)
            .where(TicketRow.tenant_id == ticket.tenant_id, TicketRow.id != ticket.id)
            .order_by(TicketRow.received_at.desc())
            .limit(3)
        )
        deploys = await s.scalars(
            select(DeployRow)
            .where(DeployRow.deployed_at > since)
            .order_by(DeployRow.deployed_at.desc())
        )
        flags = await s.scalars(
            select(FlagChangeRow)
            .where(FlagChangeRow.changed_at > since)
            .order_by(FlagChangeRow.changed_at.desc())
        )
        incidents = await s.scalars(
            select(InvestigationRow)
            .where(InvestigationRow.status == "open")
            .order_by(InvestigationRow.created_at.desc())
            .limit(10)
        )
        return ContextBundle(
            tenant={
                "id": tenant.id,
                "name": tenant.name,
                "plan": tenant.plan,
                "user_prefix": tenant.user_prefix,
            }
            if tenant
            else {},
            recent_tickets=[
                {
                    "id": t.id,
                    "subject": t.subject,
                    "status": t.status,
                    "lane": t.lane,
                    "verdict_kind": t.verdict_kind,
                    "received_at": t.received_at.isoformat(),
                }
                for t in recent
            ],
            deploys=[Deploy.model_validate(d, from_attributes=True) for d in deploys],
            flag_changes=[FlagChange.model_validate(f, from_attributes=True) for f in flags],
            incidents=[
                {
                    "id": i.id,
                    "service": i.service,
                    "version": i.version,
                    "root_cause": i.root_cause,
                    "linear_issue": i.linear_issue,
                    "created_at": i.created_at.isoformat(),
                }
                for i in incidents
            ],
            services=services,
        )


# --- code index (app/indexer) -----------------------------------------------------------------

_CODE_TABLES = (CodeSymbolRow, ErrorStringRow, RpcMapRow, FlagReadRow)


async def replace_code_index(index: "CodeIndex") -> None:
    """Store a service's index at one commit, replacing only that (service, commit)."""
    key = {"service": index.service, "git_sha": index.git_sha}
    rows: list = [
        CodeSymbolRow(
            **key, file=x.file, line=x.line, kind=x.kind, name=x.name, signature=x.signature
        )
        for x in index.symbols
    ]
    rows += [ErrorStringRow(**key, file=x.file, line=x.line, text=x.text) for x in index.errors]
    rows += [
        RpcMapRow(**key, method=x.method, handler_file=x.file, handler_line=x.line)
        for x in index.rpcs
    ]
    rows += [FlagReadRow(**key, flag=x.flag, file=x.file, line=x.line) for x in index.flags]
    async with Session.begin() as s:
        for table in _CODE_TABLES:
            await s.execute(
                delete(table).where(table.service == index.service, table.git_sha == index.git_sha)
            )
        s.add_all(rows)


async def code_index_exists(service: str, git_sha: str) -> bool:
    async with Session() as s:
        found = await s.scalar(
            select(CodeSymbolRow.id)
            .where(CodeSymbolRow.service == service, CodeSymbolRow.git_sha == git_sha)
            .limit(1)
        )
        return found is not None


async def load_code_index(git_sha: str) -> list["CodeIndex"]:
    """Every service indexed at a commit (without source files)."""
    from app.indexer import extract
    from app.indexer.build import CodeIndex

    indexes: dict[str, CodeIndex] = {}

    def get(service: str) -> CodeIndex:
        return indexes.setdefault(service, CodeIndex(service, git_sha))

    async with Session() as s:
        for r in await s.scalars(
            select(CodeSymbolRow)
            .where(CodeSymbolRow.git_sha == git_sha)
            .order_by(CodeSymbolRow.file, CodeSymbolRow.line)
        ):
            get(r.service).symbols.append(
                extract.Symbol(r.file, r.line, r.kind, r.name, r.signature or r.name)
            )
        for r in await s.scalars(
            select(ErrorStringRow)
            .where(ErrorStringRow.git_sha == git_sha)
            .order_by(ErrorStringRow.file, ErrorStringRow.line)
        ):
            get(r.service).errors.append(extract.ErrorString(r.file, r.line, r.text))
        for r in await s.scalars(
            select(RpcMapRow).where(RpcMapRow.git_sha == git_sha).order_by(RpcMapRow.method)
        ):
            get(r.service).rpcs.append(extract.Rpc(r.method, r.handler_file, r.handler_line))
        for r in await s.scalars(
            select(FlagReadRow)
            .where(FlagReadRow.git_sha == git_sha)
            .order_by(FlagReadRow.file, FlagReadRow.line)
        ):
            get(r.service).flags.append(extract.FlagRead(r.file, r.line, r.flag))
    return [indexes[k] for k in sorted(indexes)]


async def service_cards(git_sha: str) -> dict[str, str]:
    async with Session() as s:
        rows = await s.scalars(select(ServiceCardRow).where(ServiceCardRow.git_sha == git_sha))
        return {r.service: r.card for r in rows}


async def save_service_card(service: str, git_sha: str, card: str) -> None:
    stmt = insert(ServiceCardRow).values(service=service, git_sha=git_sha, card=card)
    stmt = stmt.on_conflict_do_update(
        index_elements=[ServiceCardRow.service, ServiceCardRow.git_sha],
        set_={"card": stmt.excluded.card},
    )
    async with Session.begin() as s:
        await s.execute(stmt)


# --- investigations (Layer 2 verdicts, for duplicate checks) ---------------------------------


async def add_investigation(**fields: Any) -> int:
    async with Session.begin() as s:
        row = InvestigationRow(**fields)
        s.add(row)
        await s.flush()
        return row.id


async def open_investigations(service: str, version: str | None = None) -> list[InvestigationRow]:
    """Open investigations of a service, at that version when one is given."""
    query = select(InvestigationRow).where(
        InvestigationRow.service == service, InvestigationRow.status == "open"
    )
    if version:
        query = query.where(InvestigationRow.version == version)
    async with Session() as s:
        return list(await s.scalars(query.order_by(InvestigationRow.created_at.desc())))


# --- evals ------------------------------------------------------------------------------------


async def list_eval_results(limit: int = 100) -> list[EvalResultRow]:
    async with Session() as s:
        return list(
            await s.scalars(
                select(EvalResultRow).order_by(EvalResultRow.run_at.desc()).limit(limit)
            )
        )
