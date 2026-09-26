"""Incremental indexing of help sections and synthetic or live ticket memory."""

from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from app import db
from app.retrieval.chunk import HelpSection, content_hash
from app.retrieval.embed import DIMENSIONS, EmbeddingClient
from app.tables import RetrievalDocRow


def _check_vectors(vectors: list[list[float]], expected: int) -> None:
    if len(vectors) != expected or any(len(vector) != DIMENSIONS for vector in vectors):
        raise ValueError(f"embedding client must return {expected} vectors of {DIMENSIONS} values")


async def _existing(ids: list[str]) -> dict[str, RetrievalDocRow]:
    if not ids:
        return {}
    async with db.Session() as session:
        rows = await session.scalars(select(RetrievalDocRow).where(RetrievalDocRow.id.in_(ids)))
        return {row.id: row for row in rows}


async def index_help(sections: Sequence[HelpSection], embedder: EmbeddingClient) -> int:
    """Re-embed only changed sections; return the number embedded."""
    existing = await _existing([section.id for section in sections])
    changed = [
        section
        for section in sections
        if existing.get(section.id) is None
        or existing[section.id].content_hash != section.content_hash
    ]
    vectors = await embedder.embed_documents([section.body for section in changed])
    _check_vectors(vectors, len(changed))
    async with db.Session.begin() as session:
        for section, vector in zip(changed, vectors, strict=True):
            if section.id in existing and existing[section.id].kind != "help_section":
                raise ValueError(f"{section.id}: already indexed as a ticket")
            stmt = insert(RetrievalDocRow).values(
                id=section.id,
                kind="help_section",
                title=section.title,
                body=section.body,
                content_hash=section.content_hash,
                embedding=vector,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=[RetrievalDocRow.id],
                set_={
                    "title": stmt.excluded.title,
                    "body": stmt.excluded.body,
                    "content_hash": stmt.excluded.content_hash,
                    "embedding": stmt.excluded.embedding,
                    "updated_at": func.now(),
                },
            )
            await session.execute(stmt)
    return len(changed)


async def index_tickets(tickets: Sequence[Mapping[str, Any]], embedder: EmbeddingClient) -> int:
    """Update status and metadata without re-embedding unchanged customer text."""
    existing = await _existing([ticket["id"] for ticket in tickets])
    texts = [f"{ticket['subject']}\n{ticket['body']}\n{ticket['summary']}" for ticket in tickets]
    hashes = [content_hash(text) for text in texts]
    changed_positions = [
        i
        for i, ticket in enumerate(tickets)
        if ticket["id"] not in existing or existing[ticket["id"]].content_hash != hashes[i]
    ]
    vectors = await embedder.embed_documents([texts[i] for i in changed_positions])
    _check_vectors(vectors, len(changed_positions))
    by_position = dict(zip(changed_positions, vectors, strict=True))
    async with db.Session.begin() as session:
        for i, ticket in enumerate(tickets):
            old = existing.get(ticket["id"])
            if old and old.kind != "ticket":
                raise ValueError(f"{ticket['id']}: already indexed as a help section")
            values = {
                "id": ticket["id"],
                "kind": "ticket",
                "title": ticket["subject"],
                "body": ticket["body"],
                "summary": ticket["summary"],
                "status": ticket["status"],
                "service": ticket["service"],
                "version": ticket.get("version"),
                "verdict": ticket.get("verdict"),
                "root_cause": ticket.get("root_cause"),
                "linear_issue": ticket.get("linear_issue"),
                "tenant": ticket.get("tenant"),
                "content_hash": hashes[i],
                "embedding": by_position.get(i, old.embedding if old else None),
            }
            stmt = insert(RetrievalDocRow).values(**values)
            stmt = stmt.on_conflict_do_update(
                index_elements=[RetrievalDocRow.id],
                set_={
                    **{key: getattr(stmt.excluded, key) for key in values if key != "id"},
                    "updated_at": func.now(),
                },
            )
            await session.execute(stmt)
    return len(changed_positions)
