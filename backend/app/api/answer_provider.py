"""API composition root for the answer model."""

from functools import lru_cache
from typing import Annotated

from fastapi import Depends, HTTPException

from app.api.auth import authorized_knowledge_base
from app.core.config import Settings, get_settings
from app.llm.structured_output import StructuredOutputMethod
from app.models.knowledge_base import KnowledgeBase
from app.rag.answer_generator import AnswerGenerator, LangChainAnswerGenerator


@lru_cache(maxsize=2)
def _cached_generator(
    model: str,
    api_key: str,
    timeout_seconds: float,
    base_url: str | None,
    disable_thinking: bool,
    structured_output_method: StructuredOutputMethod,
) -> AnswerGenerator:
    return LangChainAnswerGenerator(
        model=model,
        api_key=api_key,
        timeout_seconds=timeout_seconds,
        base_url=base_url,
        disable_thinking=disable_thinking,
        structured_output_method=structured_output_method,
    )


def get_answer_generator(
    _knowledge_base: Annotated[KnowledgeBase, Depends(authorized_knowledge_base)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AnswerGenerator:
    secret = settings.effective_chat_api_key
    key = secret.get_secret_value() if secret else ""
    if not key:
        raise HTTPException(status_code=503, detail="Answer model is not configured")
    return _cached_generator(
        settings.answer_model,
        key,
        settings.answer_generation_timeout_seconds,
        str(settings.chat_api_base_url) if settings.chat_api_base_url else None,
        settings.chat_disable_thinking,
        settings.chat_structured_output_method,
    )
