"""Real LangGraph routing against tenant-scoped demo and pgvector data."""

import asyncio
import uuid

import pytest
from conftest import make_token
from langchain_core.embeddings import Embeddings
from sqlalchemy import select, text

from app.agent.model import DiagnosticDraft, DiagnosticPlan, ModelCall, TokenUsage
from app.api.diagnostic_provider import get_diagnostic_model
from app.api.embedding_provider import get_query_embeddings
from app.business.demo_seed import seed_demo_orders
from app.business.orders import OrderLookupTool
from app.main import app
from app.models.agent_run import AgentRun, AgentRunStatus, AgentRunStep
from app.models.chunk import Chunk
from app.models.document import Document, DocumentStatus
from app.models.tenant import Tenant
from app.rag.embeddings import EMBEDDING_DIMENSIONS


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


class FixedDiagnosticModel:
    def __init__(self, order_id: str | None, *, search_policy: bool) -> None:
        self.order_id = order_id
        self.search_policy = search_policy
        self.citation_override: str | None = None
        self.plan_calls = 0
        self.explain_calls = 0
        self.delay = 0.0

    async def plan(self, question: str) -> ModelCall[DiagnosticPlan]:
        self.plan_calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        return ModelCall(
            value=DiagnosticPlan(
                order_id=self.order_id, search_policy=self.search_policy
            ),
            usage=TokenUsage(input_tokens=12, output_tokens=4, total_tokens=16),
        )

    async def explain(self, question: str, order, hits) -> ModelCall[DiagnosticDraft]:
        self.explain_calls += 1
        return ModelCall(
            value=DiagnosticDraft(
                answer=f"{order.order_id} 的退款因规则期限已过而失败。",
                cited_chunk_ids=[self.citation_override or str(hits[0].chunk_id)],
            ),
            usage=TokenUsage(input_tokens=24, output_tokens=8, total_tokens=32),
        )


async def create_context(client, sessions) -> tuple[uuid.UUID, uuid.UUID]:
    response = await client.post(
        "/api/v1/knowledge-bases", json={"name": "Diagnostics"}
    )
    assert response.status_code == 201
    knowledge_base_id = uuid.UUID(response.json()["id"])
    tenant_id = uuid.uuid5(uuid.NAMESPACE_URL, "enterprise-agent-platform:test-user")
    async with sessions() as db:
        await seed_demo_orders(db, tenant_id)
        document = Document(
            knowledge_base_id=knowledge_base_id,
            filename="refund_rules.md",
            file_type="text/markdown",
            storage_uri="test/refund_rules.md",
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
            content="支付后 30 天内可申请退款。",
            token_count=10,
            metadata_={
                "section_path": ["退款规则"],
                "embedding_model": "text-embedding-3-small",
            },
            embedding=[1.0] + [0.0] * (EMBEDDING_DIMENSIONS - 1),
        )
        db.add(chunk)
        await db.commit()
        return knowledge_base_id, chunk.id


