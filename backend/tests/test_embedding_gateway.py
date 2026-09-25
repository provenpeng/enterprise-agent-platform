"""Short local vectors retain cosine geometry in the fixed pgvector column."""

import math

import pytest
from langchain_core.embeddings import Embeddings

from app.rag import embeddings as embedding_module
from app.rag.embeddings import (
    EMBEDDING_DIMENSIONS,
    FixedDimensionEmbeddings,
    create_embeddings,
    pad_embedding,
)


class ShortEmbeddings(Embeddings):
    def embed_query(self, text: str) -> list[float]:
        return [3.0, 4.0]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[3.0, 4.0] for _ in texts]


@pytest.mark.asyncio
async def test_native_vectors_are_padded_and_validated() -> None:
    adapter = FixedDimensionEmbeddings(ShortEmbeddings(), native_dimensions=2)
    query = await adapter.aembed_query("query")
    documents = await adapter.aembed_documents(["document"])
    assert len(query) == EMBEDDING_DIMENSIONS
    assert query[:2] == [3.0, 4.0]
    assert all(value == 0 for value in query[2:])
    assert documents == [query]
    assert math.dist(query, documents[0]) == 0
    with pytest.raises(ValueError, match="dimension"):
        pad_embedding([1.0], native_dimensions=2)
    with pytest.raises(ValueError, match="invalid vector"):
        pad_embedding([0.0, 0.0], native_dimensions=2)


def test_embedding_factory_uses_openai_compatible_gateway(monkeypatch) -> None:
    calls = []

    class FakeOpenAIEmbeddings(ShortEmbeddings):
        def __init__(self, **kwargs):
            calls.append(kwargs)

    monkeypatch.setattr(embedding_module, "OpenAIEmbeddings", FakeOpenAIEmbeddings)
    adapter = create_embeddings(
        model="nomic-embed-text",
        api_key="ollama",
        base_url="http://127.0.0.1:11434/v1",
        timeout_seconds=15,
        native_dimensions=2,
    )
    assert adapter.embed_query("query")[:2] == [3.0, 4.0]
    assert calls == [
        {
            "model": "nomic-embed-text",
            "api_key": "ollama",
            "base_url": "http://127.0.0.1:11434/v1",
            "request_timeout": 15,
            "max_retries": 0,
            "check_embedding_ctx_length": False,
        }
    ]
