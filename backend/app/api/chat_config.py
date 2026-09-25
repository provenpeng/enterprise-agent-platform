"""Resolve the shared chat gateway settings at the HTTP composition boundary."""

from fastapi import HTTPException

from app.core.config import Settings
from app.llm.chat import ChatModelConfig


def require_chat_config(settings: Settings, *, purpose: str) -> ChatModelConfig:
    secret = settings.effective_chat_api_key
    key = secret.get_secret_value() if secret else ""
    if not key:
        raise HTTPException(
            status_code=503, detail=f"{purpose} model is not configured"
        )
    return ChatModelConfig(
        model=settings.answer_model,
        api_key=key,
        timeout_seconds=settings.answer_generation_timeout_seconds,
        base_url=str(settings.chat_api_base_url)
        if settings.chat_api_base_url
        else None,
        disable_thinking=settings.chat_disable_thinking,
        structured_output_method=settings.chat_structured_output_method,
    )
