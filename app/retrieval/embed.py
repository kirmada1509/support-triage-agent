"""Local 384-dimensional embeddings behind a replaceable async interface."""

import asyncio
from functools import cached_property
from typing import Protocol

from app.tables import EMBEDDING_DIM

DIMENSIONS = EMBEDDING_DIM
MODEL_NAME = "BAAI/bge-small-en-v1.5"
MODEL_REVISION = "5c38ec7c405ec4b44b94cc5a9bb96e735b38267a"
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


class EmbeddingClient(Protocol):
    async def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    async def embed_query(self, text: str) -> list[float]: ...


class LocalBGE:
    """Load the small model lazily; CPU work stays off the event loop."""

    @cached_property
    def model(self):
        from sentence_transformers import SentenceTransformer

        return SentenceTransformer(MODEL_NAME, revision=MODEL_REVISION)

    def _encode(self, texts: list[str]) -> list[list[float]]:
        vectors = self.model.encode(texts, normalize_embeddings=True)
        output = vectors.tolist()
        if any(len(vector) != DIMENSIONS for vector in output):
            raise ValueError(f"{MODEL_NAME} must return {DIMENSIONS} dimensions")
        return output

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        return await asyncio.to_thread(self._encode, texts)

    async def embed_query(self, text: str) -> list[float]:
        return (await asyncio.to_thread(self._encode, [QUERY_PREFIX + text]))[0]
