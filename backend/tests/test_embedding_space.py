"""Vector-space identity changes whenever comparison semantics can change."""

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
