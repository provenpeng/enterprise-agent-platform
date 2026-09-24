"""PostgreSQL lease, retry and atomic index publication operations."""

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.models.chunk import Chunk
from app.models.document import Document, DocumentStatus
from app.models.index_job import IndexJob, IndexJobStatus
from app.rag.types import ChunkCandidate
from app.services.errors import PermanentIndexError


class LeaseLost(Exception):
    """Another worker owns this job attempt."""


@dataclass(frozen=True)
class ClaimedJob:
    job_id: uuid.UUID
    document_id: uuid.UUID
    index_version: int
    attempt: int
    processing_backend: str
    processing_version: str
    embedding_model: str
    target_tokens: int
    max_tokens: int
    max_chunks: int
    embed_batch_size: int
    tokenizer_name: str
    file_type: str
    storage_uri: str
    checksum: str


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def claim_index_job(
    sessions: async_sessionmaker[AsyncSession], settings: Settings
) -> ClaimedJob | None:
    while True:
        now = _utcnow()
        async with sessions() as db:
            async with db.begin():
                job = await db.scalar(
                    select(IndexJob)
                    .where(
                        or_(
                            and_(
                                IndexJob.status == IndexJobStatus.PENDING,
                                IndexJob.next_attempt_at <= now,
                            ),
                            and_(
                                IndexJob.status == IndexJobStatus.RUNNING,
                                IndexJob.lease_expires_at <= now,
                            ),
                        )
                    )
                    .order_by(IndexJob.created_at, IndexJob.id)
                    .with_for_update(skip_locked=True)
                    .limit(1)
                )
                if job is None:
                    return None

                document = await db.get(Document, job.document_id, with_for_update=True)
                if document is None:
                    # The foreign key cascades deletes; this is a defensive guard.
                    job.status = IndexJobStatus.FAILED
                    job.last_error = "Document no longer exists"
                    continue
                if job.attempts >= settings.index_max_attempts:
                    job.status = IndexJobStatus.FAILED
                    job.lease_expires_at = None
                    job.last_error = "Index job exhausted its retry budget"
                    document.status = DocumentStatus.FAILED
                    continue

                job.status = IndexJobStatus.RUNNING
                job.attempts += 1
                job.lease_expires_at = now + timedelta(
                    seconds=settings.index_lease_seconds
                )
                job.last_error = None
                document.status = DocumentStatus.PARSING
                return ClaimedJob(
                    job_id=job.id,
                    document_id=document.id,
                    index_version=job.index_version,
                    attempt=job.attempts,
                    processing_backend=job.processing_backend,
                    processing_version=job.processing_version,
                    embedding_model=job.embedding_model,
                    target_tokens=job.target_tokens,
                    max_tokens=job.max_tokens,
                    max_chunks=job.max_chunks,
                    embed_batch_size=job.embed_batch_size,
                    tokenizer_name=job.tokenizer_name,
                    file_type=document.file_type,
                    storage_uri=document.storage_uri,
                    checksum=document.checksum,
                )


async def _renew_and_set_phase(
    sessions: async_sessionmaker[AsyncSession],
    claim: ClaimedJob,
    settings: Settings,
    phase: DocumentStatus,
) -> None:
    async with sessions() as db:
        async with db.begin():
            job = await db.get(IndexJob, claim.job_id, with_for_update=True)
            if (
                job is None
                or job.status != IndexJobStatus.RUNNING
                or job.attempts != claim.attempt
                or job.lease_expires_at is None
                or job.lease_expires_at <= _utcnow()
            ):
                raise LeaseLost
            job.lease_expires_at = _utcnow() + timedelta(
                seconds=settings.index_lease_seconds
            )
            document = await db.get(Document, claim.document_id, with_for_update=True)
            if document is None:
                raise LeaseLost
            document.status = phase


async def _publish_index(
    sessions: async_sessionmaker[AsyncSession],
    claim: ClaimedJob,
    chunks: list[ChunkCandidate],
    vectors: list[list[float]],
) -> None:
    async with sessions() as db:
        async with db.begin():
            job = await db.get(IndexJob, claim.job_id, with_for_update=True)
            if (
                job is None
                or job.status != IndexJobStatus.RUNNING
                or job.attempts != claim.attempt
                or job.lease_expires_at is None
                or job.lease_expires_at <= _utcnow()
            ):
                raise LeaseLost
            document = await db.get(Document, claim.document_id, with_for_update=True)
            if document is None:
                raise LeaseLost
            await db.execute(
                delete(Chunk).where(
                    Chunk.document_id == claim.document_id,
                    Chunk.index_version == claim.index_version,
                )
            )
            db.add_all(
                Chunk(
                    document_id=claim.document_id,
                    index_version=claim.index_version,
                    chunk_index=chunk.chunk_index,
                    content=chunk.content,
                    token_count=chunk.token_count,
                    page_number=chunk.page_number,
                    section_title=chunk.section_path[-1]
                    if chunk.section_path
                    else None,
                    metadata_={
                        "section_path": list(chunk.section_path),
                        "block_start": chunk.block_start,
                        "block_end": chunk.block_end,
                        "processing_backend": claim.processing_backend,
                        "embedding_model": claim.embedding_model,
                    },
                    embedding=vector,
                )
                for chunk, vector in zip(chunks, vectors, strict=True)
            )
            # Retain the previous published version for rollback and bound storage growth.
            retained_versions = [claim.index_version]
            if document.active_index_version is not None:
                retained_versions.append(document.active_index_version)
            await db.execute(
                delete(Chunk).where(
                    Chunk.document_id == claim.document_id,
                    Chunk.index_version.notin_(retained_versions),
                )
            )
            document.active_index_version = claim.index_version
            document.status = DocumentStatus.READY
            job.status = IndexJobStatus.SUCCEEDED
            job.lease_expires_at = None
            job.last_error = None


async def _record_failure(
    sessions: async_sessionmaker[AsyncSession],
    claim: ClaimedJob,
    settings: Settings,
    exc: Exception,
) -> None:
    permanent = isinstance(exc, PermanentIndexError)
    async with sessions() as db:
        async with db.begin():
            job = await db.get(IndexJob, claim.job_id, with_for_update=True)
            if (
                job is None
                or job.status != IndexJobStatus.RUNNING
                or job.attempts != claim.attempt
            ):
                return
            document = await db.get(Document, claim.document_id, with_for_update=True)
            job.lease_expires_at = None
            if permanent or job.attempts >= settings.index_max_attempts:
                job.status = IndexJobStatus.FAILED
                if permanent:
                    job.last_error = "Document or index configuration is invalid"
                else:
                    job.last_error = "Indexing failed after retries"
                if document is not None:
                    document.status = DocumentStatus.FAILED
            else:
                job.status = IndexJobStatus.PENDING
                job.next_attempt_at = _utcnow() + timedelta(
                    seconds=min(300, 2**job.attempts)
                )
                job.last_error = "Transient indexing error; retry scheduled"
