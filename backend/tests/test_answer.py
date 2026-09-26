"""End-to-end cited answer contract with deterministic model substitutes."""

import asyncio
import json
import logging
import uuid

import pytest
from conftest import make_token
from langchain_core.embeddings import Embeddings

from app.api.answer_provider import get_answer_generator
from app.api.embedding_provider import get_query_embeddings
from app.api.model_admission import ModelAdmissionGate, get_model_admission_gate
from app.main import app
from app.models.chunk import Chunk
from app.models.document import Document, DocumentStatus
from app.models.knowledge_base import KnowledgeBase
from app.models.tenant import Tenant
from app.rag.answer_generator import AnswerDraft
from app.rag.embeddings import EMBEDDING_DIMENSIONS
from app.schemas.answer import AskResponse
from app.schemas.retrieval import SearchHit
from app.services.answer import NO_ANSWER, stream_answer
from app.services.conversations import append_verified_turn
from app.services.errors import NotFound


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


class FixedStreamingGenerator(FixedGenerator):
    def __init__(self, draft: AnswerDraft | None = None, *, fail: bool = False) -> None:
        super().__init__(draft)
        self.fail = fail

    async def stream(self, question: str, hits: list):
        self.calls += 1
        yield "需要"
        if self.fail:
            raise RuntimeError("provider details must not reach the client")
        yield "经理批准。"
        yield self.draft or AnswerDraft(
            answer="需要经理批准。", cited_chunk_ids=[str(hits[0].chunk_id)]
        )


def parse_sse(body: str) -> list[tuple[str, dict]]:
    frames = [frame for frame in body.strip().split("\n\n") if frame]
    return [
        (
            frame.split("\n", 1)[0].removeprefix("event: "),
            json.loads(frame.split("data: ", 1)[1]),
        )
        for frame in frames
    ]


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
async def test_ask_stream_marks_deltas_provisional_and_verifies_final_source(
    api_client,
):
    client, engine, sessions, settings = api_client
    knowledge_base_id, chunk_id = await create_source(
        client, sessions, settings.embedding_space_id
    )

    class PoolCheckingGenerator(FixedStreamingGenerator):
        async def stream(self, question: str, hits: list):
            assert engine.pool.checkedout() == 0
            async for update in super().stream(question, hits):
                yield update

    embeddings, generator = FixedEmbeddings(), PoolCheckingGenerator()
    app.dependency_overrides[get_query_embeddings] = lambda: embeddings
    app.dependency_overrides[get_answer_generator] = lambda: generator
    path = f"/api/v1/knowledge-bases/{knowledge_base_id}/ask/stream"
    response = await client.post(path, json={"query": "谁批准退款？"})

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache, no-transform"
    events = parse_sse(response.text)
    assert [event for event, _ in events] == ["status", "delta", "delta", "final"]
    assert all(data["provisional"] for event, data in events if event == "delta")
    assert events[-1][1]["grounded"] is True
    assert events[-1][1]["citations"][0]["source"]["chunk_id"] == str(chunk_id)
    assert embeddings.calls == generator.calls == 1


@pytest.mark.asyncio
async def test_ask_stream_retracts_provisional_text_when_citation_is_invalid(
    api_client,
):
    client, _, sessions, settings = api_client
    knowledge_base_id, _ = await create_source(
        client, sessions, settings.embedding_space_id
    )
    app.dependency_overrides[get_query_embeddings] = lambda: FixedEmbeddings()
    app.dependency_overrides[get_answer_generator] = lambda: FixedStreamingGenerator(
        AnswerDraft(answer="需要经理批准。", cited_chunk_ids=[str(uuid.uuid4())])
    )

    response = await client.post(
        f"/api/v1/knowledge-bases/{knowledge_base_id}/ask/stream",
        json={"query": "谁批准退款？"},
    )
    events = parse_sse(response.text)
    assert any(event == "delta" for event, _ in events)
    assert events[-1][0] == "final"
    assert events[-1][1]["grounded"] is False
    assert events[-1][1]["citations"] == []
    assert events[-1][1]["answer"] == NO_ANSWER
    saved = await client.get(
        f"/api/v1/knowledge-bases/{knowledge_base_id}/conversations/{events[-1][1]['conversation_id']}"
    )
    assert saved.status_code == 200
    assert saved.json()["turns"][0]["answer"] == NO_ANSWER
    assert saved.json()["turns"][0]["citations"] == []


