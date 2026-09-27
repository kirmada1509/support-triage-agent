"""Events the console renders: one discriminated union, so OpenAPI -> TypeScript is exact.

The backend does the shaping: code arrives as file/language/lines, never as raw grep output.
"""

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, TypeAdapter

from app.models import JevAnswer, Retrieved

# --- tool-call outputs, discriminated by `render` ---------------------------------------------


class CodeOut(BaseModel):
    render: Literal["code"] = "code"
    file: str
    language: str
    start_line: int = 1
    code: str
    highlight: list[int] = []


class DiffOut(BaseModel):
    render: Literal["diff"] = "diff"
    file: str | None = None
    from_ref: str | None = None
    to_ref: str | None = None
    diff: str


class TerminalOut(BaseModel):
    render: Literal["terminal"] = "terminal"
    command: str
    output: str
    exit_code: int = 0


class CommitOut(BaseModel):
    render: Literal["commit"] = "commit"
    sha: str
    title: str
    author: str | None = None
    date: datetime | None = None
    files: list[str] = []


class LogOut(BaseModel):
    render: Literal["log"] = "log"
    source: str  # e.g. "opensearch otel-logs"
    lines: list[str]


class SeriesPoint(BaseModel):
    ts: datetime
    value: float


class Series(BaseModel):
    name: str  # e.g. 'service.version="v1.4.0"'
    points: list[SeriesPoint]


class SeriesOut(BaseModel):
    render: Literal["series"] = "series"
    query: str  # PromQL
    unit: str | None = None
    series: list[Series]


class Span(BaseModel):
    span_id: str
    parent_id: str | None = None
    service: str
    name: str
    start: datetime
    duration_ms: float
    status: Literal["ok", "error", "unset"] = "unset"
    attributes: dict[str, Any] = {}


class TraceOut(BaseModel):
    render: Literal["trace"] = "trace"
    trace_id: str
    url: str | None = None  # opens the trace in Jaeger
    spans: list[Span]


class TableOut(BaseModel):
    render: Literal["table"] = "table"
    columns: list[str]
    rows: list[list[Any]]


class JsonOut(BaseModel):
    render: Literal["json"] = "json"
    data: Any


Output = Annotated[
    CodeOut
    | DiffOut
    | TerminalOut
    | CommitOut
    | LogOut
    | SeriesOut
    | TraceOut
    | TableOut
    | JsonOut,
    Field(discriminator="render"),
]

# --- events, discriminated by `kind` ----------------------------------------------------------


class StageEvent(BaseModel):
    """Drives the pipeline nodes."""

    kind: Literal["stage"] = "stage"
    stage: str
    status: Literal["waiting", "running", "done", "skipped", "failed"]
    summary: str | None = None
    duration_ms: int | None = None


class ToolCallEvent(BaseModel):
    """One tool call or shell command. Sent twice: status=running, then ok/error with output."""

    kind: Literal["tool_call"] = "tool_call"
    stage: str
    call_id: str
    tool: str  # "jaeger.find_error_traces", "git diff", ...
    args: dict[str, Any] = {}
    status: Literal["running", "ok", "error"]
    duration_ms: int | None = None
    output: Output | None = None


class ModelDeltaEvent(BaseModel):
    kind: Literal["model_delta"] = "model_delta"
    stage: str
    text: str


class ModelOutputEvent(BaseModel):
    """A typed result such as Enrichment or Verdict."""

    kind: Literal["model_output"] = "model_output"
    stage: str
    name: str  # "Enrichment", "Verdict", ...
    data: dict[str, Any]
    model: str | None = None
    cost_usd: float | None = None


class RetrievalEvent(BaseModel):
    kind: Literal["retrieval"] = "retrieval"
    stage: str
    query: str
    results: list[Retrieved]


class JevEvent(BaseModel):
    kind: Literal["jev"] = "jev"
    stage: str
    answers: list[JevAnswer]
    source: Literal["jev", "llm", "llm_fallback", "stub"] = "llm"


class ApprovalRequiredEvent(BaseModel):
    kind: Literal["approval_required"] = "approval_required"
    stage: str = "approve"
    draft_reply: str
    reasons: list[str] = []
    linear_issue: str | None = None


class LinkEvent(BaseModel):
    kind: Literal["link"] = "link"
    stage: str
    label: str  # "Linear PAY-12", "Jaeger trace"
    url: str


class DeliveryEvent(BaseModel):
    """A durable receipt for an external handoff or its local logged fallback."""

    kind: Literal["delivery"] = "delivery"
    stage: str
    destination: Literal["linear", "pylon_reply", "pylon_note"]
    status: Literal["sent", "logged"]
    external_id: str | None = None
    detail: str


class ErrorEvent(BaseModel):
    kind: Literal["error"] = "error"
    stage: str | None = None
    message: str
    traceback: str | None = None


Event = Annotated[
    StageEvent
    | ToolCallEvent
    | ModelDeltaEvent
    | ModelOutputEvent
    | RetrievalEvent
    | JevEvent
    | ApprovalRequiredEvent
    | LinkEvent
    | DeliveryEvent
    | ErrorEvent,
    Field(discriminator="kind"),
]
EventAdapter: TypeAdapter[Event] = TypeAdapter(Event)


class StoredEvent(BaseModel):
    """An event as the API returns it: the row id and timestamp around the payload."""

    id: int
    ticket_id: str
    ts: datetime
    event: Event
