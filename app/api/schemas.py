"""Request and response models for the console API (they become lib/schema.d.ts in web/)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, computed_field

from app.events import ApprovalRequiredEvent, JevEvent, LinkEvent
from app.graph.build import stage_count


class PylonTicketIn(BaseModel):
    """What the (simulated) Pylon webhook delivers."""

    id: str
    tenant_id: str | None = None
    subject: str
    body: str
    requester: str | None = None


TicketStatus = Literal["queued", "running", "needs_approval", "done", "failed"]


class TicketSummary(BaseModel):
    """One row of the queue. Built straight from a TicketRow (from_attributes)."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str | None
    subject: str
    requester: str | None
    received_at: datetime
    status: TicketStatus
    lane: str | None
    current_stage: str | None
    stages_done: int
    severity: int | None
    verdict_kind: str | None
    cost_usd: float
    completed_at: datetime | None

    @computed_field
    @property
    def stages_total(self) -> int:
        return stage_count()


class TicketDetail(TicketSummary):
    body: str
    jev: JevEvent | None = None
    links: list[LinkEvent] = []
    pending_approval: ApprovalRequiredEvent | None = None


class Position(BaseModel):
    x: float
    y: float


class PipelineNode(BaseModel):
    id: str
    label: str
    position: Position


class PipelineEdge(BaseModel):
    id: str
    source: str
    target: str
    conditional: bool


class Pipeline(BaseModel):
    nodes: list[PipelineNode]
    edges: list[PipelineEdge]


class SimulatorTemplate(BaseModel):
    id: str
    title: str
    subject: str
    body: str
    expected_route: str | None = None
    setup: str | None = None


class SimulatorTicketIn(BaseModel):
    template_id: str | None = None
    subject: str | None = None
    body: str | None = None
    tenant_id: str = "figma-merch"
    requester: str | None = "ops@figma-merch.example"


class ScorecardEntry(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    run_at: datetime
    profile: str | None
    role: str | None
    model: str | None
    with_retrieval: bool | None
    routing_accuracy: float | None
    verdict_accuracy: float | None
    retrieval_hit_rate: float | None
    cost_per_ticket: float | None
    p50_latency_s: float | None
