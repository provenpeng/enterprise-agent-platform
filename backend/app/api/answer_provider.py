"""API composition root for the answer model."""

from functools import lru_cache
from typing import Annotated

from fastapi import Depends

from app.api.auth import authorized_knowledge_base
from app.api.chat_config import require_chat_config
from app.core.config import Settings, get_settings
from app.llm.chat import ChatModelConfig
from app.models.knowledge_base import KnowledgeBase
from app.rag.answer_generator import AnswerGenerator, LangChainAnswerGenerator


@lru_cache(maxsize=2)
def _cached_generator(config: ChatModelConfig) -> AnswerGenerator:
    return LangChainAnswerGenerator(config)


def get_answer_generator(
    _knowledge_base: Annotated[KnowledgeBase, Depends(authorized_knowledge_base)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AnswerGenerator:
    return _cached_generator(require_chat_config(settings, purpose="Answer"))
