"""Vector-space identity changes whenever comparison semantics can change."""

from app.core.config import Settings
from app.rag.embedding_space import embedding_space_id


def test_embedding_space_identity_normalizes_trailing_slash() -> None:
    options = {
        "model": "same-name",
        "native_dimensions": 768,
        "revision": "weights-v1",
    }
    assert embedding_space_id(base_url="https://provider.example/v1", **options) == (
        embedding_space_id(base_url="https://provider.example/v1/", **options)
    )
    assert embedding_space_id(base_url=None, **options) == embedding_space_id(
        base_url="https://api.openai.com/v1", **options
    )


def test_embedding_space_identity_changes_with_every_semantic_component() -> None:
    options = {
        "model": "same-name",
        "base_url": "https://provider.example/v1",
        "native_dimensions": 768,
        "revision": "weights-v1",
    }
    original = embedding_space_id(**options)
    changes = (
        {"base_url": "https://another-provider.example/v1"},
        {"model": "different-name"},
        {"native_dimensions": 1536},
        {"revision": "weights-v2"},
    )
    for change in changes:
        assert embedding_space_id(**(options | change)) != original


def test_explicit_provider_identity_is_stable_across_transport_urls() -> None:
    options = {
        "model": "nomic-embed-text",
        "native_dimensions": 768,
        "revision": "weights-v1",
        "provider_id": "local-ollama",
    }
    host = embedding_space_id(base_url="http://127.0.0.1:11435/v1", **options)
    container = embedding_space_id(base_url="http://192.168.0.107:11435/v1", **options)
    assert host == container
    assert host != embedding_space_id(
        base_url="http://127.0.0.1:11435/v1",
        **(options | {"provider_id": "another-ollama"}),
    )
    assert host != embedding_space_id(
        base_url="http://127.0.0.1:11435/v1",
        **(options | {"revision": "weights-v2"}),
    )


def test_settings_normalize_empty_provider_and_use_explicit_identity() -> None:
    common = {
        "_env_file": None,
        "database_url": "postgresql+asyncpg://example:example@localhost/example",
        "embedding_model": "nomic-embed-text",
        "embedding_native_dimensions": 768,
        "embedding_provider_id": " local-ollama ",
    }
    host = Settings(
        **(common | {"embedding_api_base_url": "http://127.0.0.1:11435/v1"})
    )
    container = Settings(
        **(common | {"embedding_api_base_url": "http://192.168.0.107:11435/v1"})
    )
    assert host.embedding_provider_id == "local-ollama"
    assert host.embedding_space_id == container.embedding_space_id
    assert (
        Settings(
            _env_file=None,
            database_url=common["database_url"],
            embedding_provider_id="",
        ).embedding_provider_id
        is None
    )
