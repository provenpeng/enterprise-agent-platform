"""Transactional document reindex requests."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models.document import Document, DocumentStatus
from app.models.index_job import IndexJob, IndexJobStatus
from app.rag.processing import PROCESSING_VERSION
from app.services.errors import Conflict, NotFound


TOKENIZER_NAME = "cl100k_base"


def new_index_job(
    document_id: uuid.UUID, index_version: int, settings: Settings
) -> IndexJob:
    return IndexJob(
        document_id=document_id,
        index_version=index_version,
        processing_backend=settings.document_processing_backend,
        processing_version=PROCESSING_VERSION,
        embedding_model=settings.embedding_model,
        target_tokens=settings.index_target_tokens,
        max_tokens=settings.index_max_tokens,
        max_chunks=settings.index_max_chunks,
        embed_batch_size=settings.index_embed_batch_size,
        tokenizer_name=TOKENIZER_NAME,
    )


async def enqueue_reindex(
    db: AsyncSession, document_id: uuid.UUID, settings: Settings
) -> IndexJob:
    document = await db.scalar(
        select(Document).where(Document.id == document_id).with_for_update()
    )
    if document is None:
        await db.rollback()
        raise NotFound("Document not found")

    active_job = await db.scalar(
        select(IndexJob.id).where(
            IndexJob.document_id == document_id,
            IndexJob.status.in_([IndexJobStatus.PENDING, IndexJobStatus.RUNNING]),
        )
    )
    if active_job is not None:
        await db.rollback()
        raise Conflict("Document already has an active index job")

    latest_version = await db.scalar(
        select(func.max(IndexJob.index_version)).where(
            IndexJob.document_id == document_id
        )
    )
    job = new_index_job(document_id, (latest_version or 0) + 1, settings)
    document.status = DocumentStatus.UPLOADED
    db.add(job)
    await db.commit()
    return job
