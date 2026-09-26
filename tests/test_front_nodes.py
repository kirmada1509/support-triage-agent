"""Phase 4 contracts: validate model claims before they reach routing or replies."""

from datetime import UTC, datetime, timedelta

import pytest

from app.graph.routes import pick_lane
from app.models import (
    Classification,
    ContextBundle,
    Deploy,
    Enrichment,
    FlagChange,
    Layer1Answer,
    RequestTriage,
    Retrieved,
)
from app.nodes import enrich, jev, layer1, requests, retrieve
from tests.conftest import demo_ticket


def test_enrichment_drops_unfounded_identifiers_changes_and_services():
    ticket = demo_ticket("4")
    end = ticket.received_at
    ctx = ContextBundle(
        services={"payment": "charges cards"},
        deploys=[Deploy(id=4, service="payment", version="v1.4.0", deployed_at=end)],
        flag_changes=[FlagChange(id=3, flag="paymentFailure", changed_at=end)],
    )
    result = enrich.validate(
        Enrichment(
            identifiers={"user_ids": ["figma-shopper-03", "invented"]},
            window_start=end - timedelta(hours=1),
            window_end=end,
            window_basis="this morning",
            symptom="expired card",
            likely_services=["payment", "invented"],
            relevant_changes=["deploy:4", "deploy:99", "flag:3"],
        ),
        ticket,
        ctx,
    )
    assert result.identifiers == {"user_ids": ["figma-shopper-03"]}
    assert result.likely_services == ["payment"]
    assert result.relevant_changes == ["deploy:4", "flag:3"]


def test_enrichment_clamps_window_and_rejects_unknown_timezone():
    ticket = demo_ticket("4")
    end = ticket.received_at
    result = enrich.validate(
        Enrichment(
            window_start=datetime(2020, 1, 1, tzinfo=UTC),
            window_end=end + timedelta(days=1),
            window_basis="this morning",
            symptom="cards fail",
        ),
        ticket,
        ContextBundle(),
    )
    assert result.window_start == end - timedelta(days=7)
    assert result.window_end == end
    with pytest.raises(ValueError):
        enrich.validate(
            Enrichment(
                window_start=datetime(2026, 9, 23),
                window_end=end,
                window_basis="morning",
                symptom="cards fail",
            ),
            ticket,
            ContextBundle(),
        )


def test_classification_gate_and_service_validation():
    uncertain = Classification(
        ticket_type="tech_issue",
        ticket_type_confidence=0.69,
        service="invented",
        severity=3,
        revenue_blocking=False,
        revenue_blocking_confidence=0.5,
        source="llm",
    )
    checked = jev.validate(uncertain)
    assert checked.service == "other" and checked.needs_human
    assert pick_lane({"classification": checked}) == "approve"
    blocking = checked.model_copy(
        update={
            "service": "payment",
            "ticket_type_confidence": 0.9,
            "revenue_blocking": True,
            "revenue_blocking_confidence": 0.9,
            "severity": 3,
            "needs_human": False,
        }
    )
    assert jev.validate(blocking).severity == 1


def test_layer1_checks_every_citation_and_requires_help():
    hits = [
        Retrieved(kind="help_section", id="cards#types", title="Cards", text="Visa", score=0.03)
    ]
    good = Layer1Answer(answer="Visa is accepted.", cited_ids=["cards#types"], confident=True)
    assert layer1.validate(good, hits).confident
    bad = good.model_copy(update={"cited_ids": ["cards#types", "made-up"]})
    assert not layer1.validate(bad, hits).confident
    assert not layer1.validate(good, []).confident


