"""Stable identity for vectors that are safe to compare with each other."""

import hashlib
import json

DEFAULT_EMBEDDING_BASE_URL = "https://api.openai.com/v1"


def embedding_space_id(
    *, model: str, base_url: str | None, native_dimensions: int, revision: str
) -> str:
    """Hash non-secret provider settings; bump revision when model weights change."""
    identity = {
        "version": 1,
        "base_url": (base_url or DEFAULT_EMBEDDING_BASE_URL).rstrip("/"),
        "model": model,
        "native_dimensions": native_dimensions,
        "revision": revision,
    }
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()
