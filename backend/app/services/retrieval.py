"""Exact tenant-scoped vector retrieval over published document versions."""

import asyncio
import logging
import uuid

from langchain_core.embeddings import Embeddings
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chunk import Chunk
from app.models.document import Document
from app.models.knowledge_base import KnowledgeBase
from app.rag.embeddings import validate_embedding
from app.schemas.retrieval import SearchHit
from app.services.errors import UpstreamUnavailable


logger = logging.getLogger(__name__)


async def search_knowledge_base(
    db: AsyncSession,
    embeddings: Embeddings,
    *,
    tenant_id: uuid.UUID,
    knowledge_base_id: uuid.UUID,
    query: str,
    top_k: int,
    min_score: float,
    timeout_seconds: float,
) -> list[SearchHit]:
    try:
        async with asyncio.timeout(timeout_seconds):
            vector = await embeddings.aembed_query(query)
        validate_embedding(vector)
    except Exception as exc:
        logger.warning(
            "Query embedding failed for knowledge base %s",
            knowledge_base_id,
            exc_info=True,
        )
        raise UpstreamUnavailable("Query embedding is unavailable") from exc

    # Materialization filters by tenant, knowledge base and active version before
    # computing distance. This avoids post-filtered ANN underfill and guarantees
    # exact top-k ordering within the authorized corpus.
    candidates = (
        select(
            Chunk.id.label("chunk_id"),
            Chunk.document_id,
            Document.filename.label("document_name"),
            Chunk.index_version,
            Chunk.chunk_index,
            Chunk.content,
            Chunk.page_number,
            Chunk.section_title,
            Chunk.metadata_.label("metadata"),
            Chunk.embedding,
        )
        .join(Document, Document.id == Chunk.document_id)
        .join(KnowledgeBase, KnowledgeBase.id == Document.knowledge_base_id)
        .where(
            KnowledgeBase.id == knowledge_base_id,
            KnowledgeBase.tenant_id == tenant_id,
            Document.active_index_version == Chunk.index_version,
            Chunk.embedding.is_not(None),
        )
        .cte("authorized_chunks")
        .prefix_with("MATERIALIZED", dialect="postgresql")
    )
    distance = candidates.c.embedding.cosine_distance(vector)
    rows = await db.execute(
        select(candidates, distance.label("distance"))
        .where(distance <= 1.0 - min_score)
        .order_by(distance, candidates.c.chunk_id)
        .limit(top_k)
    )
    hits = [
        SearchHit(
            chunk_id=row.chunk_id,
            document_id=row.document_id,
            document_name=row.document_name,
            index_version=row.index_version,
            chunk_index=row.chunk_index,
            content=row.content,
            score=max(0.0, min(1.0, 1.0 - row.distance)),
            page_number=row.page_number,
            section_title=row.section_title,
            section_path=row.metadata.get("section_path", []),
        )
        for row in rows
    ]
    logger.info(
        "Retrieved %s chunks from knowledge base %s", len(hits), knowledge_base_id
    )
    return hits
