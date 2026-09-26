"""Stable identity for vectors that are safe to compare with each other."""

import hashlib
import json

DEFAULT_EMBEDDING_BASE_URL = "https://api.openai.com/v1"


def embedding_space_id(
    *,
    model: str,
    base_url: str | None,
    native_dimensions: int,
    revision: str,
    provider_id: str | None = None,
) -> str:
    """Hash the model identity, optionally independent of its transport URL."""
    identity = {
        "version": 2 if provider_id else 1,
        "model": model,
        "native_dimensions": native_dimensions,
        "revision": revision,
    }
    if provider_id:
        identity["provider_id"] = provider_id
    else:
        identity["base_url"] = (base_url or DEFAULT_EMBEDDING_BASE_URL).rstrip("/")
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()
