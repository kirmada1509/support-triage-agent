"""Index Phase 3 content and measure retrieval against the fixed labelled tickets."""

import argparse
import asyncio
import json
from pathlib import Path

import yaml
from sqlalchemy import select

from app import db
from app.retrieval.chunk import HelpSection, chunk_markdown
from app.retrieval.embed import MODEL_NAME, MODEL_REVISION, EmbeddingClient, LocalBGE
from app.retrieval.index import index_help, index_tickets
from app.retrieval.search import search
from app.settings import ROOT
from app.tables import RetrievalDocRow


def help_sections() -> list[HelpSection]:
    return [
        section
        for path in sorted((ROOT / "knowledge").glob("*.md"))
        if path.name != "README.md"
        for section in chunk_markdown(path, path.read_text())
    ]


def past_tickets() -> list[dict]:
    return [
        json.loads(line)
        for line in (ROOT / "seed" / "past_tickets.jsonl").read_text().splitlines()
        if line.strip()
    ]


def eval_tickets() -> list[dict]:
    return yaml.safe_load((ROOT / "evals" / "tickets.yaml").read_text())["tickets"]


async def _demo_open_ticket(embedder: EmbeddingClient) -> bool:
    """Model ticket 7 after ticket 4's verdict, without replacing a real T-4 entry."""
    async with db.Session() as session:
        existing = await session.scalar(
            select(RetrievalDocRow.id).where(RetrievalDocRow.id == "T-4")
        )
    if existing:
        return False
    case = eval_tickets()[3]
    await index_tickets(
        [
            {
                "id": "T-4",
                "subject": case["subject"],
                "body": case["body"],
                "summary": (
                    "Cards expiring this month are rejected after payment v1.4.0; "
                    "an open Payments investigation tracks the regression."
                ),
                "status": "open",
                "service": "payment",
                "version": "v1.4.0",
                "verdict": "confirmed_bug",
                "root_cause": "expiry-month comparison regression",
                "linear_issue": None,
                "tenant": "figma-merch",
            }
        ],
        embedder,
    )
    return True


async def hit_rates(embedder: EmbeddingClient, min_vector_similarity: float = 0.45) -> dict:
    """Score raw search: no answer labels or oracle service filters enter the query."""
    inserted_demo = await _demo_open_ticket(embedder)
    cases = eval_tickets()
    details = []
    help_hits = help_total = ticket_hits = ticket_topic_hits = ticket_total = 0
    try:
        for case in cases:
            query = f"{case['subject']}\n{case['body']}"
            detail: dict = {"id": case["id"]}
            if expected := case["answering_help_section"]:
                help_total += 1
                hits = await search(
                    query,
                    embedder,
                    kind="help_section",
                    limit=5,
                    min_vector_similarity=min_vector_similarity,
                )
                found = expected in {hit.id for hit in hits}
                help_hits += found
                detail["help_found"] = found
                detail["help_top5"] = [hit.id for hit in hits]
            if expected_ids := case["past_ticket_ids"]:
                ticket_total += 1
                hits = await search(
                    query,
                    embedder,
                    kind="ticket",
                    limit=3,
                    min_vector_similarity=min_vector_similarity,
                )
                found = bool(set(expected_ids) & {hit.id for hit in hits})
                ticket_hits += found
                topic_found = any(
                    hit.id == expected
                    or (
                        expected.startswith("SYN-")
                        and hit.id.startswith(expected.rsplit("-", 1)[0] + "-")
                    )
                    for expected in expected_ids
                    for hit in hits
                )
                ticket_topic_hits += topic_found
                detail["ticket_found"] = found
                detail["ticket_topic_found"] = topic_found
                detail["ticket_top3"] = [hit.id for hit in hits]
            details.append(detail)
    finally:
        if inserted_demo:
            async with db.Session.begin() as session:
                row = await session.get(RetrievalDocRow, "T-4")
                if row:
                    await session.delete(row)
    report = {
        "model": MODEL_NAME,
        "model_revision": MODEL_REVISION,
        "min_vector_similarity": min_vector_similarity,
        "corpus": {
            "help_sections": len(help_sections()),
            "synthetic_tickets": len(past_tickets()),
        },
        "help_at_5": {"hits": help_hits, "total": help_total, "rate": help_hits / help_total},
        "ticket_at_3": {
            "hits": ticket_hits,
            "total": ticket_total,
            "rate": ticket_hits / ticket_total,
        },
        "ticket_topic_at_3": {
            "hits": ticket_topic_hits,
            "total": ticket_total,
            "rate": ticket_topic_hits / ticket_total,
        },
        "query": "subject plus body; no oracle service filter",
        "cases": details,
    }
    ticket_one = next(item for item in details if item["id"] == "1")
    if not ticket_one["help_found"]:
        raise RuntimeError("ticket 1's accepted-cards section is not in the top 5")
    return report


async def run(action: str, output: Path | None, min_vector_similarity: float) -> None:
    embedder = LocalBGE()
    try:
        if action in {"index-help", "index-all"}:
            sections = help_sections()
            changed = await index_help(sections, embedder)
            print(f"help: {len(sections)} sections, {changed} embedded")
        if action in {"index-tickets", "index-all"}:
            tickets = past_tickets()
            changed = await index_tickets(tickets, embedder)
            print(f"tickets: {len(tickets)} synthetic, {changed} embedded")
        if action == "hit-rate":
            report = await hit_rates(embedder, min_vector_similarity)
            content = json.dumps(report, indent=2) + "\n"
            if output:
                output.write_text(content)
            print(content)
    finally:
        await db.engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["index-help", "index-tickets", "index-all", "hit-rate"])
    parser.add_argument("--output", type=Path)
    parser.add_argument("--min-vector-similarity", type=float, default=0.45)
    args = parser.parse_args()
    asyncio.run(run(args.action, args.output, args.min_vector_similarity))


if __name__ == "__main__":
    main()
