"""Rank fusion and metadata filters for help sections and ticket memory."""

from collections.abc import Iterable, Mapping
from typing import Any

from sqlalchemy import func, select

from app import db
from app.models import Retrieved
from app.retrieval.embed import DIMENSIONS, EmbeddingClient
from app.tables import RetrievalDocRow


def reciprocal_rank_fusion(
    vector_ids: Iterable[str], keyword_ids: Iterable[str], k: int = 60
) -> list[tuple[str, float]]:
    """Sum reciprocal ranks; stable ID ordering makes ties reproducible."""
    scores: dict[str, float] = {}
    for ranking in (vector_ids, keyword_ids):
        for rank, id in enumerate(dict.fromkeys(ranking), start=1):
            scores[id] = scores.get(id, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda item: (-item[1], item[0]))


def filter_hits(
    rows: Iterable[Mapping[str, Any]],
    *,
    kind: str,
    status: str | None = None,
    services: list[str] | None = None,
) -> list[Mapping[str, Any]]:
    """Use one service vocabulary (config/ownership.yaml); help is never service-filtered."""
    return [
        row
        for row in rows
        if row["kind"] == kind
        and (status is None or row["status"] == status)
        and (kind == "help_section" or not services or row["service"] in services)
    ]


async def search(
    query: str,
    embedder: EmbeddingClient,
    *,
    kind: str,
    status: str | None = None,
    services: list[str] | None = None,
    limit: int = 5,
    candidate_limit: int = 20,
    min_vector_similarity: float = 0.45,
) -> list[Retrieved]:
    """Fuse top vector and full-text matches, with filters applied inside both SQL queries."""
    if kind not in {"help_section", "ticket"}:
        raise ValueError(f"unknown retrieval kind: {kind}")
    if not query.strip() or limit <= 0:
        return []
    vector = await embedder.embed_query(query)
    if len(vector) != DIMENSIONS:
        raise ValueError(f"embedding client must return {DIMENSIONS} values")
    filters = [RetrievalDocRow.kind == kind]
    if status is not None:
        filters.append(RetrievalDocRow.status == status)
    if kind == "ticket" and services:
        filters.append(RetrievalDocRow.service.in_(services))
    distance = RetrievalDocRow.embedding.cosine_distance(vector)
    tsquery = func.websearch_to_tsquery("english", query)
    async with db.Session() as session:
        vector_rows = await session.execute(
            select(RetrievalDocRow.id, distance.label("distance"))
            .where(*filters, RetrievalDocRow.embedding.is_not(None))
            .order_by(distance)
            .limit(candidate_limit)
        )
        vector_ids = [id for id, d in vector_rows if 1.0 - d >= min_vector_similarity]
        keyword_rows = await session.execute(
            select(RetrievalDocRow.id)
            .where(*filters, RetrievalDocRow.tsv.op("@@")(tsquery))
            .order_by(func.ts_rank_cd(RetrievalDocRow.tsv, tsquery).desc(), RetrievalDocRow.id)
            .limit(candidate_limit)
        )
        keyword_ids = list(keyword_rows.scalars())
        fused = reciprocal_rank_fusion(vector_ids, keyword_ids)[:limit]
        if not fused:
            return []
        rows = await session.scalars(
            select(RetrievalDocRow).where(RetrievalDocRow.id.in_([id for id, _ in fused]))
        )
        by_id = {row.id: row for row in rows}
    return [
        Retrieved(
            kind=kind,
            id=id,
            title=by_id[id].title or "",
            text="\n".join(value for value in (by_id[id].body, by_id[id].summary) if value),
            status=by_id[id].status if kind == "ticket" else None,
            score=score,
        )
        for id, score in fused
    ]
