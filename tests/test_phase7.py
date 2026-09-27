"""Phase 7 handoff and customer delivery contracts."""

import httpx
import pytest

from app.integrations import linear, pylon
from app.models import Classification, Evidence, Findings, Verdict
from app.nodes import approve, layer3, reply
from tests.conftest import demo_ticket


def bug_state():
    return {
        "ticket": demo_ticket("4"),
        "classification": Classification(
            ticket_type="tech_issue",
            ticket_type_confidence=0.9,
            service="payment",
            severity=2,
            revenue_blocking=True,
            revenue_blocking_confidence=0.9,
        ),
        "verdict": Verdict(
            kind="confirmed_bug",
            root_cause="Expiry comparison rejects current month",
            owning_service="payment",
            confidence=0.9,
            customer_reply="We found the issue.",
            engineering_summary="Change the expiry comparison.",
            file_line="src/payment/charge.js:88",
            commit="b7d87ca7",
        ),
        "findings": [
            Findings(
                agent="data_analyst",
                hypothesis="payments failed",
                confidence=0.9,
                evidence=[Evidence(source="trace", ref="a" * 32, observation="card rejected")],
            )
        ],
        "reply": "We found the issue.",
    }


def test_issue_description_contains_checked_evidence(monkeypatch):
    from app.settings import settings

    monkeypatch.setattr(settings, "github_repo_url", "https://github.com/example/shop")
    description = layer3.issue_description(bug_state())
    assert "T-4" in description
    assert "Expiry comparison rejects current month" in description
    assert "src/payment/charge.js:88" in description
    assert "b7d87ca7" in description
    assert "card rejected" in description
    assert "http://localhost:8080/trace/" in description
    assert "https://github.com/example/shop/blob/b7d87ca7/src/payment/charge.js#L88" in description
    assert "Affected count: at least 1" in description


def test_issue_and_final_outcome_include_only_source_backed_code():
    from app.models import CodeSnippet
    from app.outcome import build_outcome

    state = bug_state()
    snippet = CodeSnippet(
        render="diff",
        file="src/payment/charge.js",
        start_line=86,
        end_line=89,
        language="diff",
        content=(
            "-    if (currentPeriod > expiryPeriod) {\n+    if (currentPeriod >= expiryPeriod) {"
        ),
        call_id="c1",
    )
    state["findings"].append(
        Findings(
            agent="codebase_analyst",
            hypothesis="comparison regressed",
            confidence=0.9,
            evidence=[
                Evidence(source="code", ref="src/payment/charge.js:88", observation="comparison")
            ],
            code_snippets=[snippet],
        )
    )
    description = layer3.issue_description(state)
    assert "```diff" in description
    assert "+    if (currentPeriod >= expiryPeriod) {" in description
    outcome = build_outcome(state)
    assert outcome.code_snippets == [snippet]


@pytest.mark.asyncio
async def test_linear_uses_team_key_and_checks_graphql_result():
    sent = []

    def handler(request):
        sent.append(request)
        body = __import__("json").loads(request.content)
        if "teams" in body["query"]:
            return httpx.Response(
                200,
                json={
                    "data": {
                        "teams": {"nodes": [{"id": "team-1", "key": "PAY", "name": "Payments"}]}
                    }
                },
            )
        assert body["variables"]["input"]["teamId"] == "team-1"
        assert body["variables"]["input"]["priority"] == 2
        return httpx.Response(
            200,
            json={
                "data": {
                    "issueCreate": {
                        "success": True,
                        "issue": {
                            "id": "uuid",
                            "identifier": "PAY-42",
                            "url": "https://linear.app/demo/issue/PAY-42",
                        },
                    }
                }
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        issue = await linear.create_issue("key", "PAY", "Title", "Description", 2, client)
    assert issue.identifier == "PAY-42"
    assert len(sent) == 2
    assert sent[0].headers["authorization"] == "key"


@pytest.mark.asyncio
async def test_pylon_replies_to_customer_message_with_recipient():
    posts = []

    def handler(request):
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"id": "private", "is_private": True},
                        {
                            "id": "customer",
                            "is_private": False,
                            "source": "email",
                            "author": {"contact": {"email": "buyer@example.com"}},
                            "email_info": {},
                        },
                    ]
                },
            )
        posts.append(__import__("json").loads(request.content))
        return httpx.Response(200, json={"data": {"id": "reply-1", "issue_id": "issue-1"}})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://api.usepylon.com"
    ) as client:
        message_id = await pylon.send_reply(
            "token", "issue-1", "Thanks <again>", "buyer@example.com", client
        )
    assert message_id == "reply-1"
    assert posts == [
        {
            "message_id": "customer",
            "body_html": "Thanks &lt;again&gt;",
            "email_info": {"to_emails": ["buyer@example.com"]},
        }
    ]


@pytest.mark.asyncio
async def test_pylon_rejects_private_reply_target():
    def handler(request):
        assert request.method == "GET"
        return httpx.Response(200, json={"data": [{"id": "private", "is_private": True}]})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://api.usepylon.com"
    ) as client:
        with pytest.raises(ValueError, match="not customer-visible"):
            await pylon.send_reply("token", "issue-1", "Hello", None, client, "private")


