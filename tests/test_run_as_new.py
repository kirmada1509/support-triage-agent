"""Run as new: a ticket that skips the duplicate check, so a demo ticket that repeats an earlier
one still gets the whole investigation. The flag travels in the stored webhook payload."""

from datetime import UTC, datetime
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.api import main
from app.api.schemas import PylonTicketIn
from app.tasks import ticket_from_row


def row(**raw) -> SimpleNamespace:
    return SimpleNamespace(
        id="T-OLD001",
        tenant_id="figma-merch",
        source="pylon",
        subject="The Comet Book is missing",
        body="It no longer shows in our listing.",
        requester="ops@figma-merch.example",
        received_at=datetime(2026, 9, 27, 22, 20, tzinfo=UTC),
        status="done",
        lane="tech_issue",
        current_stage=None,
        stages_done=16,
        severity=3,
        verdict_kind=None,
        cost_usd=0,
        raw=raw,
    )


def test_the_worker_reads_run_as_new_from_the_stored_payload():
    assert ticket_from_row(row(run_as_new=True)).run_as_new is True
    plain = ticket_from_row(row(pylon_issue_id="iss_1"))
    assert plain.run_as_new is False and plain.pylon_issue_id == "iss_1"


def fake_delivery(monkeypatch) -> list[PylonTicketIn]:
    sent = []

    async def deliver(payload: PylonTicketIn) -> dict:
        sent.append(payload)
        return {"ok": True, "ticket_id": payload.id}

    monkeypatch.setattr(main, "deliver", deliver)
    return sent


def test_run_as_new_sends_a_copy_of_a_previous_ticket(monkeypatch):
    sent = fake_delivery(monkeypatch)

    async def get_ticket(ticket_id):
        return row() if ticket_id == "T-OLD001" else None

    monkeypatch.setattr(main.db, "get_ticket", get_ticket)
    client = TestClient(main.api)
    r = client.post("/tickets/T-OLD001/run-as-new")
    assert r.status_code == 200
    (copy,) = sent
    assert r.json()["ticket_id"] == copy.id != "T-OLD001"
    assert copy.run_as_new is True
    assert (copy.subject, copy.body, copy.tenant_id, copy.requester) == (
        "The Comet Book is missing",
        "It no longer shows in our listing.",
        "figma-merch",
        "ops@figma-merch.example",
    )
    assert client.post("/tickets/T-NOPE/run-as-new").status_code == 404


def test_the_simulator_can_send_a_ticket_to_run_as_new(monkeypatch):
    sent = fake_delivery(monkeypatch)
    client = TestClient(main.api)
    client.post("/simulator/tickets", json={"subject": "s", "body": "b", "run_as_new": True})
    client.post("/simulator/tickets", json={"subject": "s", "body": "b"})
    assert [p.run_as_new for p in sent] == [True, False]
