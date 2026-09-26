"""Our tables, as SQLAlchemy 2.0 models. Alembic generates migrations from these (db/migrations).

Procrastinate's queue tables and LangGraph's checkpoint tables live in the same database but
belong to those libraries: they aren't modelled here and Alembic leaves them alone.
Classes end in `Row` to keep them apart from the Pydantic models in app/models.py.
"""

from datetime import datetime
from decimal import Decimal
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    MetaData,
    Numeric,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

EMBEDDING_DIM = 384  # bge-small-en-v1.5


class Base(DeclarativeBase):
    metadata = MetaData(
        naming_convention={  # stable constraint names, so migrations can drop them by name
            "ix": "ix_%(table_name)s_%(column_0_N_name)s",
            "uq": "uq_%(table_name)s_%(column_0_N_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )
    type_annotation_map = {
        str: Text,
        datetime: DateTime(timezone=True),
        dict[str, Any]: JSONB,
        list[str]: ARRAY(Text),
    }


def created_at() -> Mapped[datetime]:
    return mapped_column(server_default=func.now())


# --- tenants and tickets ----------------------------------------------------------------------


class TenantRow(Base):
    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(primary_key=True)
    name: Mapped[str]
    plan: Mapped[str | None]
    user_prefix: Mapped[str]  # shoppers are <prefix>-01 ... <prefix>-20


class TicketRow(Base):
    __tablename__ = "tickets"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'needs_approval', 'done', 'failed')", name="status"
        ),
        Index(None, "status", "received_at"),
    )

    id: Mapped[str] = mapped_column(primary_key=True)
    tenant_id: Mapped[str | None] = mapped_column(ForeignKey("tenants.id"))
    source: Mapped[str] = mapped_column(server_default="pylon")
    subject: Mapped[str]
    body: Mapped[str]
    requester: Mapped[str | None]
    received_at: Mapped[datetime] = created_at()
    status: Mapped[str] = mapped_column(server_default="queued")
    lane: Mapped[str | None]  # how_to | request | tech_issue
    current_stage: Mapped[str | None]
    stages_done: Mapped[int] = mapped_column(server_default="0")
    severity: Mapped[int | None]
    verdict_kind: Mapped[str | None]
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(10, 4), server_default="0")
    completed_at: Mapped[datetime | None]
    raw: Mapped[dict[str, Any] | None]  # the webhook payload as delivered


