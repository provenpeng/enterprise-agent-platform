"""Exercise the API and database path used by the Chromium workspace test."""

import uuid

import pytest
from langchain_core.embeddings import Embeddings

from app.agent.model import DiagnosticPlan, ModelCall, TokenUsage
from app.api.answer_provider import get_answer_generator
from app.api.diagnostic_provider import get_diagnostic_model
from app.api.embedding_provider import get_query_embeddings
from app.business.demo_seed import seed_demo_orders
from app.main import app
from app.rag.answer_generator import AnswerDraft
from app.rag.embeddings import EMBEDDING_DIMENSIONS
from app.services.indexer import process_one_index_job


class LocalEmbeddings(Embeddings):
    def embed_query(self, text: str) -> list[float]:
        return [1.0] + [0.0] * (EMBEDDING_DIMENSIONS - 1)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_query(text) for text in texts]

    async def aembed_query(self, text: str) -> list[float]:
        return self.embed_query(text)


class LocalAnswer:
    async def generate(self, question: str, hits) -> AnswerDraft:
        return AnswerDraft(
            answer="退款申请应在支付成功后 30 天内提交。",
            cited_chunk_ids=[str(hits[0].chunk_id)],
        )


class LocalDiagnostic:
    async def plan(self, question: str) -> ModelCall[DiagnosticPlan]:
        return ModelCall(
            value=DiagnosticPlan(order_id="DEMO-WINDOW", search_policy=False),
            usage=TokenUsage(input_tokens=5, output_tokens=2, total_tokens=7),
        )


@pytest.mark.asyncio
async def test_login_upload_index_answer_diagnose_and_restore(api_client) -> None:
    client, _, sessions, settings = api_client
    identity = await client.get("/api/v1/me")
    assert identity.status_code == 200
    created = await client.post(
        "/api/v1/knowledge-bases", json={"name": "Workspace flow"}
    )
    assert created.status_code == 201
    knowledge_base_id = created.json()["id"]
    document = await client.post(
        f"/api/v1/knowledge-bases/{knowledge_base_id}/documents",
        files={
            "file": (
                "policy.md",
                b"# Refund\n\n## REFUND_WINDOW_EXPIRED\n\nPaid orders may request a refund within 30 days.",
                "text/markdown",
            )
        },
    )
    assert document.status_code == 201
    embeddings = LocalEmbeddings()
    assert await process_one_index_job(sessions, settings, embeddings, len)
    indexed = await client.get(f"/api/v1/documents/{document.json()['id']}")
    assert indexed.json()["status"] == "READY"

    app.dependency_overrides[get_query_embeddings] = lambda: embeddings
    app.dependency_overrides[get_answer_generator] = LocalAnswer
    search = await client.post(
        f"/api/v1/knowledge-bases/{knowledge_base_id}/search",
        json={"query": "When may a paid order request a refund?"},
    )
    assert search.status_code == 200 and search.json()["hits"]
    answer = await client.post(
        f"/api/v1/knowledge-bases/{knowledge_base_id}/ask",
        json={"query": "When may a paid order request a refund?"},
    )
    assert answer.status_code == 200 and answer.json()["grounded"]
    assert answer.json()["citations"]

    tenant_id = uuid.uuid5(uuid.NAMESPACE_URL, "enterprise-agent-platform:test-user")
    async with sessions() as db:
        await seed_demo_orders(db, tenant_id)
    app.dependency_overrides[get_diagnostic_model] = LocalDiagnostic
    diagnosis = await client.post(
        f"/api/v1/knowledge-bases/{knowledge_base_id}/diagnose",
        json={
            "question": "DEMO-WINDOW why did the refund fail?",
            "order_id": "DEMO-WINDOW",
        },
    )
    assert diagnosis.status_code == 200, diagnosis.text
    result = diagnosis.json()
    assert result["status"] == "ANSWERED"
    assert result["citations"]
    restored = await client.get(
        f"/api/v1/agent-runs/mine/{result['run_id']}?knowledge_base_id={knowledge_base_id}"
    )
    assert restored.status_code == 200
    assert restored.json()["response"] == result
