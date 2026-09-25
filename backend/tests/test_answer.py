"""End-to-end cited answer contract with deterministic model substitutes."""

import asyncio
import uuid

import pytest
from conftest import make_token
from langchain_core.embeddings import Embeddings

from app.api.answer_provider import get_answer_generator
from app.api.embedding_provider import get_query_embeddings
from app.main import app
from app.models.chunk import Chunk
from app.models.document import Document, DocumentStatus
from app.models.knowledge_base import KnowledgeBase
from app.models.tenant import Tenant
from app.rag.answer_generator import AnswerDraft
from app.rag.embeddings import EMBEDDING_DIMENSIONS
from app.services.answer import NO_ANSWER


class FixedEmbeddings(Embeddings):
    def __init__(self) -> None:
        self.calls = 0

    def embed_query(self, text: str) -> list[float]:
        return [1.0] + [0.0] * (EMBEDDING_DIMENSIONS - 1)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_query(text) for text in texts]

    async def aembed_query(self, text: str) -> list[float]:
        self.calls += 1
        return self.embed_query(text)


class FixedGenerator:
    def __init__(self, draft: AnswerDraft | None = None, *, delay: float = 0) -> None:
        self.draft = draft
        self.delay = delay
        self.calls = 0

    async def generate(self, question: str, hits: list) -> AnswerDraft:
        self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.draft is not None:
            return self.draft
        return AnswerDraft(
            answer="需要经理批准。", cited_chunk_ids=[str(hits[0].chunk_id)]
        )


async def create_source(client, sessions, space_id: str) -> tuple[uuid.UUID, uuid.UUID]:
    response = await client.post("/api/v1/knowledge-bases", json={"name": "Q&A"})
    assert response.status_code == 201
    knowledge_base_id = uuid.UUID(response.json()["id"])
    async with sessions() as db:
        document = Document(
            knowledge_base_id=knowledge_base_id,
            filename="policy.md",
            file_type="text/markdown",
            storage_uri="test/policy.md",
            checksum=str(uuid.uuid4()),
            status=DocumentStatus.READY,
            active_index_version=1,
        )
        db.add(document)
        await db.flush()
        chunk = Chunk(
            document_id=document.id,
            index_version=1,
            chunk_index=0,
            content="退款需要经理批准。",
            token_count=5,
            page_number=2,
            section_title="退款",
            metadata_={
                "section_path": ["政策", "退款"],
                "embedding_model": "text-embedding-3-small",
                "embedding_space_id": space_id,
            },
            embedding=[1.0] + [0.0] * (EMBEDDING_DIMENSIONS - 1),
        )
        db.add(chunk)
        await db.commit()
        return knowledge_base_id, chunk.id


@pytest.mark.asyncio
async def test_ask_returns_server_verified_citation(api_client):
    client, _, sessions, settings = api_client
    knowledge_base_id, chunk_id = await create_source(
        client, sessions, settings.embedding_space_id
    )
    embeddings, generator = FixedEmbeddings(), FixedGenerator()
    app.dependency_overrides[get_query_embeddings] = lambda: embeddings
    app.dependency_overrides[get_answer_generator] = lambda: generator
    viewer = {"Authorization": f"Bearer {make_token('test-user', role='viewer')}"}

    response = await client.post(
        f"/api/v1/knowledge-bases/{knowledge_base_id}/ask",
        json={"query": "谁批准退款？"},
        headers=viewer,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["grounded"] is True
    assert body["answer"] == "需要经理批准。\n\n来源：[1]"
    assert body["citations"][0]["number"] == 1
    assert body["citations"][0]["source"]["chunk_id"] == str(chunk_id)
    assert body["citations"][0]["source"]["document_name"] == "policy.md"
    assert body["citations"][0]["source"]["page_number"] == 2
    assert body["citations"][0]["source"]["section_path"] == ["政策", "退款"]
    assert embeddings.calls == generator.calls == 1


@pytest.mark.asyncio
async def test_ask_abstains_without_evidence_or_valid_citations(api_client):
    client, _, sessions, settings = api_client
    knowledge_base_id, chunk_id = await create_source(
        client, sessions, settings.embedding_space_id
    )
    embeddings, generator = FixedEmbeddings(), FixedGenerator()
    app.dependency_overrides[get_query_embeddings] = lambda: embeddings
    app.dependency_overrides[get_answer_generator] = lambda: generator
    path = f"/api/v1/knowledge-bases/{knowledge_base_id}/ask"

    # An orthogonal query has no evidence above the threshold.
    embeddings.embed_query = lambda text: (
        [0.0, 1.0] + [0.0] * (EMBEDDING_DIMENSIONS - 2)
    )
    no_evidence = await client.post(path, json={"query": "unrelated", "min_score": 0.5})
    assert no_evidence.json() == {
        "knowledge_base_id": str(knowledge_base_id),
        "answer": NO_ANSWER,
        "grounded": False,
        "citations": [],
    }
    assert generator.calls == 0

    embeddings.embed_query = lambda text: [1.0] + [0.0] * (EMBEDDING_DIMENSIONS - 1)
    for draft in (
        AnswerDraft(answer="fabricated", cited_chunk_ids=[str(uuid.uuid4())]),
        AnswerDraft(answer="uncited", cited_chunk_ids=[]),
        AnswerDraft(answer=" ", cited_chunk_ids=[str(chunk_id)]),
    ):
        generator.draft = draft
        response = await client.post(path, json={"query": "policy"})
        assert response.status_code == 200
        assert response.json()["grounded"] is False
        assert response.json()["answer"] == NO_ANSWER
        assert response.json()["citations"] == []


@pytest.mark.asyncio
async def test_ask_authorizes_before_model_calls_and_bounds_generation(api_client):
    client, _, sessions, settings = api_client
    knowledge_base_id, _ = await create_source(
        client, sessions, settings.embedding_space_id
    )
    embeddings, generator = FixedEmbeddings(), FixedGenerator(delay=0.05)
    app.dependency_overrides[get_query_embeddings] = lambda: embeddings
    app.dependency_overrides[get_answer_generator] = lambda: generator
    path = f"/api/v1/knowledge-bases/{knowledge_base_id}/ask"

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
    assert (
        await client.post(path, json={"query": "policy"}, headers=outsider)
    ).status_code == 404
    assert embeddings.calls == generator.calls == 0
    settings.answer_generation_timeout_seconds = 0.001
    assert (await client.post(path, json={"query": "policy"})).status_code == 503
    assert (
        await client.post(path, json={"query": "policy", "top_k": 11})
    ).status_code == 422


@pytest.mark.asyncio
async def test_ask_releases_db_connection_during_external_model_calls(api_client):
    client, engine, sessions, settings = api_client
    knowledge_base_id, _ = await create_source(
        client, sessions, settings.embedding_space_id
    )

    class PoolCheckingEmbeddings(FixedEmbeddings):
        async def aembed_query(self, text: str) -> list[float]:
            assert engine.pool.checkedout() == 0
            return await super().aembed_query(text)

    class PoolCheckingGenerator(FixedGenerator):
        async def generate(self, question: str, hits: list) -> AnswerDraft:
            assert engine.pool.checkedout() == 0
            return await super().generate(question, hits)

    embeddings, generator = PoolCheckingEmbeddings(), PoolCheckingGenerator()
    app.dependency_overrides[get_query_embeddings] = lambda: embeddings
    app.dependency_overrides[get_answer_generator] = lambda: generator
    response = await client.post(
        f"/api/v1/knowledge-bases/{knowledge_base_id}/ask",
        json={"query": "谁批准退款？"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["grounded"] is True
