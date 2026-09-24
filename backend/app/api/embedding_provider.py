"""API composition root for a reusable query embedding client."""

from functools import lru_cache
from typing import Annotated

from fastapi import Depends, HTTPException
from langchain_core.embeddings import Embeddings
from langchain_openai import OpenAIEmbeddings

from app.api.auth import authorized_knowledge_base
from app.core.config import Settings, get_settings
from app.models.knowledge_base import KnowledgeBase
from app.rag.embeddings import EMBEDDING_DIMENSIONS


@lru_cache(maxsize=2)
def _cached_embeddings(model: str, api_key: str, timeout_seconds: float) -> Embeddings:
    return OpenAIEmbeddings(
        model=model,
        dimensions=EMBEDDING_DIMENSIONS,
        api_key=api_key,
        request_timeout=timeout_seconds,
        max_retries=0,
    )


def get_query_embeddings(
    _knowledge_base: Annotated[KnowledgeBase, Depends(authorized_knowledge_base)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> Embeddings:
    key = settings.openai_api_key.get_secret_value() if settings.openai_api_key else ""
    if not key:
        raise HTTPException(
            status_code=503, detail="Query embeddings are not configured"
        )
    return _cached_embeddings(
        settings.embedding_model, key, settings.retrieval_embedding_timeout_seconds
    )
