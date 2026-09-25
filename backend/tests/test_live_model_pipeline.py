"""Opt-in exercise of Ollama embeddings and a real compatible chat model."""

import os
import uuid
from pathlib import Path

import pytest
import tiktoken

from app.business.demo_seed import seed_demo_orders
from app.core.config import get_settings
from app.rag.embeddings import create_embeddings
from app.services.index_jobs import TOKENIZER_NAME
from app.services.indexer import process_one_index_job


@pytest.mark.skipif(
    os.getenv("EAP_LIVE_MODELS") != "1",
    reason="Run explicitly with Ollama embeddings and a configured chat model",
)
@pytest.mark.asyncio
async def test_live_model_rag_and_diagnosis(api_client) -> None:
    client, _, sessions, settings = api_client
    local_settings = get_settings()
    for name in (
        "embedding_model",
        "embedding_native_dimensions",
        "embedding_api_key",
        "embedding_api_base_url",
        "chat_api_key",
        "chat_api_base_url",
        "chat_disable_thinking",
        "chat_structured_output_method",
        "answer_model",
    ):
        setattr(settings, name, getattr(local_settings, name))
    assert settings.embedding_model == "nomic-embed-text"
    assert settings.embedding_native_dimensions == 768
    assert settings.embedding_api_base_url is not None
    assert settings.chat_api_base_url is not None
    assert settings.effective_embedding_api_key is not None

    created = await client.post(
        "/api/v1/knowledge-bases", json={"name": "Local model smoke"}
    )
    assert created.status_code == 201, created.text
    knowledge_base_id = created.json()["id"]
    policy = Path(__file__).resolve().parents[2] / "examples" / "refund_policy.md"
    uploaded = await client.post(
        f"/api/v1/knowledge-bases/{knowledge_base_id}/documents",
        files={"file": ("refund_policy.md", policy.read_bytes(), "text/markdown")},
    )
    assert uploaded.status_code == 201, uploaded.text

    embeddings = create_embeddings(
        model=settings.embedding_model,
        api_key=settings.effective_embedding_api_key.get_secret_value(),
        base_url=str(settings.embedding_api_base_url),
        timeout_seconds=settings.index_embedding_timeout_seconds,
        native_dimensions=settings.embedding_native_dimensions,
    )
    encoding = tiktoken.get_encoding(TOKENIZER_NAME)
    assert await process_one_index_job(
        sessions, settings, embeddings, lambda value: len(encoding.encode(value))
    )
    jobs = await client.get(f"/api/v1/documents/{uploaded.json()['id']}/index-jobs")
    assert jobs.status_code == 200, jobs.text
    assert jobs.json()[0]["status"] == "SUCCEEDED", jobs.text

    search = await client.post(
        f"/api/v1/knowledge-bases/{knowledge_base_id}/search",
        json={"query": "退款申请需要谁审核？"},
    )
    assert search.status_code == 200, search.text
    assert any("运营人员" in hit["content"] for hit in search.json()["hits"])

    answer = await client.post(
        f"/api/v1/knowledge-bases/{knowledge_base_id}/ask",
        json={"query": "退款申请需要谁审核？"},
    )
    assert answer.status_code == 200, answer.text
    assert answer.json()["grounded"] is True, answer.text
    assert answer.json()["citations"], answer.text

    tenant_id = uuid.uuid5(uuid.NAMESPACE_URL, "enterprise-agent-platform:test-user")
    async with sessions() as db:
        await seed_demo_orders(db, tenant_id)
    diagnosis = await client.post(
        f"/api/v1/knowledge-bases/{knowledge_base_id}/diagnose",
        json={
            "question": "DEMO-WINDOW 为什么退款失败？请检索退款规则。",
            "order_id": "DEMO-WINDOW",
        },
    )
    assert diagnosis.status_code == 200, diagnosis.text
    assert diagnosis.json()["status"] == "ANSWERED", diagnosis.text
    assert diagnosis.json()["citations"], diagnosis.text
