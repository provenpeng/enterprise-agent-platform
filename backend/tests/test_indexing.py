import uuid
import asyncio
from datetime import datetime, timedelta, timezone
from io import BytesIO

import pytest
from langchain_core.embeddings import Embeddings
from reportlab.pdfgen import canvas
from sqlalchemy import func, select

from app.models.chunk import Chunk
from app.models.document import Document, DocumentStatus
from app.models.index_job import IndexJob, IndexJobStatus
from app.services.indexer import (
    EMBEDDING_DIMENSIONS,
    LeaseLost,
    _publish_index,
    _with_lease_heartbeat,
    claim_index_job,
    process_one_index_job,
)


class FakeEmbeddings(Embeddings):
    def __init__(self, *, fail_once: bool = False) -> None:
        self.fail_once = fail_once
        self.calls = 0

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[1.0] + [0.0] * (EMBEDDING_DIMENSIONS - 1) for _ in texts]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        if self.fail_once:
            self.fail_once = False
            raise TimeoutError("simulated provider outage")
        return self.embed_documents(texts)


class InvalidRequestEmbeddings(FakeEmbeddings):
    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        raise ValueError("provider-specific request failure")


class SlowEmbeddings(FakeEmbeddings):
    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        await asyncio.sleep(0.05)
        return self.embed_documents(texts)


