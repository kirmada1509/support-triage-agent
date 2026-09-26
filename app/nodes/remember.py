"""Write-back to ticket memory: every ticket joins retrieval_docs (open while an issue for it is
open), and a finished Layer 2 verdict becomes an investigations row for later duplicate checks.
"""

from app import db
from app.graph.state import TicketState
from app.nodes.duplicates import error_signature
from app.nodes.retrieve import embedder
from app.retrieval.index import index_tickets

OPEN_KINDS = {"confirmed_bug", "config_incident"}  # an issue stays open for these
REMEMBERED_KINDS = OPEN_KINDS | {"false_positive"}  # an inconclusive verdict teaches nothing


async def write_doc(doc: dict) -> None:
    await index_tickets([doc], embedder())


async def add_investigation(**row) -> None:
    await db.add_investigation(**row)


async def run(state: TicketState) -> dict:
    t = state["ticket"]
    v, b, c = state.get("verdict"), state.get("brief"), state.get("classification")
    dup = state.get("duplicate_of")
    issue = state.get("linear_issue") or dup
    status = "open" if dup or (v and v.kind in OPEN_KINDS) else "resolved"
    service = v.owning_service if v else (c.service if c else None)
    version = b.deployed_version if b else None
    await write_doc(
        {
            "id": t.id,
            "subject": t.subject,
            "body": t.body,
            "summary": (v.root_cause if v else state.get("reply") or "")[:1000],
            "status": status,
            "service": service,
            "version": version,
            "verdict": v.kind if v else None,
            "root_cause": v.root_cause if v else None,
            "linear_issue": issue,
            "tenant": t.tenant_id,
        }
    )
    if not v or dup or v.kind not in REMEMBERED_KINDS:
        return {"_summary": f"ticket memory: {status}"}
    error_text = next((f.error_text for f in state.get("findings", []) if f.error_text), None)
    await add_investigation(
        ticket_id=t.id,
        service=v.owning_service,
        version=version,
        error_signature=error_signature(error_text) if error_text else None,
        root_cause=v.root_cause + (f" (commit {v.commit[:8]})" if v.commit else ""),
        file_line=v.file_line,
        linear_issue=state.get("linear_issue"),
        status=status,
    )
    return {"_summary": f"ticket memory: {status}; investigation {v.kind}"}
