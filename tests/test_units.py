from fastapi.testclient import TestClient

from app.api.main import api
from app.events import CodeOut, EventAdapter, ToolCallEvent
from app.graph.build import pipeline_shape
from app.graph.routes import is_duplicate, pick_lane, pick_outcome
from app.models import Classification, Verdict
from app.nodes.approve import approval_reasons


def classification(**kw) -> Classification:
    base = dict(
        ticket_type="tech_issue",
        ticket_type_confidence=0.9,
        service="payment",
        severity=3,
        revenue_blocking=False,
        revenue_blocking_confidence=0.2,
    )
    return Classification(**{**base, **kw})


def verdict(kind: str, confidence: float = 0.9) -> Verdict:
    return Verdict(
        kind=kind,
        root_cause="x",
        owning_service="payment",
        confidence=confidence,
        customer_reply="hi",
    )


def test_routes():
    assert pick_lane({"classification": classification(ticket_type="how_to")}) == "layer1"
    assert pick_lane({"classification": classification(ticket_type="request")}) == "requests"
    assert pick_lane({"classification": classification()}) == "duplicates"
    assert pick_lane({"classification": classification(needs_human=True)}) == "approve"
    assert is_duplicate({"duplicate_of": "PAY-12"}) == "reply"
    assert is_duplicate({"duplicate_of": None}) == "brief"
    assert pick_outcome({"verdict": verdict("confirmed_bug")}) == "layer3"
    assert pick_outcome({"verdict": verdict("config_incident")}) == "layer3"
    assert pick_outcome({"verdict": verdict("false_positive")}) == "approve"


def test_approval_reasons():
    ok = {"classification": classification(), "verdict": verdict("false_positive"), "reply": "hi"}
    assert approval_reasons(ok) == []
    assert approval_reasons({**ok, "classification": classification(severity=1)}) == ["Sev1"]
    assert "revenue blocking" in approval_reasons(
        {
            **ok,
            "classification": classification(
                revenue_blocking=True, revenue_blocking_confidence=0.9
            ),
        }
    )
    assert approval_reasons({**ok, "verdict": verdict("inconclusive")})
    assert approval_reasons({**ok, "verdict": verdict("false_positive", 0.5)})
    assert approval_reasons({**ok, "reply": None}) == ["no draft reply"]


def test_event_roundtrip():
    e = ToolCallEvent(
        stage="codebase_analyst",
        call_id="1",
        tool="sed",
        status="ok",
        output=CodeOut(
            file="src/payment/charge.js", language="js", start_line=55, code="...", highlight=[73]
        ),
    )
    back = EventAdapter.validate_python(e.model_dump(mode="json"))
    assert back == e and back.output.render == "code"


def test_pipeline_shape():
    shape = pipeline_shape()
    ids = {n["id"] for n in shape["nodes"]}
    assert len(ids) == 19 and {"__start__", "__end__", "data_analyst"} <= ids
    conditional = {(e["source"], e["target"]) for e in shape["edges"] if e["conditional"]}
    assert ("verdict", "layer3") in conditional and ("route", "duplicates") in conditional


def test_webhook_rejects_bad_signature():
    client = TestClient(api)  # no lifespan: nothing touches Postgres
    r = client.post(
        "/webhooks/pylon",
        content=b'{"id":"T-1","subject":"s","body":"b"}',
        headers={"x-pylon-signature": "wrong"},
    )
    assert r.status_code == 401
    assert client.get("/pipeline").status_code == 200
