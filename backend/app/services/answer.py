"""Grounded answer orchestration and server-side citation validation."""

import asyncio
import logging
import uuid

from langchain_core.embeddings import Embeddings
from sqlalchemy.ext.asyncio import AsyncSession

from app.rag.answer_generator import AnswerGenerator
from app.schemas.answer import AnswerCitation, AskResponse
from app.services.errors import UpstreamUnavailable
from app.services.retrieval import search_knowledge_base

logger = logging.getLogger(__name__)
NO_ANSWER = "根据当前知识库资料，无法确定答案。"


async def answer_question(
    db: AsyncSession,
    embeddings: Embeddings,
    generator: AnswerGenerator,
    *,
    tenant_id: uuid.UUID,
    knowledge_base_id: uuid.UUID,
    embedding_model: str,
    question: str,
    top_k: int,
    min_score: float,
    embedding_timeout_seconds: float,
    generation_timeout_seconds: float,
) -> AskResponse:
    hits = await search_knowledge_base(
        db,
        embeddings,
        tenant_id=tenant_id,
        knowledge_base_id=knowledge_base_id,
        embedding_model=embedding_model,
        query=question,
        top_k=top_k,
        min_score=min_score,
        timeout_seconds=embedding_timeout_seconds,
    )
    # Search results are DTOs; no database transaction is needed while the
    # answer model runs, and the source IDs were already tenant scoped.
    await db.rollback()
    if not hits:
        return AskResponse(
            knowledge_base_id=knowledge_base_id,
            answer=NO_ANSWER,
            grounded=False,
            citations=[],
        )

    try:
        async with asyncio.timeout(generation_timeout_seconds):
            draft = await generator.generate(question, hits)
    except Exception as exc:
        logger.warning(
            "Answer generation failed for knowledge base %s",
            knowledge_base_id,
            exc_info=True,
        )
        raise UpstreamUnavailable("Answer generation is unavailable") from exc

    authorized = {str(hit.chunk_id): hit for hit in hits}
    cited_ids = list(dict.fromkeys(draft.cited_chunk_ids))
    if (
        not draft.answer.strip()
        or not cited_ids
        or any(chunk_id not in authorized for chunk_id in cited_ids)
    ):
        logger.info(
            "Answer abstained or contained invalid citations for %s", knowledge_base_id
        )
        return AskResponse(
            knowledge_base_id=knowledge_base_id,
            answer=NO_ANSWER,
            grounded=False,
            citations=[],
        )

    citations = [
        AnswerCitation(number=index, source=authorized[chunk_id])
        for index, chunk_id in enumerate(cited_ids, start=1)
    ]
    markers = " ".join(f"[{citation.number}]" for citation in citations)
    return AskResponse(
        knowledge_base_id=knowledge_base_id,
        answer=f"{draft.answer.strip()}\n\n来源：{markers}",
        grounded=True,
        citations=citations,
    )
