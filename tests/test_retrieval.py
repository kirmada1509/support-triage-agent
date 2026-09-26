"""Phase 3 retrieval rules: stable chunks, incremental hashes, fusion and filters."""

import json
from pathlib import Path

import yaml

from app.retrieval.chunk import chunk_markdown, content_hash
from app.retrieval.search import filter_hits, reciprocal_rank_fusion
from app.settings import ROOT


def test_sections_keep_article_title_and_heading():
    article = (
        "# Paying for orders\n\nIntro.\n\n## Accepted cards\nVisa and Mastercard.\n\n"
        "## Expiry\nThe expiry month is valid.\n"
    )
    chunks = chunk_markdown(Path("payment-cards.md"), article)
    assert [chunk.id for chunk in chunks] == [
        "payment-cards#accepted-cards",
        "payment-cards#expiry",
    ]
    assert chunks[0].title == "Paying for orders — Accepted cards"
    assert chunks[0].body.startswith("Paying for orders\nAccepted cards\n")
    assert "Visa and Mastercard." in chunks[0].body
    assert "Expiry" not in chunks[0].body


def test_content_hash_is_stable_and_changes_with_content():
    assert content_hash("same text") == content_hash("same text")
    assert content_hash("same text") != content_hash("same text changed")
    assert len(content_hash("same text")) == 64


def test_rrf_fuses_overlap_and_breaks_ties_by_id():
    ranked = reciprocal_rank_fusion(["a", "b", "c"], ["b", "a", "d"])
    assert [id for id, _ in ranked] == ["a", "b", "c", "d"]
    assert ranked[0][1] == ranked[1][1]
    assert ranked[0][1] > ranked[2][1]


def test_filters_keep_kind_status_and_likely_services():
    rows = [
        {"id": "help", "kind": "help_section", "status": None, "service": None},
        {"id": "open-pay", "kind": "ticket", "status": "open", "service": "payment"},
        {"id": "closed-pay", "kind": "ticket", "status": "resolved", "service": "payment"},
        {"id": "open-quote", "kind": "ticket", "status": "open", "service": "quote"},
    ]
    assert [r["id"] for r in filter_hits(rows, kind="help_section")] == ["help"]
    assert [
        r["id"] for r in filter_hits(rows, kind="ticket", status="open", services=["payment"])
    ] == ["open-pay"]


def test_eval_set_is_fixed_and_labels_reference_expected_ids():
    data = yaml.safe_load((ROOT / "evals" / "tickets.yaml").read_text())
    cases = data["tickets"]
    assert len(cases) == 20
    assert [case["id"] for case in cases[:7]] == [str(i) for i in range(1, 8)]
    assert len({case["id"] for case in cases}) == 20
    scenarios = yaml.safe_load((ROOT / "scenarios" / "tickets.yaml").read_text())["tickets"]
    for case, scenario in zip(cases[:7], scenarios, strict=True):
        assert (case["subject"], case["body"]) == (scenario["subject"], scenario["body"])
    ownership = yaml.safe_load((ROOT / "config" / "ownership.yaml").read_text())
    for case in cases:
        assert case["type"] in {"how_to", "request", "tech_issue"}
        assert case["service"] in {*ownership, "other"}
        assert case["verdict"] in {
            None,
            "false_positive",
            "confirmed_bug",
            "config_incident",
            "duplicate",
        }
        assert case["team"] is None or case["team"] in {v["team"] for v in ownership.values()}
        assert isinstance(case["answering_help_section"], str | type(None))
        assert isinstance(case["past_ticket_ids"], list)
    assert cases[0]["answering_help_section"] == "payment-cards#accepted-cards"
    assert cases[6]["past_ticket_ids"] == ["T-4"]


def test_help_and_seed_labels_resolve_to_real_content():
    article_paths = [path for path in (ROOT / "knowledge").glob("*.md") if path.name != "README.md"]
    assert len(article_paths) == 31
    sections = {
        section.id for path in article_paths for section in chunk_markdown(path, path.read_text())
    }
    assert len(sections) == 62
    sources = yaml.safe_load((ROOT / "knowledge" / "sources.yaml").read_text())
    assert set(sources) == sections
    for source_paths in sources.values():
        for source in [source_paths] if isinstance(source_paths, str) else source_paths:
            assert source.startswith("src/") and ".." not in Path(source).parts

    cases = yaml.safe_load((ROOT / "evals" / "tickets.yaml").read_text())["tickets"]
    assert {
        case["answering_help_section"] for case in cases if case["answering_help_section"]
    } <= sections
    tickets = [
        json.loads(line) for line in (ROOT / "seed" / "past_tickets.jsonl").read_text().splitlines()
    ]
    assert len(tickets) == 200
    ids = {ticket["id"] for ticket in tickets}
    assert len(ids) == 200
    assert all(ticket["synthetic"] is True for ticket in tickets)
    assert all(
        ticket["service"] in yaml.safe_load((ROOT / "config" / "ownership.yaml").read_text())
        for ticket in tickets
    )
    assert {id for case in cases for id in case["past_ticket_ids"] if id != "T-4"} <= ids
    assert tickets[1]["near_miss_group"] == tickets[10]["near_miss_group"] or any(
        sum(ticket["near_miss_group"] == group for ticket in tickets) > 10
        for group in {ticket["near_miss_group"] for ticket in tickets}
    )
