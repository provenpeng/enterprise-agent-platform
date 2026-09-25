"""Find published documents whose vectors do not match the current space."""

import uuid
from dataclasses import dataclass

from sqlalchemy import exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chunk import Chunk
from app.models.document import Document
from app.models.index_job import IndexJob
from app.models.knowledge_base import KnowledgeBase


@dataclass(frozen=True)
class ReindexCandidate:
    document_id: uuid.UUID
    knowledge_base_id: uuid.UUID
    active_index_version: int
    recorded_space_id: str | None


async def find_embedding_reindex_candidates(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    embedding_space_id: str,
    after_document_id: uuid.UUID | None = None,
    batch_size: int = 100,
) -> list[ReindexCandidate]:
    """Scan one tenant in stable batches, including unverifiable legacy indexes."""
    if batch_size < 1:
        raise ValueError("batch_size must be positive")

    mismatched_chunk = exists(
        select(Chunk.id).where(
            Chunk.document_id == Document.id,
            Chunk.index_version == Document.active_index_version,
            Chunk.metadata_["embedding_space_id"].astext.is_distinct_from(
                embedding_space_id
            ),
        )
    )
    query = (
        select(
            Document.id,
            Document.knowledge_base_id,
            Document.active_index_version,
            IndexJob.embedding_space_id,
        )
        .join(KnowledgeBase, KnowledgeBase.id == Document.knowledge_base_id)
        .outerjoin(
            IndexJob,
            (IndexJob.document_id == Document.id)
            & (IndexJob.index_version == Document.active_index_version),
        )
        .where(
            KnowledgeBase.tenant_id == tenant_id,
            Document.active_index_version.is_not(None),
            or_(
                IndexJob.embedding_space_id.is_distinct_from(embedding_space_id),
                mismatched_chunk,
            ),
        )
        .order_by(Document.id)
        .limit(batch_size)
    )
    if after_document_id is not None:
        query = query.where(Document.id > after_document_id)
    rows = (await db.execute(query)).all()
    return [ReindexCandidate(*row) for row in rows]
