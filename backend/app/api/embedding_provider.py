"""API composition root for a reusable query embedding client."""

from functools import lru_cache
from typing import Annotated

from fastapi import Depends, HTTPException
from langchain_core.embeddings import Embeddings

from app.api.auth import authorized_knowledge_base
from app.core.config import Settings, get_settings
from app.models.knowledge_base import KnowledgeBase
from app.rag.embeddings import create_embeddings


@lru_cache(maxsize=2)
def _cached_embeddings(
    model: str,
    api_key: str,
    base_url: str | None,
    timeout_seconds: float,
    native_dimensions: int,
) -> Embeddings:
    return create_embeddings(
        model=model,
        api_key=api_key,
        base_url=base_url,
        timeout_seconds=timeout_seconds,
        native_dimensions=native_dimensions,
    )


def get_query_embeddings(
    _knowledge_base: Annotated[KnowledgeBase, Depends(authorized_knowledge_base)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> Embeddings:
    secret = settings.effective_embedding_api_key
    key = secret.get_secret_value() if secret else ""
    if not key:
        raise HTTPException(
            status_code=503, detail="Query embeddings are not configured"
        )
    return _cached_embeddings(
        settings.embedding_model,
        key,
        str(settings.embedding_api_base_url)
        if settings.embedding_api_base_url
        else None,
        settings.retrieval_embedding_timeout_seconds,
        settings.embedding_native_dimensions,
    )
