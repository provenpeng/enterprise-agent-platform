"""Transactional document reindex requests."""

import uuid

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models.document import Document, DocumentStatus
from app.models.index_job import IndexJob, IndexJobStatus


async def enqueue_reindex(
    db: AsyncSession, document_id: uuid.UUID, settings: Settings
) -> IndexJob:
    document = await db.scalar(
        select(Document).where(Document.id == document_id).with_for_update()
    )
    if document is None:
        await db.rollback()
        raise HTTPException(status_code=404, detail="Document not found")

    active_job = await db.scalar(
        select(IndexJob.id).where(
            IndexJob.document_id == document_id,
            IndexJob.status.in_([IndexJobStatus.PENDING, IndexJobStatus.RUNNING]),
        )
    )
    if active_job is not None:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Document already has an active index job")

    latest_version = await db.scalar(
        select(func.max(IndexJob.index_version)).where(IndexJob.document_id == document_id)
    )
    job = IndexJob(
        document_id=document_id,
        index_version=(latest_version or 0) + 1,
        processing_backend=settings.document_processing_backend,
        embedding_model=settings.embedding_model,
    )
    document.status = DocumentStatus.UPLOADED
    db.add(job)
    await db.commit()
    return job
