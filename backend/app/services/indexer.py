"""Lease-fenced, versioned document indexing worker operations."""

import asyncio
import hashlib
import logging
import math
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from langchain_core.embeddings import Embeddings
from sqlalchemy import and_, delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.models.chunk import Chunk
from app.models.document import Document, DocumentStatus
from app.models.index_job import IndexJob, IndexJobStatus
from app.rag.processing import create_document_processor
from app.rag.types import ChunkCandidate


logger = logging.getLogger(__name__)
EMBEDDING_DIMENSIONS = 1536


class LeaseLost(Exception):
    """Another worker owns this job attempt."""


@dataclass(frozen=True)
class ClaimedJob:
    job_id: uuid.UUID
    document_id: uuid.UUID
    index_version: int
    attempt: int
    processing_backend: str
    embedding_model: str
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
                job.lease_expires_at = now + timedelta(seconds=settings.index_lease_seconds)
                job.last_error = None
                document.status = DocumentStatus.PARSING
                return ClaimedJob(
                    job_id=job.id,
                    document_id=document.id,
                    index_version=job.index_version,
                    attempt=job.attempts,
                    processing_backend=job.processing_backend,
                    embedding_model=job.embedding_model,
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
            if job is None or job.status != IndexJobStatus.RUNNING or job.attempts != claim.attempt:
                raise LeaseLost
            job.lease_expires_at = _utcnow() + timedelta(seconds=settings.index_lease_seconds)
            document = await db.get(Document, claim.document_id, with_for_update=True)
            if document is None:
                raise LeaseLost
            document.status = phase


def _read_source(settings: Settings, claim: ClaimedJob) -> bytes:
    root = settings.upload_dir.resolve()
    source = (root / claim.storage_uri).resolve(strict=True)
    try:
        source.relative_to(root)
    except ValueError as exc:
        raise ValueError("Document storage key escapes upload directory") from exc
    if source.stat().st_size > settings.max_upload_size_bytes:
        raise ValueError("Original document exceeds upload size limit")
    data = source.read_bytes()
    if hashlib.sha256(data).hexdigest() != claim.checksum:
        raise ValueError("Original document checksum does not match")
    return data


def _validate_embeddings(vectors: list[list[float]], expected_count: int) -> None:
    if len(vectors) != expected_count:
        raise ValueError("Embedding provider returned the wrong number of vectors")
    for vector in vectors:
        if len(vector) != EMBEDDING_DIMENSIONS or not all(
            isinstance(value, (int, float)) and math.isfinite(value) for value in vector
        ):
            raise ValueError("Embedding provider returned an invalid vector")


async def _publish_index(
    sessions: async_sessionmaker[AsyncSession],
    claim: ClaimedJob,
    chunks: list[ChunkCandidate],
    vectors: list[list[float]],
) -> None:
    async with sessions() as db:
        async with db.begin():
            job = await db.get(IndexJob, claim.job_id, with_for_update=True)
            if job is None or job.status != IndexJobStatus.RUNNING or job.attempts != claim.attempt:
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
                    section_title=chunk.section_path[-1] if chunk.section_path else None,
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
    permanent = isinstance(exc, (ValueError, UnicodeError, FileNotFoundError))
    async with sessions() as db:
        async with db.begin():
            job = await db.get(IndexJob, claim.job_id, with_for_update=True)
            if job is None or job.status != IndexJobStatus.RUNNING or job.attempts != claim.attempt:
                return
            document = await db.get(Document, claim.document_id, with_for_update=True)
            job.lease_expires_at = None
            if permanent or job.attempts >= settings.index_max_attempts:
                job.status = IndexJobStatus.FAILED
                if isinstance(exc, FileNotFoundError):
                    job.last_error = "Original document is missing"
                elif isinstance(exc, UnicodeError):
                    job.last_error = "Document text is not valid UTF-8"
                elif permanent:
                    job.last_error = "Document or index configuration is invalid"
                else:
                    job.last_error = "Indexing failed after retries"
                if document is not None:
                    document.status = DocumentStatus.FAILED
            else:
                job.status = IndexJobStatus.PENDING
                job.next_attempt_at = _utcnow() + timedelta(seconds=min(300, 2 ** job.attempts))
                job.last_error = "Transient indexing error; retry scheduled"


async def process_one_index_job(
    sessions: async_sessionmaker[AsyncSession],
    settings: Settings,
    embeddings: Embeddings,
    token_counter: Callable[[str], int],
) -> bool:
    claim = await claim_index_job(sessions, settings)
    if claim is None:
        return False

    try:
        if claim.embedding_model != settings.embedding_model:
            raise ValueError("Index job embedding model does not match worker configuration")
        source = await asyncio.to_thread(_read_source, settings, claim)
        processor = create_document_processor(
            backend=claim.processing_backend,
            file_type=claim.file_type,
            target_tokens=settings.index_target_tokens,
            max_tokens=settings.index_max_tokens,
            token_counter=token_counter,
        )
        parsed = processor.parse(source if claim.file_type == "application/pdf" else source.decode("utf-8"))
        await _renew_and_set_phase(sessions, claim, settings, DocumentStatus.CHUNKING)
        chunks = processor.chunker.chunk(parsed)
        if not chunks or len(chunks) > settings.index_max_chunks:
            raise ValueError("Document has no chunks or exceeds the configured chunk limit")
        await _renew_and_set_phase(sessions, claim, settings, DocumentStatus.EMBEDDING)

        vectors: list[list[float]] = []
        for start in range(0, len(chunks), settings.index_embed_batch_size):
            await _renew_and_set_phase(sessions, claim, settings, DocumentStatus.EMBEDDING)
            batch = chunks[start:start + settings.index_embed_batch_size]
            vectors.extend(await embeddings.aembed_documents([chunk.content for chunk in batch]))
        _validate_embeddings(vectors, len(chunks))
        await _publish_index(sessions, claim, chunks, vectors)
        logger.info("Indexed document %s version %s", claim.document_id, claim.index_version)
    except LeaseLost:
        logger.warning("Index job lease lost: %s attempt %s", claim.job_id, claim.attempt)
    except Exception as exc:
        logger.exception("Index job failed: %s attempt %s", claim.job_id, claim.attempt)
        await _record_failure(sessions, claim, settings, exc)
    return True
