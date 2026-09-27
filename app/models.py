"""Domain models shared by the graph nodes. Each LLM call returns one (Pydantic AI output_type)."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

Lane = Literal["how_to", "request", "tech_issue"]


class Ticket(BaseModel):
    id: str
    tenant_id: str | None = None
    subject: str
    body: str
    requester: str | None = None
    received_at: datetime | None = None
    pylon_issue_id: str | None = None  # absent for simulator tickets
    pylon_message_id: str | None = None  # optional top-level customer-visible message ID


# --- context (code, no LLM) -------------------------------------------------------------------


class Deploy(BaseModel):
    id: int
    service: str
    version: str
    previous_version: str | None = None
    git_sha: str | None = None
    commit_titles: list[str] = []
    deployed_at: datetime


class FlagChange(BaseModel):
    id: int
    flag: str
    old_variant: str | None = None
    new_variant: str | None = None
    changed_at: datetime


class ContextBundle(BaseModel):
    tenant: dict = {}
    recent_tickets: list[dict] = []
    deploys: list[Deploy] = []  # last 24 h
    flag_changes: list[FlagChange] = []  # last 24 h
    incidents: list[dict] = []
    services: dict[str, str] = {}  # service -> one-line description (ownership.yaml keys)


# --- enrichment (one LLM call, then validation) -----------------------------------------------


class Enrichment(BaseModel):
    identifiers: dict[str, list[str]] = {}  # order_ids, session_ids, card_last4, emails
    window_start: datetime
    window_end: datetime
    window_basis: str  # the phrase it came from, e.g. "since this morning"
    symptom: str
    likely_services: list[str] = []  # names from ownership.yaml, most likely first
    relevant_changes: list[str] = []  # "deploy:<id>" or "flag:<id>" from the context bundle
    missing: list[str] = []  # what to ask the customer if nothing is identifiable


# --- retrieval --------------------------------------------------------------------------------


class Retrieved(BaseModel):
    kind: Literal["help_section", "ticket"]
    id: str  # section slug or ticket ID
    title: str
    text: str
    status: Literal["open", "resolved"] | None = None  # tickets only
    score: float


# --- categorization ---------------------------------------------------------------------------


class JevAnswer(BaseModel):
    question: str  # ticket_type | service | severity | revenue_blocking
    answer: str | int | bool
    confidence: float


class Classification(BaseModel):
    ticket_type: Lane
    ticket_type_confidence: float
    service: str  # ownership.yaml key or "other"
    severity: int = Field(ge=1, le=4)
    revenue_blocking: bool
    revenue_blocking_confidence: float
    source: Literal["jev", "llm", "llm_fallback", "stub"] = "llm"
    needs_human: bool = False
    answers: list[JevAnswer] = []


# --- Layer 1 and request triage (one LLM call each) -------------------------------------------


class Layer1Answer(BaseModel):
    answer: str
    cited_ids: list[str]  # must be IDs from the Retrieved list
    confident: bool


class RequestTriage(BaseModel):
    kind: Literal["feature", "billing", "account"]
    summary: str
    roadmap_tag: str | None = None
    acknowledgement: str


# --- Layer 2 ----------------------------------------------------------------------------------


class DuplicateCheck(BaseModel):
    new_problem: str = Field(description="the new ticket's symptom: what fails, how, for whom")
    closest_problem: str = Field(description="the closest open ticket's symptom, the same way")
    same_problem: bool
    ticket_id: str | None = Field(None, description="the open ticket it repeats, from the list")
    reason: str


class Brief(BaseModel):
    text: str  # identifiers, window, suspected service, customer words
    suspected_service: str
    deployed_version: str  # the fork tag the service runs now
    previous_version: str | None = None  # the tag before its last deploy, if recent
    past_investigations: list[str] = []  # hypotheses to check, never facts


class ToolRecord(BaseModel):
    """One tool call or shell command an analyst made, as it happened: what evidence may cite."""

    call_id: str
    provider_call_id: str | None = None  # HolmesGPT's original ID, if its answer cites it
    tool: str  # a HolmesGPT tool name, or "bash" for the codebox
    args: dict[str, Any] = {}
    output: str = ""
    ok: bool = True  # False when the call failed: it shows nothing


class Evidence(BaseModel):
    source: Literal["trace", "metric", "log", "sql", "deploy", "flag", "code", "git"]
    ref: str  # trace id, PromQL, file:line, commit sha
    observation: str
    call_id: str | None = None  # the tool call it came from (checked in findings.py)


class CodeSnippet(BaseModel):
    """A short excerpt copied from a codebox call, with its file, lines and call ID."""

    render: Literal["code", "diff"]
    file: str
    language: str
    start_line: int
    end_line: int
    content: str
    call_id: str


class Findings(BaseModel):
    agent: Literal["data_analyst", "codebase_analyst"]
    hypothesis: str
    evidence: list[Evidence]
    code_snippets: list[CodeSnippet] = []  # filled in code from checked evidence, not model claims
    confidence: float
    round: int = 1
    error_text: str | None = None  # the exact error message it saw in a tool's output
    intended: bool | None = (
        None  # codebase analyst: the code it cites is intended (or a regression)
    )
    completed: bool = True  # False when the run hit its time or call budget


class Verdict(BaseModel):
    kind: Literal["false_positive", "confirmed_bug", "config_incident", "inconclusive"]
    root_cause: str
    owning_service: str
    confidence: float
    customer_reply: str
    engineering_summary: str | None = None
    file_line: str | None = None  # where the behaviour comes from, from code evidence
    commit: str | None = None  # the commit that introduced it, from git evidence


# --- approval ---------------------------------------------------------------------------------


class ApprovalDecision(BaseModel):
    approved: bool = True
    edited_reply: str | None = None
    reviewer: str | None = None
