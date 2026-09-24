"""API composition root for the answer model."""

from functools import lru_cache
from typing import Annotated

from fastapi import Depends, HTTPException

from app.api.auth import authorized_knowledge_base
from app.core.config import Settings, get_settings
from app.models.knowledge_base import KnowledgeBase
from app.rag.answer_generator import AnswerGenerator, LangChainAnswerGenerator


@lru_cache(maxsize=2)
def _cached_generator(
    model: str, api_key: str, timeout_seconds: float
) -> AnswerGenerator:
    return LangChainAnswerGenerator(
        model=model, api_key=api_key, timeout_seconds=timeout_seconds
    )


def get_answer_generator(
    _knowledge_base: Annotated[KnowledgeBase, Depends(authorized_knowledge_base)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AnswerGenerator:
    key = settings.openai_api_key.get_secret_value() if settings.openai_api_key else ""
    if not key:
        raise HTTPException(status_code=503, detail="Answer model is not configured")
    return _cached_generator(
        settings.answer_model, key, settings.answer_generation_timeout_seconds
    )
