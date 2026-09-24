"""Database-backed tests for the tenant and active-version retrieval boundary."""

import asyncio
import uuid

import pytest
from langchain_core.embeddings import Embeddings

from app.api.embedding_provider import get_query_embeddings
from app.main import app
from app.models.chunk import Chunk
from app.models.document import Document, DocumentStatus
from app.models.knowledge_base import KnowledgeBase
from app.models.tenant import Tenant
from app.rag.embeddings import EMBEDDING_DIMENSIONS
from conftest import make_token


def vector(first: float, second: float = 0.0) -> list[float]:
    return [first, second] + [0.0] * (EMBEDDING_DIMENSIONS - 2)


class QueryEmbeddings(Embeddings):
    def __init__(self, result: list[float] | None = None, delay: float = 0) -> None:
        self.result = result if result is not None else vector(1)
        self.delay = delay
        self.calls = 0

    def embed_query(self, text: str) -> list[float]:
        return self.result

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self.result for _ in texts]

    async def aembed_query(self, text: str) -> list[float]:
        self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        return self.result


async def create_corpus(client, sessions):
    response = await client.post("/api/v1/knowledge-bases", json={"name": "Searchable"})
    assert response.status_code == 201
    knowledge_base_id = uuid.UUID(response.json()["id"])
    async with sessions() as db:
        documents = [
            Document(
                knowledge_base_id=knowledge_base_id,
                filename=name,
                file_type="text/plain",
                storage_uri=f"test/{name}",
                checksum=str(uuid.uuid4()),
                status=DocumentStatus.READY,
                active_index_version=version,
            )
            for name, version in (
                ("strong.txt", 2),
                ("medium.txt", 1),
                ("pending.txt", None),
            )
        ]
        db.add_all(documents)
        await db.flush()
        chunks = [
            Chunk(
                document_id=documents[0].id,
                index_version=2,
                chunk_index=0,
                content="Refunds need approval",
                token_count=4,
                page_number=3,
                section_title="Refunds",
                metadata_={"section_path": ["Policies", "Refunds"]},
                embedding=vector(1),
            ),
            Chunk(
                document_id=documents[1].id,
                index_version=1,
                chunk_index=0,
                content="Approval timing",
                token_count=2,
                metadata_={},
                embedding=vector(0.8, 0.6),
            ),
            Chunk(
                document_id=documents[0].id,
                index_version=1,
                chunk_index=0,
                content="Superseded answer",
                token_count=2,
                metadata_={},
                embedding=vector(1),
            ),
            Chunk(
                document_id=documents[2].id,
                index_version=1,
                chunk_index=0,
                content="Unpublished answer",
                token_count=2,
                metadata_={},
                embedding=vector(1),
            ),
        ]
        db.add_all(chunks)
        await db.commit()
        return knowledge_base_id, documents, chunks


@pytest.mark.asyncio
async def test_search_orders_authorized_active_chunks_and_returns_sources(api_client):
    client, _, sessions, _ = api_client
    knowledge_base_id, documents, chunks = await create_corpus(client, sessions)
    embeddings = QueryEmbeddings()
    app.dependency_overrides[get_query_embeddings] = lambda: embeddings
    path = f"/api/v1/knowledge-bases/{knowledge_base_id}/search"

    response = await client.post(path, json={"query": " refund policy "})
    assert response.status_code == 200, response.text
    hits = response.json()["hits"]
    assert [hit["chunk_id"] for hit in hits] == [str(chunks[0].id), str(chunks[1].id)]
    assert hits[0]["score"] == pytest.approx(1)
    assert hits[1]["score"] == pytest.approx(0.8)
    assert hits[0]["document_id"] == str(documents[0].id)
    assert hits[0]["document_name"] == "strong.txt"
    assert hits[0]["page_number"] == 3
    assert hits[0]["section_path"] == ["Policies", "Refunds"]
    assert (
        len(
            (await client.post(path, json={"query": "policy", "top_k": 1})).json()[
                "hits"
            ]
        )
        == 1
    )
    threshold = await client.post(path, json={"query": "policy", "min_score": 0.9})
    assert [hit["chunk_id"] for hit in threshold.json()["hits"]] == [str(chunks[0].id)]
    assert embeddings.calls == 3


@pytest.mark.asyncio
async def test_search_checks_tenant_before_embedding_and_allows_viewer(api_client):
    client, _, sessions, _ = api_client
    knowledge_base_id, _, _ = await create_corpus(client, sessions)
    embeddings = QueryEmbeddings()
    app.dependency_overrides[get_query_embeddings] = lambda: embeddings
    path = f"/api/v1/knowledge-bases/{knowledge_base_id}/search"
    viewer = {"Authorization": f"Bearer {make_token('test-user', role='viewer')}"}
    assert (
        await client.post(path, json={"query": "policy"}, headers=viewer)
    ).status_code == 200

    other_tenant = uuid.uuid4()
    async with sessions() as db:
        db.add(Tenant(id=other_tenant, name="Other tenant"))
        db.add(
            KnowledgeBase(
                id=uuid.uuid4(),
                tenant_id=other_tenant,
                owner_sub="outsider",
                name="Private",
            )
        )
        await db.commit()
    outsider = {
        "Authorization": f"Bearer {make_token('outsider', tenant_id=str(other_tenant))}"
    }
    forbidden = await client.post(path, json={"query": "policy"}, headers=outsider)
    assert forbidden.status_code == 404
    assert embeddings.calls == 1


@pytest.mark.asyncio
async def test_search_rejects_provider_failures_and_invalid_requests(api_client):
    client, _, sessions, settings = api_client
    knowledge_base_id, _, _ = await create_corpus(client, sessions)
    path = f"/api/v1/knowledge-bases/{knowledge_base_id}/search"
    app.dependency_overrides[get_query_embeddings] = lambda: QueryEmbeddings()
    for payload in (
        {"query": " "},
        {"query": "policy", "top_k": 21},
        {"query": "policy", "min_score": -0.1},
    ):
        assert (await client.post(path, json=payload)).status_code == 422

    app.dependency_overrides[get_query_embeddings] = lambda: QueryEmbeddings(vector(0))
    assert (await client.post(path, json={"query": "policy"})).status_code == 503
    settings.retrieval_embedding_timeout_seconds = 0.001
    app.dependency_overrides[get_query_embeddings] = lambda: QueryEmbeddings(delay=0.05)
    assert (await client.post(path, json={"query": "policy"})).status_code == 503

    app.dependency_overrides.pop(get_query_embeddings)
    assert (await client.post(path, json={"query": "policy"})).status_code == 503
