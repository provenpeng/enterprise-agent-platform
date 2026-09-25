"""API composition root for LangChain diagnostic planning and explanation."""

from functools import lru_cache
from typing import Annotated

from fastapi import Depends

from app.agent.model import DiagnosticModel, LangChainDiagnosticModel
from app.api.auth import authorized_knowledge_base
from app.api.chat_config import require_chat_config
from app.core.config import Settings, get_settings
from app.llm.chat import ChatModelConfig
from app.models.knowledge_base import KnowledgeBase


@lru_cache(maxsize=2)
def _cached_diagnostic_model(config: ChatModelConfig) -> DiagnosticModel:
    return LangChainDiagnosticModel(config)


def get_diagnostic_model(
    _knowledge_base: Annotated[KnowledgeBase, Depends(authorized_knowledge_base)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> DiagnosticModel:
    return _cached_diagnostic_model(require_chat_config(settings, purpose="Diagnostic"))
