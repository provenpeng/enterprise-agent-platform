"""Compose the selected processing backend from application settings."""

from collections.abc import Callable

from app.core.config import Settings
from app.rag.processing import DocumentProcessor, create_document_processor


def document_processor_from_settings(
    settings: Settings,
    *,
    file_type: str,
    target_tokens: int,
    max_tokens: int,
    token_counter: Callable[[str], int],
) -> DocumentProcessor[str] | DocumentProcessor[bytes]:
    return create_document_processor(
        backend=settings.document_processing_backend,
        file_type=file_type,
        target_tokens=target_tokens,
        max_tokens=max_tokens,
        token_counter=token_counter,
    )