class EventRow(Base):
    """Every event the console shows. A trigger (see the initial migration) NOTIFYs
    `ticket_events` with "<ticket_id>:<event id>" on each insert, for the SSE stream."""

    __tablename__ = "events"
    __table_args__ = (Index(None, "ticket_id", "id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ticket_id: Mapped[str] = mapped_column(ForeignKey("tickets.id", ondelete="CASCADE"))
    ts: Mapped[datetime] = created_at()
    kind: Mapped[str]
    stage: Mapped[str | None]
    payload: Mapped[dict[str, Any]]  # one app.events.Event, as JSON


class VerdictRow(Base):
    __tablename__ = "verdicts"

    ticket_id: Mapped[str] = mapped_column(
        ForeignKey("tickets.id", ondelete="CASCADE"), primary_key=True
    )
    data: Mapped[dict[str, Any]]  # app.models.Verdict
    created_at: Mapped[datetime] = created_at()


# --- deploy and flag history (written by scenarios/deploy.sh and flag.sh) ----------------------


class DeployRow(Base):
    __tablename__ = "deploys"
    __table_args__ = (Index(None, "deployed_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    service: Mapped[str]
    version: Mapped[str]
    previous_version: Mapped[str | None]
    git_sha: Mapped[str | None]
    commit_titles: Mapped[list[str]] = mapped_column(server_default="{}")
    deployed_at: Mapped[datetime] = created_at()


class FlagChangeRow(Base):
    __tablename__ = "flag_changes"
    __table_args__ = (Index(None, "changed_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    flag: Mapped[str]
    old_variant: Mapped[str | None]
    new_variant: Mapped[str | None]
    changed_at: Mapped[datetime] = created_at()


# --- memory of past investigations (phase 6) --------------------------------------------------


class InvestigationRow(Base):
    __tablename__ = "investigations"
    __table_args__ = (
        CheckConstraint("status IN ('open', 'resolved')", name="status"),
        Index(None, "service", "version", "error_signature"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[str | None] = mapped_column(ForeignKey("tickets.id", ondelete="SET NULL"))
    service: Mapped[str | None]
    version: Mapped[str | None]
    error_signature: Mapped[str | None]  # normalized error text
    root_cause: Mapped[str | None]
    file_line: Mapped[str | None]
    linear_issue: Mapped[str | None]
    status: Mapped[str] = mapped_column(server_default="open")
    created_at: Mapped[datetime] = created_at()


# --- retrieval: help-center sections and tickets in one table (phase 3) -----------------------


class RetrievalDocRow(Base):
    __tablename__ = "retrieval_docs"
    __table_args__ = (
        CheckConstraint("kind IN ('help_section', 'ticket')", name="kind"),
        Index(
            None,
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        Index(None, "tsv", postgresql_using="gin"),
        Index(None, "kind", "status"),
    )

    id: Mapped[str] = mapped_column(primary_key=True)  # section slug or ticket ID
    kind: Mapped[str]
    title: Mapped[str | None]
    body: Mapped[str | None]
    summary: Mapped[str | None]
    status: Mapped[str | None]  # tickets: open | resolved
    service: Mapped[str | None]
    version: Mapped[str | None]
    verdict: Mapped[str | None]
    root_cause: Mapped[str | None]
    linear_issue: Mapped[str | None]
    tenant: Mapped[str | None]
    content_hash: Mapped[str | None]  # re-embed only what changed
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))
    tsv: Mapped[Any] = mapped_column(
        TSVECTOR,
        Computed(
            "to_tsvector('english', coalesce(title, '') || ' ' || coalesce(body, '') || ' ' "
            "|| coalesce(summary, ''))",
            persisted=True,
        ),
    )


# --- code index, one set of rows per (service, git_sha) (phase 5) -----------------------------


class CodeSymbolRow(Base):
    __tablename__ = "code_symbols"
    __table_args__ = (Index(None, "git_sha", "name"), Index(None, "service", "git_sha"))

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    service: Mapped[str]
    git_sha: Mapped[str]
    file: Mapped[str]
    line: Mapped[int]
    kind: Mapped[str]  # function | method | class | struct | interface ...
    name: Mapped[str]
    signature: Mapped[str | None]


class ErrorStringRow(Base):
    __tablename__ = "error_strings"
    __table_args__ = (Index(None, "git_sha"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    service: Mapped[str]
    git_sha: Mapped[str]
    file: Mapped[str]
    line: Mapped[int]
    text: Mapped[str]


class RpcMapRow(Base):
    __tablename__ = "rpc_map"
    __table_args__ = (Index(None, "git_sha", "method"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    git_sha: Mapped[str]
    method: Mapped[str]  # Service/Method
    service: Mapped[str]
    handler_file: Mapped[str]
    handler_line: Mapped[int]


class FlagReadRow(Base):
    __tablename__ = "flag_reads"
    __table_args__ = (Index(None, "git_sha", "flag"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    service: Mapped[str]
    git_sha: Mapped[str]
    flag: Mapped[str]
    file: Mapped[str]
    line: Mapped[int]


class ServiceCardRow(Base):
    __tablename__ = "service_cards"

    service: Mapped[str] = mapped_column(primary_key=True)
    git_sha: Mapped[str] = mapped_column(primary_key=True)
    card: Mapped[str]
    created_at: Mapped[datetime] = created_at()


# --- evals (phase 9) --------------------------------------------------------------------------


class EvalResultRow(Base):
    __tablename__ = "eval_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_at: Mapped[datetime] = created_at()
    profile: Mapped[str | None]
    role: Mapped[str | None]
    model: Mapped[str | None]
    with_retrieval: Mapped[bool | None]
    routing_accuracy: Mapped[float | None]
    verdict_accuracy: Mapped[float | None]
    retrieval_hit_rate: Mapped[float | None]
    cost_per_ticket: Mapped[float | None]
    p50_latency_s: Mapped[float | None]