async def test_enrich_and_classify_nodes_use_typed_calls(monkeypatch):
    ticket = demo_ticket("4")
    ctx = ContextBundle(services={"payment": "charges cards"})
    events = []
    monkeypatch.setattr(enrich, "emit", events.append)
    monkeypatch.setattr(jev, "emit", events.append)

    async def fake_enrich(role, output_type, prompt):
        assert role == "enrichment" and output_type is Enrichment
        assert "customer timezone is unknown" in prompt
        return Enrichment(
            window_start=ticket.received_at - timedelta(hours=1),
            window_end=ticket.received_at,
            window_basis="this morning",
            symptom="card expired",
            identifiers={"user_ids": ["figma-shopper-03", "invented"]},
            likely_services=["payment", "invented"],
        ), "fake-model"

    monkeypatch.setattr(enrich, "call", fake_enrich)
    enriched = await enrich.run({"ticket": ticket, "context": ctx})
    assert enriched["enrichment"].identifiers == {"user_ids": ["figma-shopper-03"]}
    assert enriched["enrichment"].likely_services == ["payment"]

    async def fake_classify(role, output_type, prompt):
        assert role == "classification" and output_type is jev.Categorization
        assert "Card decline or expiry errors at checkout belong here" in prompt
        return jev.Categorization(
            ticket_type="tech_issue",
            ticket_type_confidence=0.88,
            service="payment",
            service_confidence=0.9,
            severity=3,
            severity_confidence=0.8,
            revenue_blocking=True,
            revenue_blocking_confidence=0.9,
        ), "fake-model"

    monkeypatch.setattr(jev, "call", fake_classify)
    result = await jev.run({"ticket": ticket, "context": ctx, **enriched})
    assert result["classification"].severity == 1
    assert result["classification"].source == "llm"
    assert len(events) == 2
    assert {a.question: a.answer for a in events[-1].answers}["severity"] == 1


async def test_retrieve_layer1_and_request_nodes(monkeypatch):
    ticket = demo_ticket("1")
    end = ticket.received_at
    state = {
        "ticket": ticket,
        "context": ContextBundle(),
        "enrichment": Enrichment(
            window_start=end - timedelta(hours=1),
            window_end=end,
            window_basis="today",
            symptom="accepted cards",
            likely_services=["payment"],
        ),
    }
    hit = Retrieved(
        kind="help_section",
        id="payment-cards#accepted-cards",
        title="Accepted cards",
        text="Visa and Mastercard accepted; Amex declined.",
        score=0.03,
    )
    seen = []

    async def fake_search(query, embedder, **kwargs):
        seen.append(kwargs)
        return [hit] if kwargs["kind"] == "help_section" else []

    monkeypatch.setattr(retrieve, "search", fake_search)
    monkeypatch.setattr(retrieve, "emit", lambda event: None)
    monkeypatch.setattr(retrieve, "embedder", lambda: None)
    retrieved = await retrieve.run(state)
    assert retrieved["retrieved"] == [hit]
    assert seen[1]["services"] == ["payment"]

    async def fake_layer1(role, output_type, prompt):
        assert hit.id in prompt
        return Layer1Answer(
            answer="Visa and Mastercard are accepted.", cited_ids=[hit.id], confident=True
        ), "fake-model"

    monkeypatch.setattr(layer1, "call", fake_layer1)
    monkeypatch.setattr(layer1, "emit", lambda event: None)
    answer = await layer1.run({**state, **retrieved})
    assert answer["layer1"].confident and answer["layer1"].cited_ids == [hit.id]

    async def fake_request(role, output_type, prompt):
        return RequestTriage(
            kind="feature",
            summary="Apple Pay",
            roadmap_tag="payments",
            acknowledgement="Thanks, we recorded the request.",
        ), "fake-model"

    monkeypatch.setattr(requests, "call", fake_request)
    monkeypatch.setattr(requests, "emit", lambda event: None)
    triage = await requests.run({**state, "ticket": demo_ticket("2")})
    assert triage["request"].kind == "feature"
    assert "recorded" not in triage["reply"].lower()
    assert "review" in triage["reply"].lower()
    assert "Apple Pay" in triage["reply"]


def test_request_acknowledgement_does_not_claim_a_handoff():
    result = requests.validate(
        RequestTriage(
            kind="feature",
            summary="Apple Pay at checkout",
            roadmap_tag="checkout",
            acknowledgement="Your request is in the right hands. We've reviewed and routed it.",
        ),
        demo_ticket("2"),
    )
    assert "right hands" not in result.acknowledgement
    assert "reviewed" not in result.acknowledgement
    assert "Apple Pay" in result.acknowledgement
