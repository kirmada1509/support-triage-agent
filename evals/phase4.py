"""Run the live front pipeline on fixed, pre-labelled eval tickets and save a baseline."""

import argparse
import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from langgraph.graph import END, START, StateGraph

from app.graph.routes import pick_lane
from app.graph.state import TicketState
from app.graph.stream import staged
from app.models import ContextBundle, Ticket
from app.models_config import role
from app.nodes import enrich, jev, layer1, requests, retrieve, route
from app.nodes._config import service_glossary
from app.retrieval.cli import eval_tickets
from app.settings import ROOT

RECEIVED_AT = datetime(2026, 9, 23, 12, 0, tzinfo=UTC)


def graph():
    builder = StateGraph(TicketState)
    for name, fn in {
        "enrich": enrich.run,
        "retrieve": retrieve.run,
        "jev": jev.run,
        "route": route.run,
        "layer1": layer1.run,
        "requests": requests.run,
    }.items():
        builder.add_node(name, staged(name, fn))
    builder.add_edge(START, "enrich")
    builder.add_edge("enrich", "retrieve")
    builder.add_edge("enrich", "jev")
    builder.add_edge(["retrieve", "jev"], "route")
    builder.add_conditional_edges(
        "route",
        lambda state: pick_lane(state) if pick_lane(state) in ("layer1", "requests") else END,
        {"layer1": "layer1", "requests": "requests", END: END},
    )
    builder.add_edge("layer1", END)
    builder.add_edge("requests", END)
    return builder.compile()


async def evaluate(limit: int = 20, ids: set[str] | None = None) -> dict:
    pipeline = graph()
    cases = [case for case in eval_tickets() if ids is None or case["id"] in ids][:limit]
    details = []
    for case in cases:
        ticket = Ticket(
            id=f"EVAL-{case['id']}",
            tenant_id="figma-merch",
            subject=case["subject"],
            body=case["body"],
            received_at=RECEIVED_AT,
        )
        initial = {
            "ticket": ticket,
            "context": ContextBundle(services=service_glossary()),
        }
        state = dict(initial)
        async for mode, chunk in pipeline.astream(initial, stream_mode=["updates", "custom"]):
            if mode == "updates":
                for update in chunk.values():
                    if isinstance(update, dict):
                        state.update(update)
        classification = state["classification"]
        detail = {
            "id": case["id"],
            "expected_type": case["type"],
            "type": classification.ticket_type,
            "expected_service": case["service"],
            "service": classification.service,
            "confidence": classification.ticket_type_confidence,
            "needs_human": classification.needs_human,
            "lane": state["lane"],
            "routed_node": pick_lane(state),
            "window_valid": (
                RECEIVED_AT - timedelta(days=7)
                <= state["enrichment"].window_start
                <= state["enrichment"].window_end
                <= RECEIVED_AT
            ),
        }
        if answer := state.get("layer1"):
            detail["answer"] = answer.answer
            detail["cited_ids"] = answer.cited_ids
            detail["answer_confident"] = answer.confident
            detail["expected_help_section"] = case["answering_help_section"]
        if request := state.get("request"):
            detail["request_summary"] = request.summary
            detail["acknowledgement"] = request.acknowledgement
            detail["request_kind"] = request.kind
        details.append(detail)
        print(
            f"{case['id']:>2}: {classification.ticket_type}/{classification.service} "
            f"(expected {case['type']}/{case['service']}) "
            f"route={detail['routed_node']} confidence={classification.ticket_type_confidence:.2f}",
            flush=True,
        )
    return {
        "classification_model": role("classification").primary.key,
        "received_at": RECEIVED_AT.isoformat(),
        "context": "Service glossary only; no labelled answers, deploys, flags or incidents",
        "cases": details,
        "type_accuracy": sum(d["type"] == d["expected_type"] for d in details) / len(details),
        "service_accuracy": sum(d["service"] == d["expected_service"] for d in details)
        / len(details),
        "lane_accuracy": sum(
            d["routed_node"]
            == {"how_to": "layer1", "request": "requests", "tech_issue": "duplicates"}[
                d["expected_type"]
            ]
            for d in details
        )
        / len(details),
        "valid_windows": sum(d["window_valid"] for d in details),
        "help_citations": {
            "hits": sum(
                d["expected_help_section"] in d.get("cited_ids", [])
                for d in details if d.get("expected_help_section")
            ),
            "total": sum(bool(d.get("expected_help_section")) for d in details),
        },
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--ids", help="comma-separated case IDs for a focused rerun")
    parser.add_argument("--output", type=Path, default=ROOT / "evals" / "phase4_baseline.json")
    args = parser.parse_args()
    report = asyncio.run(evaluate(args.limit, set(args.ids.split(",")) if args.ids else None))
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(
        f"type={report['type_accuracy']:.0%} service={report['service_accuracy']:.0%} "
        f"lane={report['lane_accuracy']:.0%}",
        flush=True,
    )