@pytest.mark.asyncio
async def test_ask_stream_abstains_or_errors_without_exposing_provider_details(
    api_client,
    caplog,
):
    client, _, sessions, settings = api_client
    knowledge_base_id, _ = await create_source(
        client, sessions, settings.embedding_space_id
    )
    embeddings = FixedEmbeddings()
    generator = FixedStreamingGenerator(fail=True)
    gate = ModelAdmissionGate(1, 0.01)
    app.dependency_overrides[get_model_admission_gate] = lambda: gate
    app.dependency_overrides[get_query_embeddings] = lambda: embeddings
    app.dependency_overrides[get_answer_generator] = lambda: generator
    path = f"/api/v1/knowledge-bases/{knowledge_base_id}/ask/stream"

    with caplog.at_level(logging.INFO, logger="uvicorn.error"):
        failed_generation = await client.post(path, json={"query": "退款"})
    assert failed_generation.status_code == 200
    assert [event for event, _ in parse_sse(failed_generation.text)] == [
        "status",
        "delta",
        "error",
    ]
    assert "provider details" not in failed_generation.text
    history = await client.get(
        f"/api/v1/knowledge-bases/{knowledge_base_id}/conversations"
    )
    assert history.json() == []
    access_log = [
        json.loads(record.getMessage())
        for record in caplog.records
        if record.name == "uvicorn.error" and record.getMessage().startswith("{")
    ][-1]
    assert access_log["status"] == 200
    assert access_log["failure_type"] == "AnswerGenerationFailed"

    embeddings.embed_query = lambda text: (
        [0.0, 1.0] + [0.0] * (EMBEDDING_DIMENSIONS - 2)
    )
    abstained = await client.post(path, json={"query": "不相关", "min_score": 0.5})
    assert [event for event, _ in parse_sse(abstained.text)] == ["status", "final"]
    assert parse_sse(abstained.text)[-1][1]["grounded"] is False
    assert generator.calls == 1

    outsider = {
        "Authorization": f"Bearer {make_token('outsider', tenant_id=str(uuid.uuid4()))}"
    }
    forbidden = await client.post(path, json={"query": "退款"}, headers=outsider)
    assert forbidden.status_code == 404
    assert generator.calls == 1


