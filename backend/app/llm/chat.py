"""Shared configuration and construction for OpenAI-compatible chat clients."""

from dataclasses import dataclass, field

from langchain_openai import ChatOpenAI

from app.llm.structured_output import StructuredOutputMethod


@dataclass(frozen=True)
class ChatModelConfig:
    model: str
    api_key: str = field(repr=False)
    timeout_seconds: float
    base_url: str | None = None
    disable_thinking: bool = False
    structured_output_method: StructuredOutputMethod = "json_schema"


def create_chat_model(config: ChatModelConfig) -> ChatOpenAI:
    return ChatOpenAI(
        model=config.model,
        api_key=config.api_key,
        base_url=config.base_url,
        timeout=config.timeout_seconds,
        max_retries=0,
        temperature=0,
        max_tokens=512,
        extra_body={"thinking": {"type": "disabled"}}
        if config.disable_thinking
        else None,
    )
