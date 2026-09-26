"""Chat gateway settings stay separate from the embedding provider."""

from pydantic import SecretStr

from app.agent import model as diagnostic_module
from app.api import answer_provider, diagnostic_provider
from app.core.config import Settings
from app.llm import chat as chat_module
from app.llm.chat import ChatModelConfig
from app.llm.structured_output import json_mode_instruction, structured_chain
from app.rag import answer_generator as answer_module


def test_chat_settings_fall_back_to_openai_and_normalize_compose_defaults() -> None:
    settings = Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://example:example@localhost/example",
        openai_api_key=SecretStr("embedding-key"),
        chat_api_key=SecretStr(""),
        chat_api_base_url="",
    )
    assert settings.effective_chat_api_key.get_secret_value() == "embedding-key"
    assert settings.chat_api_base_url is None


def test_gateway_config_reaches_both_chat_adapters(monkeypatch) -> None:
    calls = []
    structured_calls = []
    streaming_calls = []

    class FakeChat:
        def __init__(self, **kwargs):
            calls.append(kwargs)

        def with_structured_output(self, *args, **kwargs):
            structured_calls.append(kwargs)
            return object()

        def bind(self, **kwargs):
            streaming_calls.append(kwargs)
            return object()

    monkeypatch.setattr(chat_module, "ChatOpenAI", FakeChat)
    config = ChatModelConfig(
        model="free-model",
        api_key="gateway-key",
        timeout_seconds=30,
        base_url="https://aihubmix.com/v1",
        disable_thinking=True,
        structured_output_method="json_mode",
    )
    for adapter in (
        answer_module.LangChainAnswerGenerator,
        diagnostic_module.LangChainDiagnosticModel,
    ):
        adapter(config)
    assert len(calls) == 2
    assert all(call["api_key"] == "gateway-key" for call in calls)
    assert all(call["base_url"] == "https://aihubmix.com/v1" for call in calls)
    assert all(
        call["extra_body"] == {"thinking": {"type": "disabled"}} for call in calls
    )
    assert len(structured_calls) == 3
    assert all(call["method"] == "json_mode" for call in structured_calls)
    assert all("strict" not in call for call in structured_calls)
    assert streaming_calls == [{"response_format": {"type": "json_object"}}]
    assert "gateway-key" not in repr(config)


def test_gateway_credentials_are_used_by_both_api_providers(monkeypatch) -> None:
    settings = Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://example:example@localhost/example",
        openai_api_key=SecretStr("embedding-key"),
        chat_api_key=SecretStr("gateway-key"),
        chat_api_base_url="https://aihubmix.com/v1",
        chat_disable_thinking=True,
        answer_model="free-model",
    )
    calls = []
    monkeypatch.setattr(
        answer_provider,
        "_cached_generator",
        lambda *args: calls.append(args) or object(),
    )
    monkeypatch.setattr(
        diagnostic_provider,
        "_cached_diagnostic_model",
        lambda *args: calls.append(args) or object(),
    )
    answer_provider.get_answer_generator(object(), settings)
    diagnostic_provider.get_diagnostic_model(object(), settings)
    assert len(calls) == 2
    assert calls[0] == calls[1]
    config = calls[0][0]
    assert config == ChatModelConfig(
        model="free-model",
        api_key="gateway-key",
        timeout_seconds=30,
        base_url="https://aihubmix.com/v1",
        disable_thinking=True,
    )


def test_json_mode_omits_unsupported_strict_schema_parameter() -> None:
    calls = []

    class FakeChat:
        def with_structured_output(self, *args, **kwargs):
            calls.append((args, kwargs))
            return object()

    chat = FakeChat()
    structured_chain(chat, answer_module.AnswerDraft, method="json_mode")
    assert calls[0][1] == {"method": "json_mode", "include_raw": False}
    assert "cited_chunk_ids" in json_mode_instruction(
        answer_module.AnswerDraft, "json_mode"
    )
    structured_chain(chat, answer_module.AnswerDraft, method="json_schema")
    assert calls[1][1]["strict"] is True