@pytest.mark.asyncio
async def test_stream_answer_closes_model_stream_on_cancellation():
    closed = asyncio.Event()

    class WaitingGenerator:
        async def stream(self, question: str, hits: list):
            try:
                yield "provisional"
                await asyncio.sleep(60)
            finally:
                closed.set()

    hit = SearchHit(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        document_name="policy.md",
        index_version=1,
        chunk_index=0,
        content="规则",
        score=1,
        page_number=None,
        section_title=None,
        section_path=[],
    )
    updates = stream_answer(
        WaitingGenerator(),
        knowledge_base_id=uuid.uuid4(),
        question="问题",
        hits=[hit],
        generation_timeout_seconds=30,
    )
    assert await anext(updates) == "provisional"
    await updates.aclose()
    assert closed.is_set()


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
    no_evidence_body = no_evidence.json()
    assert uuid.UUID(no_evidence_body.pop("conversation_id"))
    assert no_evidence_body == {
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
async def test_ask_reranks_relevant_evidence_beyond_fifth_vector_hit(api_client):
    client, _, sessions, settings = api_client
    knowledge_base_id, chunk_id = await create_source(
        client, sessions, settings.embedding_space_id
    )
    async with sessions() as db:
        target = await db.get(Chunk, chunk_id)
        target.embedding = [0.6, 0.8] + [0.0] * (EMBEDDING_DIMENSIONS - 2)
        db.add_all(
            Chunk(
                document_id=target.document_id,
                index_version=1,
                chunk_index=index,
                content=f"Unrelated policy {index}",
                token_count=4,
                metadata_={"embedding_space_id": settings.embedding_space_id},
                embedding=[1.0] + [0.0] * (EMBEDDING_DIMENSIONS - 1),
            )
            for index in range(1, 6)
        )
        await db.commit()

    generator = FixedGenerator(
        AnswerDraft(answer="需要经理批准。", cited_chunk_ids=[str(chunk_id)])
    )
    app.dependency_overrides[get_query_embeddings] = lambda: FixedEmbeddings()
    app.dependency_overrides[get_answer_generator] = lambda: generator
    path = f"/api/v1/knowledge-bases/{knowledge_base_id}/ask"

    default = await client.post(path, json={"query": "谁批准退款？"})
    assert default.status_code == 200, default.text
    assert default.json()["grounded"] is True
    assert default.json()["citations"][0]["source"]["chunk_id"] == str(chunk_id)

    restricted = await client.post(path, json={"query": "谁批准退款？", "top_k": 5})
    assert restricted.status_code == 200, restricted.text
    assert restricted.json()["grounded"] is True
    assert restricted.json()["citations"][0]["source"]["chunk_id"] == str(chunk_id)

    # Lexical overlap does not bypass the caller's cosine threshold.
    thresholded = await client.post(
        path, json={"query": "谁批准退款？", "min_score": 0.9}
    )
    assert thresholded.status_code == 200, thresholded.text
    assert thresholded.json()["grounded"] is False
    assert thresholded.json()["answer"] == NO_ANSWER


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


@pytest.mark.asyncio
async def test_conversation_history_restores_verified_turns_and_is_owner_scoped(
    api_client,
):
    client, _, sessions, settings = api_client
    knowledge_base_id, chunk_id = await create_source(
        client, sessions, settings.embedding_space_id
    )
    embeddings, generator = FixedEmbeddings(), FixedStreamingGenerator()
    app.dependency_overrides[get_query_embeddings] = lambda: embeddings
    app.dependency_overrides[get_answer_generator] = lambda: generator
    base = f"/api/v1/knowledge-bases/{knowledge_base_id}"
    viewer = {"Authorization": f"Bearer {make_token('test-user', role='viewer')}"}

    first = await client.post(
        f"{base}/ask", json={"query": "谁批准退款？"}, headers=viewer
    )
    assert first.status_code == 200, first.text
    conversation_id = first.json()["conversation_id"]
    assert uuid.UUID(conversation_id)
    second = await client.post(
        f"{base}/ask/stream",
        json={"query": "再问一次", "conversation_id": conversation_id},
        headers=viewer,
    )
    assert second.status_code == 200
    assert parse_sse(second.text)[-1][1]["conversation_id"] == conversation_id

    summaries = (await client.get(f"{base}/conversations", headers=viewer)).json()
    assert len(summaries) == 1
    assert summaries[0]["title"] == "谁批准退款？"
    restored = (
        await client.get(f"{base}/conversations/{conversation_id}", headers=viewer)
    ).json()
    assert [turn["question"] for turn in restored["turns"]] == [
        "谁批准退款？",
        "再问一次",
    ]
    assert restored["turns"][0]["answer"] == first.json()["answer"]
    assert restored["turns"][0]["citations"][0]["source"]["chunk_id"] == str(chunk_id)
    assert restored["turns"][1]["grounded"] is True

    tenant_id = uuid.uuid5(uuid.NAMESPACE_URL, "enterprise-agent-platform:test-user")
    other_user = {
        "Authorization": f"Bearer {make_token('colleague', tenant_id=str(tenant_id))}"
    }
    assert (await client.get(f"{base}/conversations", headers=other_user)).json() == []
    assert (
        await client.get(f"{base}/conversations/{conversation_id}", headers=other_user)
    ).status_code == 404
    calls_before = embeddings.calls
    assert (
        await client.post(
            f"{base}/ask",
            json={"query": "steal", "conversation_id": conversation_id},
            headers=other_user,
        )
    ).status_code == 404
    assert embeddings.calls == calls_before
    assert (
        await client.delete(
            f"{base}/conversations/{conversation_id}", headers=other_user
        )
    ).status_code == 404
    other_base = await client.post(
        "/api/v1/knowledge-bases", json={"name": "Other knowledge base"}
    )
    assert other_base.status_code == 201
    calls_before = embeddings.calls
    assert (
        await client.post(
            f"/api/v1/knowledge-bases/{other_base.json()['id']}/ask",
            json={"query": "wrong base", "conversation_id": conversation_id},
        )
    ).status_code == 404
    assert embeddings.calls == calls_before

    removed = await client.delete(
        f"{base}/conversations/{conversation_id}", headers=viewer
    )
    assert removed.status_code == 204
    assert (await client.get(f"{base}/conversations", headers=viewer)).json() == []
    assert (
        await client.get(f"{base}/conversations/{conversation_id}", headers=viewer)
    ).status_code == 404


@pytest.mark.asyncio
async def test_conversation_turn_pages_are_bounded_and_newest_first(api_client):
    client, _, sessions, settings = api_client
    knowledge_base_id, _ = await create_source(
        client, sessions, settings.embedding_space_id
    )
    app.dependency_overrides[get_query_embeddings] = lambda: FixedEmbeddings()
    app.dependency_overrides[get_answer_generator] = lambda: FixedGenerator()
    base = f"/api/v1/knowledge-bases/{knowledge_base_id}"
    conversation_id = None
    for question in ("问题一", "问题二", "问题三"):
        result = await client.post(
            f"{base}/ask", json={"query": question, "conversation_id": conversation_id}
        )
        assert result.status_code == 200, result.text
        conversation_id = result.json()["conversation_id"]

    latest = (
        await client.get(f"{base}/conversations/{conversation_id}?limit=2")
    ).json()
    assert [turn["question"] for turn in latest["turns"]] == ["问题二", "问题三"]
    assert latest["has_older"] is True
    older = (
        await client.get(f"{base}/conversations/{conversation_id}?limit=2&offset=2")
    ).json()
    assert [turn["question"] for turn in older["turns"]] == ["问题一"]
    assert older["has_older"] is False


@pytest.mark.asyncio
async def test_conversation_writer_checks_knowledge_base_tenant(api_client):
    client, _, sessions, settings = api_client
    knowledge_base_id, _ = await create_source(
        client, sessions, settings.embedding_space_id
    )
    async with sessions() as db:
        with pytest.raises(NotFound):
            await append_verified_turn(
                db,
                tenant_id=uuid.uuid4(),
                owner_sub="test-user",
                knowledge_base_id=knowledge_base_id,
                conversation_id=None,
                question="问题",
                answer=AskResponse(
                    knowledge_base_id=knowledge_base_id,
                    answer=NO_ANSWER,
                    grounded=False,
                    citations=[],
                ),
            )
