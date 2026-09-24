"""API composition root for LangChain diagnostic planning and explanation."""

from functools import lru_cache
from typing import Annotated

from fastapi import Depends, HTTPException

from app.agent.model import DiagnosticModel, LangChainDiagnosticModel
from app.api.auth import authorized_knowledge_base
from app.core.config import Settings, get_settings
from app.models.knowledge_base import KnowledgeBase


@lru_cache(maxsize=2)
def _cached_diagnostic_model(
    model: str, api_key: str, timeout_seconds: float
) -> DiagnosticModel:
    return LangChainDiagnosticModel(
        model=model, api_key=api_key, timeout_seconds=timeout_seconds
    )


def get_diagnostic_model(
    _knowledge_base: Annotated[KnowledgeBase, Depends(authorized_knowledge_base)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> DiagnosticModel:
    key = settings.openai_api_key.get_secret_value() if settings.openai_api_key else ""
    if not key:
        raise HTTPException(
            status_code=503, detail="Diagnostic model is not configured"
        )
    return _cached_diagnostic_model(
        settings.answer_model, key, settings.answer_generation_timeout_seconds
    )
