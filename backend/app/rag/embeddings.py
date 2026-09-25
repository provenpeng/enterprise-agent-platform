"""Vector contract shared by indexing and retrieval."""

import math

from langchain_core.embeddings import Embeddings
from langchain_openai import OpenAIEmbeddings

from app.rag.embedding_space import DEFAULT_EMBEDDING_BASE_URL

EMBEDDING_DIMENSIONS = 1536


def validate_embedding(vector: list[float]) -> None:
    if (
        len(vector) != EMBEDDING_DIMENSIONS
        or not all(
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(value)
            for value in vector
        )
        or not any(value != 0 for value in vector)
    ):
        raise ValueError("Embedding provider returned an invalid vector")


def pad_embedding(vector: list[float], native_dimensions: int) -> list[float]:
    """Zero padding preserves cosine distance within one embedding model."""
    if len(vector) != native_dimensions:
        raise ValueError("Embedding provider returned an unexpected vector dimension")
    stored = vector + [0.0] * (EMBEDDING_DIMENSIONS - native_dimensions)
    validate_embedding(stored)
    return stored


class FixedDimensionEmbeddings(Embeddings):
    def __init__(self, delegate: Embeddings, native_dimensions: int) -> None:
        self._delegate = delegate
        self._native_dimensions = native_dimensions

    def embed_query(self, text: str) -> list[float]:
        return pad_embedding(self._delegate.embed_query(text), self._native_dimensions)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [
            pad_embedding(vector, self._native_dimensions)
            for vector in self._delegate.embed_documents(texts)
        ]

    async def aembed_query(self, text: str) -> list[float]:
        return pad_embedding(
            await self._delegate.aembed_query(text), self._native_dimensions
        )

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        return [
            pad_embedding(vector, self._native_dimensions)
            for vector in await self._delegate.aembed_documents(texts)
        ]


def create_embeddings(
    *,
    model: str,
    api_key: str,
    base_url: str | None,
    timeout_seconds: float,
    native_dimensions: int,
) -> Embeddings:
    delegate = OpenAIEmbeddings(
        model=model,
        api_key=api_key,
        base_url=base_url or DEFAULT_EMBEDDING_BASE_URL,
        request_timeout=timeout_seconds,
        max_retries=0,
        check_embedding_ctx_length=False,
    )
    return FixedDimensionEmbeddings(delegate, native_dimensions)