@pytest.mark.asyncio
async def test_pylon_note_is_private_and_html_escaped():
    posted = []

    def handler(request):
        posted.append(__import__("json").loads(request.content))
        return httpx.Response(200, json={"data": {"id": "note-1", "issue_id": "issue-1"}})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://api.usepylon.com"
    ) as client:
        assert await pylon.send_note("token", "issue-1", "Root <cause>", client) == "note-1"
    assert posted == [{"body_html": "Root &lt;cause&gt;", "thread_name": "Account manager"}]


@pytest.mark.asyncio
async def test_no_account_logs_reply_and_does_not_claim_sent(monkeypatch):
    from app.settings import settings

    monkeypatch.setattr(settings, "pylon_api_token", "")
    events = []
    monkeypatch.setattr(reply, "emit", events.append)
    state = {"ticket": demo_ticket("1"), "reply": "Here is the answer.", "approved": True}
    result = await reply.run(state)
    assert result["_summary"] == "reply logged (Pylon not configured)"
    assert events[-1].status == "logged"


@pytest.mark.asyncio
async def test_rejected_reply_is_never_sent(monkeypatch):
    events = []
    monkeypatch.setattr(reply, "emit", events.append)
    result = await reply.run({"ticket": demo_ticket("1"), "reply": "Draft", "approved": False})
    assert "no reply" in result["_summary"]
    assert not events


@pytest.mark.asyncio
async def test_feature_request_goes_to_roadmap_team(monkeypatch):
    from app.integrations.linear import Issue
    from app.models import RequestTriage
    from app.settings import settings

    calls = []

    async def created(*args):
        calls.append(args)
        return Issue("ROAD-12", "https://linear.app/demo/issue/ROAD-12")

    async def no_receipt(*args):
        return None

    monkeypatch.setattr(settings, "linear_api_key", "key")
    monkeypatch.setattr(settings, "roadmap_linear_team", "ROAD")
    monkeypatch.setattr(settings, "pylon_api_token", "")
    monkeypatch.setattr(reply.linear, "create_issue", created)
    monkeypatch.setattr(reply.db, "delivery_receipt", no_receipt)
    events = []
    monkeypatch.setattr(reply, "emit", events.append)
    result = await reply.run(
        {
            "ticket": demo_ticket("2"),
            "approved": True,
            "request": RequestTriage(
                kind="feature",
                summary="Apple Pay",
                roadmap_tag="payments",
                acknowledgement="Thanks.",
            ),
            "reply": "Thanks.",
        }
    )
    assert calls[0][1] == "ROAD"
    assert result["linear_issue"] == "ROAD-12"
    assert any(
        e.destination == "linear" and e.status == "sent"
        for e in events
        if hasattr(e, "destination")
    )


@pytest.mark.asyncio
async def test_retry_uses_linear_receipt(monkeypatch):
    from app.events import DeliveryEvent
    from app.settings import settings

    async def receipt(*args):
        return DeliveryEvent(
            stage="layer3",
            destination="linear",
            status="sent",
            external_id="PAY-42",
            detail="https://linear.app/demo/issue/PAY-42",
        )

    async def no_create(*args):
        pytest.fail("retry created a second Linear issue")

    monkeypatch.setattr(settings, "linear_api_key", "key")
    monkeypatch.setattr(layer3.db, "delivery_receipt", receipt)
    monkeypatch.setattr(layer3.linear, "create_issue", no_create)
    result = await layer3.run(bug_state())
    assert result["linear_issue"] == "PAY-42"


@pytest.mark.asyncio
async def test_retry_uses_pylon_reply_receipt(monkeypatch):
    from app.events import DeliveryEvent
    from app.settings import settings

    async def receipt(*args):
        return DeliveryEvent(
            stage="reply",
            destination="pylon_reply",
            status="sent",
            external_id="msg-42",
            detail="Customer reply",
        )

    async def no_send(*args, **kwargs):
        pytest.fail("retry sent a second customer reply")

    monkeypatch.setattr(settings, "pylon_api_token", "token")
    monkeypatch.setattr(reply.db, "delivery_receipt", receipt)
    monkeypatch.setattr(reply.pylon, "send_reply", no_send)
    state = {
        "ticket": demo_ticket("1").model_copy(update={"pylon_issue_id": "issue-1"}),
        "reply": "Thanks.",
        "approved": True,
    }
    result = await reply.run(state)
    assert result["_summary"] == "reply already sent (msg-42)"


def test_missing_linear_does_not_force_approval():
    state = bug_state()
    state["classification"] = state["classification"].model_copy(update={"revenue_blocking": False})
    assert approve.approval_reasons(state) == []


def test_end_of_ticket_outcome_shows_bug_and_logged_reply():
    from app.outcome import build_outcome

    state = {**bug_state(), "reply_delivery": "logged", "approved": True}
    outcome = build_outcome(state)
    assert outcome.summary.startswith("Confirmed bug in payment")
    assert outcome.root_cause == "Expiry comparison rejects current month"
    assert outcome.file_line == "src/payment/charge.js:88"
    assert outcome.reply_delivery == "logged"
    assert outcome.linear_issue is None
    assert outcome.engineering_handoff == "local_only"


@pytest.mark.asyncio
async def test_without_linear_records_finding_locally(monkeypatch):
    from app.settings import settings

    monkeypatch.setattr(settings, "linear_api_key", "")
    seen = []
    monkeypatch.setattr(layer3, "emit", seen.append)
    result = await layer3.run(bug_state())
    assert result["linear_issue"] is None
    assert result["_summary"] == "Payments finding recorded locally"
    assert "escalat" not in result["reply"].lower()
    assert seen[0].status == "logged"
