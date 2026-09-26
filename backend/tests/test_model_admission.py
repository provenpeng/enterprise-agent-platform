"""Model admission is bounded, tenant-safe, and releases capacity on errors."""

import uuid

import pytest
from conftest import make_token
from fastapi import HTTPException
from langchain_core.embeddings import Embeddings

from app.api.answer_provider import get_answer_generator
from app.api.diagnostic_provider import get_diagnostic_model
from app.api.embedding_provider import get_query_embeddings
from app.api.model_admission import ModelAdmissionGate, get_model_admission_gate
from app.main import app
from app.rag.embeddings import EMBEDDING_DIMENSIONS


@pytest.mark.asyncio
async def test_gate_times_out_and_recovers_after_failure():
    gate = ModelAdmissionGate(max_inflight=1, wait_seconds=0.01)
    with pytest.raises(ValueError):
        async with gate.slot():
            with pytest.raises(HTTPException) as rejected:
                async with gate.slot():
                    pass
            assert rejected.value.status_code == 503
            assert rejected.value.headers == {"Retry-After": "1"}
            raise ValueError("caller failed")
    async with gate.slot():
        pass


@pytest.mark.asyncio
async def test_api_admits_only_authorized_model_work_without_db_lease(api_client):
    client, engine, _, _ = api_client
    response = await client.post(
        "/api/v1/knowledge-bases", json={"name": "Admission test"}
    )
    assert response.status_code == 201
    base = f"/api/v1/knowledge-bases/{response.json()['id']}"
    gate = ModelAdmissionGate(max_inflight=1, wait_seconds=0.01)
    app.dependency_overrides[get_model_admission_gate] = lambda: gate

    def unexpected_provider():
        raise AssertionError("model dependency must not run when capacity is full")

    app.dependency_overrides[get_query_embeddings] = unexpected_provider
    app.dependency_overrides[get_answer_generator] = unexpected_provider
    app.dependency_overrides[get_diagnostic_model] = unexpected_provider

    async with gate.slot():
        for endpoint, body in (
            ("search", {"query": "policy"}),
            ("ask", {"query": "policy"}),
            ("diagnose", {"question": "DEMO-WINDOW?", "order_id": "DEMO-WINDOW"}),
        ):
            busy = await client.post(f"{base}/{endpoint}", json=body)
            assert busy.status_code == 503, busy.text
            assert busy.json() == {"detail": "Model capacity is busy"}
            assert busy.headers["retry-after"] == "1"
            assert engine.pool.checkedout() == 0

        outsider = {
            "Authorization": f"Bearer {make_token('outsider', tenant_id=str(uuid.uuid4()))}"
        }
        hidden = await client.post(
            f"{base}/search", json={"query": "policy"}, headers=outsider
        )
        assert hidden.status_code == 404
        assert (await client.get("/api/v1/health")).status_code == 200

    class PoolCheckingEmbeddings(Embeddings):
        def embed_query(self, text: str) -> list[float]:
            return [1.0] + [0.0] * (EMBEDDING_DIMENSIONS - 1)

        def embed_documents(self, texts: list[str]) -> list[list[float]]:
            return [self.embed_query(text) for text in texts]

        async def aembed_query(self, text: str) -> list[float]:
            assert engine.pool.checkedout() == 0
            return self.embed_query(text)

    app.dependency_overrides[get_query_embeddings] = lambda: PoolCheckingEmbeddings()
    admitted = await client.post(f"{base}/search", json={"query": "policy"})
    assert admitted.status_code == 200, admitted.text
    assert admitted.json()["hits"] == []