async def upload_text(client, name: str = "Rules") -> str:
    knowledge_base = await client.post("/api/v1/knowledge-bases", json={"name": name})
    assert knowledge_base.status_code == 201
    response = await client.post(
        f"/api/v1/knowledge-bases/{knowledge_base.json()['id']}/documents",
        files={
            "file": (
                "rules.md",
                b"# Refunds\n\nRefunds require approval.",
                "text/markdown",
            )
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


@pytest.mark.asyncio
async def test_upload_enqueues_and_worker_publishes_active_index(api_client) -> None:
    client, _, sessions, settings = api_client
    document_id = await upload_text(client)
    job_response = await client.get(f"/api/v1/documents/{document_id}/index-jobs")
    assert job_response.status_code == 200
    assert [(job["index_version"], job["status"]) for job in job_response.json()] == [
        (1, "PENDING")
    ]
    assert (await client.get(f"/api/v1/documents/{document_id}/chunks")).json() == []

    assert await process_one_index_job(sessions, settings, FakeEmbeddings(), len)
    assert not await process_one_index_job(sessions, settings, FakeEmbeddings(), len)

    document = (await client.get(f"/api/v1/documents/{document_id}")).json()
    assert document["status"] == "READY"
    assert document["active_index_version"] == 1
    chunks = (await client.get(f"/api/v1/documents/{document_id}/chunks")).json()
    assert len(chunks) == 1
    assert chunks[0]["section_path"] == ["Refunds"]
    assert chunks[0]["content"] == "Refunds require approval."
    assert (
        await client.get(f"/api/v1/documents/{document_id}/chunks?limit=0")
    ).status_code == 422
    async with sessions() as db:
        chunk = await db.scalar(
            select(Chunk).where(Chunk.document_id == uuid.UUID(document_id))
        )
        assert chunk is not None
        assert len(chunk.embedding) == EMBEDDING_DIMENSIONS


@pytest.mark.asyncio
async def test_reindex_switches_backend_and_preserves_previous_version(
    api_client,
) -> None:
    client, _, sessions, settings = api_client
    document_id = await upload_text(client)
    await process_one_index_job(sessions, settings, FakeEmbeddings(), len)

    settings.document_processing_backend = "langchain"
    response = await client.post(f"/api/v1/documents/{document_id}/index-jobs")
    assert response.status_code == 201
    assert response.json()["index_version"] == 2
    assert response.json()["processing_backend"] == "langchain"
    assert (
        await client.post(f"/api/v1/documents/{document_id}/index-jobs")
    ).status_code == 409
    before = (await client.get(f"/api/v1/documents/{document_id}/chunks")).json()
    assert all(chunk["index_version"] == 1 for chunk in before)

    await process_one_index_job(sessions, settings, FakeEmbeddings(), len)
    after = (await client.get(f"/api/v1/documents/{document_id}/chunks")).json()
    assert after and all(chunk["index_version"] == 2 for chunk in after)
    async with sessions() as db:
        versions = await db.scalars(
            select(Chunk.index_version).where(
                Chunk.document_id == uuid.UUID(document_id)
            )
        )
        assert set(versions) == {1, 2}
        latest = await db.scalar(
            select(IndexJob).where(
                IndexJob.document_id == uuid.UUID(document_id),
                IndexJob.index_version == 2,
            )
        )
        assert latest is not None and latest.status == IndexJobStatus.SUCCEEDED

    settings.document_processing_backend = "manual"
    third = await client.post(f"/api/v1/documents/{document_id}/index-jobs")
    assert third.status_code == 201 and third.json()["index_version"] == 3
    await process_one_index_job(sessions, settings, FakeEmbeddings(), len)
    async with sessions() as db:
        versions = await db.scalars(
            select(Chunk.index_version).where(
                Chunk.document_id == uuid.UUID(document_id)
            )
        )
        assert set(versions) == {2, 3}


@pytest.mark.asyncio
async def test_transient_embedding_failure_retries_without_changing_active_index(
    api_client,
) -> None:
    client, _, sessions, settings = api_client
    document_id = await upload_text(client)
    await process_one_index_job(sessions, settings, FakeEmbeddings(), len)
    await client.post(f"/api/v1/documents/{document_id}/index-jobs")
    embeddings = FakeEmbeddings(fail_once=True)

    assert await process_one_index_job(sessions, settings, embeddings, len)
    async with sessions() as db:
        job = await db.scalar(
            select(IndexJob).where(
                IndexJob.document_id == uuid.UUID(document_id),
                IndexJob.index_version == 2,
            )
        )
        document = await db.get(Document, uuid.UUID(document_id))
        assert job is not None and job.status == IndexJobStatus.PENDING
        assert job.attempts == 1
        assert document is not None and document.active_index_version == 1
        job.next_attempt_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        await db.commit()

    assert await process_one_index_job(sessions, settings, embeddings, len)
    assert (await client.get(f"/api/v1/documents/{document_id}")).json()[
        "active_index_version"
    ] == 2
    assert embeddings.calls == 2


@pytest.mark.asyncio
async def test_expired_attempt_cannot_publish_after_new_worker_claims(
    api_client,
) -> None:
    client, _, sessions, settings = api_client
    await upload_text(client)
    first = await claim_index_job(sessions, settings)
    assert first is not None
    async with sessions() as db:
        job = await db.get(IndexJob, first.job_id)
        assert job is not None
        job.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        await db.commit()

    second = await claim_index_job(sessions, settings)
    assert second is not None and second.attempt == 2
    with pytest.raises(LeaseLost):
        await _publish_index(sessions, first, [], [])
    async with sessions() as db:
        count = await db.scalar(select(func.count()).select_from(Chunk))
        assert count == 0


@pytest.mark.asyncio
async def test_crashed_job_exhausts_retry_budget(api_client) -> None:
    client, _, sessions, settings = api_client
    settings.index_max_attempts = 2
    document_id = await upload_text(client)

    for attempt in (1, 2):
        claim = await claim_index_job(sessions, settings)
        assert claim is not None and claim.attempt == attempt
        async with sessions() as db:
            job = await db.get(IndexJob, claim.job_id)
            assert job is not None
            job.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            await db.commit()

    assert await claim_index_job(sessions, settings) is None
    async with sessions() as db:
        job = await db.scalar(
            select(IndexJob).where(IndexJob.document_id == uuid.UUID(document_id))
        )
        document = await db.get(Document, uuid.UUID(document_id))
        assert job is not None and job.status == IndexJobStatus.FAILED
        assert document is not None and document.status == DocumentStatus.FAILED


@pytest.mark.asyncio
async def test_invalid_pdf_job_fails_and_can_be_requeued(api_client) -> None:
    client, _, sessions, settings = api_client
    knowledge_base = await client.post(
        "/api/v1/knowledge-bases", json={"name": "PDF failures"}
    )
    response = await client.post(
        f"/api/v1/knowledge-bases/{knowledge_base.json()['id']}/documents",
        files={"file": ("broken.pdf", b"%PDF-invalid", "application/pdf")},
    )
    assert response.status_code == 201
    document_id = response.json()["id"]

    await process_one_index_job(sessions, settings, FakeEmbeddings(), len)
    document = (await client.get(f"/api/v1/documents/{document_id}")).json()
    assert document["status"] == DocumentStatus.FAILED
    assert document["active_index_version"] is None
    jobs = (await client.get(f"/api/v1/documents/{document_id}/index-jobs")).json()
    assert jobs[0]["status"] == "FAILED"
    retried = await client.post(f"/api/v1/documents/{document_id}/index-jobs")
    assert retried.status_code == 201
    assert retried.json()["index_version"] == 2


@pytest.mark.asyncio
async def test_failed_reindex_keeps_previous_chunks_and_hides_storage_path(
    api_client,
) -> None:
    client, _, sessions, settings = api_client
    document_id = await upload_text(client)
    await process_one_index_job(sessions, settings, FakeEmbeddings(), len)
    async with sessions() as db:
        document = await db.get(Document, uuid.UUID(document_id))
        assert document is not None
        source = settings.upload_dir / document.storage_uri
    source.write_bytes(b"tampered content")

    response = await client.post(f"/api/v1/documents/{document_id}/index-jobs")
    assert response.status_code == 201
    await process_one_index_job(sessions, settings, FakeEmbeddings(), len)

    document = (await client.get(f"/api/v1/documents/{document_id}")).json()
    jobs = (await client.get(f"/api/v1/documents/{document_id}/index-jobs")).json()
    chunks = (await client.get(f"/api/v1/documents/{document_id}/chunks")).json()
    assert document["status"] == "FAILED"
    assert document["active_index_version"] == 1
    assert jobs[0]["status"] == "FAILED"
    assert str(settings.upload_dir) not in jobs[0]["last_error"]
    assert chunks and all(chunk["index_version"] == 1 for chunk in chunks)


@pytest.mark.asyncio
async def test_langchain_pdf_index_keeps_page_numbers(api_client) -> None:
    client, _, sessions, settings = api_client
    settings.document_processing_backend = "langchain"
    output = BytesIO()
    pdf = canvas.Canvas(output)
    for text in (
        "Refund requests require approval.",
        "Final sales cannot be refunded.",
    ):
        pdf.drawString(72, 720, text)
        pdf.showPage()
    pdf.save()
    knowledge_base = await client.post(
        "/api/v1/knowledge-bases", json={"name": "PDF indexing"}
    )
    response = await client.post(
        f"/api/v1/knowledge-bases/{knowledge_base.json()['id']}/documents",
        files={"file": ("rules.pdf", output.getvalue(), "application/pdf")},
    )
    assert response.status_code == 201

    await process_one_index_job(sessions, settings, FakeEmbeddings(), len)
    chunks = (
        await client.get(f"/api/v1/documents/{response.json()['id']}/chunks")
    ).json()
    assert [chunk["page_number"] for chunk in chunks] == [1, 2]


@pytest.mark.asyncio
async def test_job_uses_saved_processing_limits_after_settings_change(
    api_client,
) -> None:
    client, _, sessions, settings = api_client
    settings.index_target_tokens = 100
    settings.index_max_tokens = 120
    document_id = await upload_text(client)
    settings.index_target_tokens = 5
    settings.index_max_tokens = 10
    settings.index_max_chunks = 1
    settings.index_embed_batch_size = 1

    assert await process_one_index_job(sessions, settings, FakeEmbeddings(), len)
    chunks = (await client.get(f"/api/v1/documents/{document_id}/chunks")).json()
    jobs = (await client.get(f"/api/v1/documents/{document_id}/index-jobs")).json()
    assert len(chunks) == 1
    assert jobs[0]["target_tokens"] == 100
    assert jobs[0]["max_tokens"] == 120
    assert jobs[0]["max_chunks"] == 1000
    assert jobs[0]["embed_batch_size"] == 32


@pytest.mark.asyncio
@pytest.mark.parametrize("embeddings", [InvalidRequestEmbeddings(), SlowEmbeddings()])
async def test_embedding_errors_remain_retryable(
    api_client, embeddings: Embeddings
) -> None:
    client, _, sessions, settings = api_client
    settings.index_embedding_timeout_seconds = 0.01
    document_id = await upload_text(client)

    assert await process_one_index_job(sessions, settings, embeddings, len)
    jobs = (await client.get(f"/api/v1/documents/{document_id}/index-jobs")).json()
    assert jobs[0]["status"] == "PENDING"
    assert jobs[0]["attempts"] == 1


@pytest.mark.asyncio
async def test_long_processing_renews_lease(api_client) -> None:
    client, _, sessions, settings = api_client
    await upload_text(client)
    settings.index_lease_seconds = 1
    claim = await claim_index_job(sessions, settings)
    assert claim is not None

    await _with_lease_heartbeat(
        asyncio.sleep(1.5), sessions, claim, settings, DocumentStatus.PARSING
    )
    async with sessions() as db:
        job = await db.get(IndexJob, claim.job_id)
        assert job is not None
        assert job.lease_expires_at is not None
        assert job.lease_expires_at > datetime.now(timezone.utc)
