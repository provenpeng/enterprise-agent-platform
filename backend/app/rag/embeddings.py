"""Vector contract shared by indexing and retrieval."""

import math


EMBEDDING_DIMENSIONS = 1536


def validate_embedding(vector: list[float]) -> None:
    if (
        len(vector) != EMBEDDING_DIMENSIONS
        or not all(
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(value)
            for value in vector
        )
        or not any(value != 0 for value in vector)
    ):
        raise ValueError("Embedding provider returned an invalid vector")
