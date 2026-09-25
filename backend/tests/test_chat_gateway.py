"""Chat gateway settings stay separate from the embedding provider."""

from pydantic import SecretStr

from app.agent import model as diagnostic_module
from app.api import answer_provider, diagnostic_provider
from app.core.config import Settings
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

    class FakeChat:
        def __init__(self, **kwargs):
            calls.append(kwargs)

        def with_structured_output(self, *args, **kwargs):
            return object()

    monkeypatch.setattr(answer_module, "ChatOpenAI", FakeChat)
    monkeypatch.setattr(diagnostic_module, "ChatOpenAI", FakeChat)
    for adapter in (
        answer_module.LangChainAnswerGenerator,
        diagnostic_module.LangChainDiagnosticModel,
    ):
        adapter(
            model="free-model",
            api_key="gateway-key",
            timeout_seconds=30,
            base_url="https://aihubmix.com/v1",
            disable_thinking=True,
        )
    assert len(calls) == 2
    assert all(call["api_key"] == "gateway-key" for call in calls)
    assert all(call["base_url"] == "https://aihubmix.com/v1" for call in calls)
    assert all(
        call["extra_body"] == {"thinking": {"type": "disabled"}} for call in calls
    )


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
    assert calls == [
        ("free-model", "gateway-key", 30, "https://aihubmix.com/v1", True),
        ("free-model", "gateway-key", 30, "https://aihubmix.com/v1", True),
    ]
