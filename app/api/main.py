"""FastAPI: the Pylon webhook and the Triage Console's endpoints (including the SSE stream)."""

import asyncio
import hashlib
import hmac
import json
import uuid
from contextlib import asynccontextmanager
from functools import cache

import httpx
import psycopg
import yaml
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette import EventSourceResponse, ServerSentEvent

from app import db
from app.api.schemas import (
    Pipeline,
    PylonTicketIn,
    ScorecardEntry,
    SimulatorTemplate,
    SimulatorTicketIn,
    TicketDetail,
    TicketStatus,
    TicketSummary,
)
from app.events import ApprovalRequiredEvent, JevEvent, LinkEvent, OutcomeEvent, StoredEvent
from app.graph.build import pipeline_shape
from app.models import ApprovalDecision, Ticket
from app.settings import ROOT, settings
from app.tasks import app as procrastinate_app
from app.tasks import enqueue_resume, enqueue_run


@asynccontextmanager
async def lifespan(_: FastAPI):
    async with procrastinate_app.open_async():
        yield
    await db.engine.dispose()


api = FastAPI(title="Support Triage Agent", lifespan=lifespan)
app = api  # uvicorn app.api.main:app
api.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- intake -----------------------------------------------------------------------------------


def sign(body: bytes) -> str:
    return hmac.new(settings.pylon_webhook_secret.encode(), body, hashlib.sha256).hexdigest()


@api.post("/webhooks/pylon", status_code=200)
async def pylon_webhook(request: Request) -> dict:
    """Check the HMAC, store the ticket, queue its run. Returns fast: Pylon retries slow calls."""
    body = await request.body()
    if not hmac.compare_digest(sign(body), request.headers.get("x-pylon-signature", "")):
        raise HTTPException(401, "bad signature")
    data = PylonTicketIn.model_validate_json(body)
    ticket = Ticket(**data.model_dump())
    if await db.insert_ticket(ticket, raw=json.loads(body)):
        await enqueue_run(ticket.id)
    return {"ok": True, "ticket_id": ticket.id}


# --- queue and ticket -------------------------------------------------------------------------


@api.get("/tickets")
async def list_tickets(status: TicketStatus | None = None) -> list[TicketSummary]:
    return [TicketSummary.model_validate(r) for r in await db.list_tickets(status)]


@api.get("/tickets/{ticket_id}")
async def get_ticket(ticket_id: str) -> TicketDetail:
    row = await db.get_ticket(ticket_id)
    if row is None:
        raise HTTPException(404)
    events = [e.event for e in await db.list_events(ticket_id)]
    detail = TicketDetail.model_validate(row)
    detail.jev = next((e for e in reversed(events) if isinstance(e, JevEvent)), None)
    detail.links = [e for e in events if isinstance(e, LinkEvent)]
    detail.outcome = next((e for e in reversed(events) if isinstance(e, OutcomeEvent)), None)
    if row.status == "needs_approval":
        detail.pending_approval = next(
            (e for e in reversed(events) if isinstance(e, ApprovalRequiredEvent)), None
        )
    return detail


@api.get("/pipeline")
async def get_pipeline() -> Pipeline:
    return Pipeline.model_validate(pipeline_shape())


@api.post("/tickets/{ticket_id}/approve", status_code=202)
async def approve(ticket_id: str, decision: ApprovalDecision) -> dict:
    row = await db.get_ticket(ticket_id)
    if row is None:
        raise HTTPException(404)
    if row.status != "needs_approval":
        raise HTTPException(409, f"ticket is {row.status}, not waiting for approval")
    await db.update_ticket(ticket_id, status="queued")
    await enqueue_resume(ticket_id, decision.model_dump())
    return {"ok": True}


# --- events -----------------------------------------------------------------------------------


@api.get("/tickets/{ticket_id}/events")
async def list_events(ticket_id: str, after: int = 0) -> list[StoredEvent]:
    return await db.list_events(ticket_id, after)


def _sse(e: StoredEvent) -> ServerSentEvent:
    return ServerSentEvent(data=e.model_dump_json(), id=str(e.id), event=e.event.kind)


@api.get("/tickets/{ticket_id}/events/stream")
async def stream_events(ticket_id: str, request: Request, replay: bool = False):
    """Stored events first, then live ones (Postgres LISTEN/NOTIFY). With ?replay=1, re-sends a
    stored run at its original pace (gaps capped at 3 s) and closes: no model or tool calls."""
    last_id = int(request.headers.get("last-event-id", 0) or 0)

    async def replayed():
        prev = None
        for e in await db.list_events(ticket_id):
            if prev is not None:
                await asyncio.sleep(min((e.ts - prev).total_seconds(), 3.0))
            prev = e.ts
            yield _sse(e)

    async def live():
        nonlocal last_id
        async with await psycopg.AsyncConnection.connect(
            settings.database_url, autocommit=True
        ) as conn:
            await conn.execute("LISTEN ticket_events")  # listen first, so nothing is missed
            for e in await db.list_events(ticket_id, last_id):
                last_id = e.id
                yield _sse(e)
            while not await request.is_disconnected():
                async for n in conn.notifies(timeout=5.0):
                    if n.payload.split(":", 1)[0] != ticket_id:
                        continue
                    for e in await db.list_events(ticket_id, last_id):
                        last_id = e.id
                        yield _sse(e)

    return EventSourceResponse(replayed() if replay else live(), ping=15)


# --- simulator and scorecard ------------------------------------------------------------------


@cache
def _templates() -> list[SimulatorTemplate]:
    raw = yaml.safe_load((ROOT / "scenarios" / "tickets.yaml").read_text())
    return [SimulatorTemplate(**t) for t in raw["tickets"]]


@api.get("/simulator/templates")
async def simulator_templates() -> list[SimulatorTemplate]:
    return _templates()


@api.post("/simulator/tickets")
async def simulator_send(req: SimulatorTicketIn) -> dict:
    """Send a signed ticket through the real webhook, exactly as Pylon would."""
    if req.template_id:
        t = next((t for t in _templates() if t.id == req.template_id), None)
        if t is None:
            raise HTTPException(404, "unknown template")
        subject, body = t.subject, t.body
    elif req.subject and req.body:
        subject, body = req.subject, req.body
    else:
        raise HTTPException(422, "give template_id, or subject and body")
    payload = PylonTicketIn(
        id=f"T-{uuid.uuid4().hex[:6].upper()}",
        tenant_id=req.tenant_id,
        subject=subject,
        body=body,
        requester=req.requester,
    )
    raw = payload.model_dump_json().encode()
    async with httpx.AsyncClient(base_url=settings.api_base_url) as client:
        r = await client.post(
            "/webhooks/pylon",
            content=raw,
            headers={"x-pylon-signature": sign(raw), "content-type": "application/json"},
        )
        r.raise_for_status()
    return r.json()


@api.get("/evals/scorecard")
async def scorecard() -> list[ScorecardEntry]:
    return [ScorecardEntry.model_validate(r) for r in await db.list_eval_results()]