@pytest.mark.asyncio
async def test_diagnostic_routes_to_order_and_policy_with_verified_citation(api_client):
    client, _, sessions, _ = api_client
    knowledge_base_id, chunk_id = await create_context(client, sessions)
    model, embeddings = (
        FixedDiagnosticModel("DEMO-WINDOW", search_policy=True),
        FixedEmbeddings(),
    )
    app.dependency_overrides[get_diagnostic_model] = lambda: model
    app.dependency_overrides[get_query_embeddings] = lambda: embeddings
    viewer = {"Authorization": f"Bearer {make_token('test-user', role='viewer')}"}
    path = f"/api/v1/knowledge-bases/{knowledge_base_id}/diagnose"

    response = await client.post(
        path, json={"question": "DEMO-WINDOW 为什么退款失败？"}, headers=viewer
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "ANSWERED"
    assert body["order"]["order_id"] == "DEMO-WINDOW"
    assert body["order"]["refund_attempts"][0]["reason_code"] == "REFUND_WINDOW_EXPIRED"
    assert body["answer"].endswith("来源：[1]")
    assert body["citations"][0]["source"]["chunk_id"] == str(chunk_id)
    assert (model.plan_calls, model.explain_calls, embeddings.calls) == (1, 1, 1)
    assert body["run_id"]
    admin_run = await client.get(f"/api/v1/agent-runs/{body['run_id']}")
    assert admin_run.status_code == 200
    trace = admin_run.json()
    assert trace["status"] == "SUCCEEDED"
    assert trace["outcome"] == "ANSWERED"
    assert trace["model_name"] == "gpt-4o-mini"
    assert (trace["input_tokens"], trace["output_tokens"], trace["total_tokens"]) == (
        36,
        12,
        48,
    )
    assert [step["name"] for step in trace["steps"]] == [
        "plan",
        "lookup_order",
        "retrieve_policy",
        "compose",
    ]
    assert trace["steps"][1]["output_data"]["order_id"] == "DEMO-WINDOW"
    assert trace["steps"][2]["output_data"]["hits"][0]["chunk_id"] == str(chunk_id)
    assert "content" not in trace["steps"][2]["output_data"]["hits"][0]
    assert "answer" not in trace["steps"][3]["output_data"]
    assert trace["steps"][3]["total_tokens"] == 32
    assert (
        await client.get(f"/api/v1/agent-runs/{body['run_id']}", headers=viewer)
    ).status_code == 403
    assert len((await client.get("/api/v1/agent-runs?limit=1")).json()) == 1
    other_tenant = uuid.uuid4()
    async with sessions() as db:
        db.add(Tenant(id=other_tenant, name="Audit outsider"))
        await db.commit()
    outsider = {
        "Authorization": f"Bearer {make_token('outsider', tenant_id=str(other_tenant))}"
    }
    assert (
        await client.get(f"/api/v1/agent-runs/{body['run_id']}", headers=outsider)
    ).status_code == 404
    assert (await client.get("/api/v1/agent-runs", headers=outsider)).json() == []

    model.order_id = "DEMO-SUCCESS"
    explicit = await client.post(
        path,
        json={"question": "为什么失败？", "order_id": "DEMO-WINDOW"},
    )
    assert explicit.json()["order"]["order_id"] == "DEMO-WINDOW"

    model.order_id = "DEMO-WINDOW"
    model.citation_override = str(uuid.uuid4())
    invalid = await client.post(path, json={"question": "DEMO-WINDOW 为什么退款失败？"})
    assert invalid.json()["status"] == "BUSINESS_FACTS_ONLY"
    assert invalid.json()["citations"] == []
    assert "REFUND_WINDOW_EXPIRED" in invalid.json()["answer"]


@pytest.mark.asyncio
async def test_diagnostic_short_circuits_missing_order_and_status_only(api_client):
    client, _, sessions, _ = api_client
    knowledge_base_id, _ = await create_context(client, sessions)
    model, embeddings = (
        FixedDiagnosticModel(None, search_policy=False),
        FixedEmbeddings(),
    )
    app.dependency_overrides[get_diagnostic_model] = lambda: model
    app.dependency_overrides[get_query_embeddings] = lambda: embeddings
    path = f"/api/v1/knowledge-bases/{knowledge_base_id}/diagnose"

    missing_id = await client.post(path, json={"question": "这个订单退款了吗？"})
    assert missing_id.json()["status"] == "NEEDS_ORDER_ID"
    assert embeddings.calls == model.explain_calls == 0
    model.order_id = "DEMO-NOT-FOUND"
    missing_order = await client.post(path, json={"question": "这个订单退款了吗？"})
    assert missing_order.json()["status"] == "ORDER_NOT_FOUND"
    assert embeddings.calls == model.explain_calls == 0

    model.order_id = "DEMO-SUCCESS"
    status = await client.post(path, json={"question": "DEMO-SUCCESS 的退款状态？"})
    assert status.json()["status"] == "BUSINESS_FACTS_ONLY"
    assert "SUCCEEDED" in status.json()["answer"]
    assert embeddings.calls == model.explain_calls == 0
    assert (
        await client.post(path, json={"question": "status", "order_id": "bad_id"})
    ).status_code == 422

    model.order_id = "DEMO-WINDOW"
    model.search_policy = True
    embeddings.embed_query = lambda text: (
        [0.0, 1.0] + [0.0] * (EMBEDDING_DIMENSIONS - 2)
    )
    no_policy = await client.post(path, json={"question": "DEMO-WINDOW 为什么失败？"})
    assert no_policy.json()["status"] == "BUSINESS_FACTS_ONLY"
    assert no_policy.json()["citations"] == []
    assert embeddings.calls == 1
    assert model.explain_calls == 0


@pytest.mark.asyncio
async def test_diagnostic_rejects_cross_tenant_kb_before_model_calls(api_client):
    client, _, sessions, settings = api_client
    knowledge_base_id, _ = await create_context(client, sessions)
    model, embeddings = (
        FixedDiagnosticModel("DEMO-WINDOW", search_policy=True),
        FixedEmbeddings(),
    )
    app.dependency_overrides[get_diagnostic_model] = lambda: model
    app.dependency_overrides[get_query_embeddings] = lambda: embeddings
    other_tenant = uuid.uuid4()
    async with sessions() as db:
        db.add(Tenant(id=other_tenant, name="Other tenant"))
        await db.commit()
    outsider = {
        "Authorization": f"Bearer {make_token('outsider', tenant_id=str(other_tenant))}"
    }
    path = f"/api/v1/knowledge-bases/{knowledge_base_id}/diagnose"
    assert (
        await client.post(path, json={"question": "DEMO-WINDOW?"}, headers=outsider)
    ).status_code == 404
    assert model.plan_calls == embeddings.calls == 0
    assert (await client.get("/api/v1/agent-runs")).json() == []

    model.delay = 0.05
    settings.diagnostic_planning_timeout_seconds = 0.001
    assert (
        await client.post(path, json={"question": "DEMO-WINDOW?"})
    ).status_code == 503


@pytest.mark.asyncio
async def test_diagnostic_masks_business_tool_failure(api_client, monkeypatch):
    client, _, sessions, _ = api_client
    knowledge_base_id, _ = await create_context(client, sessions)
    model, embeddings = (
        FixedDiagnosticModel("DEMO-WINDOW", search_policy=True),
        FixedEmbeddings(),
    )
    app.dependency_overrides[get_diagnostic_model] = lambda: model
    app.dependency_overrides[get_query_embeddings] = lambda: embeddings

    async def fail_lookup(self, order_id):
        await self._db.execute(text("SELECT missing_column FROM demo_orders LIMIT 1"))

    monkeypatch.setattr(OrderLookupTool, "lookup", fail_lookup)
    response = await client.post(
        f"/api/v1/knowledge-bases/{knowledge_base_id}/diagnose",
        json={"question": "DEMO-WINDOW 为什么退款失败？"},
    )
    assert response.status_code == 503
    assert response.json() == {"detail": "Order lookup is unavailable"}
    assert embeddings.calls == model.explain_calls == 0
    async with sessions() as db:
        run = await db.scalar(select(AgentRun))
        steps = list(
            await db.scalars(select(AgentRunStep).order_by(AgentRunStep.sequence))
        )
        assert run is not None and run.status == AgentRunStatus.FAILED
        assert run.error_code == "UpstreamUnavailable"
        assert [step.name for step in steps] == ["plan", "lookup_order"]
        assert steps[-1].error_code == "UpstreamUnavailable"
        assert "missing_column" not in str(steps[-1].output_data)
