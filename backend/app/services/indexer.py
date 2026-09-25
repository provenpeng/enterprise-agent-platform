"""Execute a claimed document index job with injectable embedding provider."""

import asyncio
import hashlib
import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

from langchain_core.embeddings import Embeddings
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.models.document import DocumentStatus
from app.rag.embeddings import validate_embedding
from app.rag.processing import PROCESSING_VERSION, create_document_processor
from app.rag.types import ChunkCandidate
from app.services.errors import PermanentIndexError
from app.services.index_jobs import TOKENIZER_NAME
from app.services.index_store import (
    ClaimedJob,
    LeaseLost,
    _publish_index,
    _record_failure,
    _renew_and_set_phase,
    claim_index_job,
)

logger = logging.getLogger(__name__)
T = TypeVar("T")


async def _with_lease_heartbeat(
    operation: Awaitable[T],
    sessions: async_sessionmaker[AsyncSession],
    claim: ClaimedJob,
    settings: Settings,
    phase: DocumentStatus,
) -> T:
    task = asyncio.ensure_future(operation)
    try:
        while True:
            done, _ = await asyncio.wait(
                {task}, timeout=max(0.1, settings.index_lease_seconds / 3)
            )
            if done:
                return await task
            await _renew_and_set_phase(sessions, claim, settings, phase)
    finally:
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


def _read_source(settings: Settings, claim: ClaimedJob) -> bytes:
    root = settings.upload_dir.resolve()
    try:
        source = (root / claim.storage_uri).resolve(strict=True)
    except FileNotFoundError as exc:
        raise PermanentIndexError("Original document is missing") from exc
    try:
        source.relative_to(root)
    except ValueError as exc:
        raise PermanentIndexError(
            "Document storage key escapes upload directory"
        ) from exc
    if source.stat().st_size > settings.max_upload_size_bytes:
        raise PermanentIndexError("Original document exceeds upload size limit")
    data = source.read_bytes()
    if hashlib.sha256(data).hexdigest() != claim.checksum:
        raise PermanentIndexError("Original document checksum does not match")
    return data


def _validate_embeddings(vectors: list[list[float]], expected_count: int) -> None:
    if len(vectors) != expected_count:
        raise ValueError("Embedding provider returned the wrong number of vectors")
    for vector in vectors:
        validate_embedding(vector)


def _check_job_compatibility(claim: ClaimedJob, settings: Settings) -> None:
    if (
        claim.embedding_model != settings.embedding_model
        or claim.tokenizer_name != TOKENIZER_NAME
        or claim.processing_version != PROCESSING_VERSION
    ):
        raise PermanentIndexError(
            "Index job model, tokenizer, or processor version is unsupported"
        )


async def _parse_and_chunk(
    sessions: async_sessionmaker[AsyncSession],
    settings: Settings,
    claim: ClaimedJob,
    source: bytes,
    token_counter: Callable[[str], int],
) -> list[ChunkCandidate]:
    processor = create_document_processor(
        backend=claim.processing_backend,
        file_type=claim.file_type,
        target_tokens=claim.target_tokens,
        max_tokens=claim.max_tokens,
        token_counter=token_counter,
    )
    try:
        parser_input = (
            source if claim.file_type == "application/pdf" else source.decode("utf-8")
        )
        parsed = await _with_lease_heartbeat(
            asyncio.to_thread(processor.parse, parser_input),
            sessions,
            claim,
            settings,
            DocumentStatus.PARSING,
        )
    except (ValueError, UnicodeError) as exc:
        raise PermanentIndexError("Document cannot be parsed") from exc

    await _renew_and_set_phase(sessions, claim, settings, DocumentStatus.CHUNKING)
    try:
        chunks = await _with_lease_heartbeat(
            asyncio.to_thread(processor.chunker.chunk, parsed),
            sessions,
            claim,
            settings,
            DocumentStatus.CHUNKING,
        )
    except ValueError as exc:
        raise PermanentIndexError("Document cannot be chunked") from exc
    if not chunks or len(chunks) > claim.max_chunks:
        raise PermanentIndexError(
            "Document has no chunks or exceeds the saved chunk limit"
        )
    return chunks


async def _embed_chunks(
    sessions: async_sessionmaker[AsyncSession],
    settings: Settings,
    claim: ClaimedJob,
    chunks: list[ChunkCandidate],
    embeddings: Embeddings,
) -> list[list[float]]:
    vectors: list[list[float]] = []
    for start in range(0, len(chunks), claim.embed_batch_size):
        await _renew_and_set_phase(sessions, claim, settings, DocumentStatus.EMBEDDING)
        batch = chunks[start : start + claim.embed_batch_size]
        async with asyncio.timeout(settings.index_embedding_timeout_seconds):
            vectors.extend(
                await embeddings.aembed_documents([chunk.content for chunk in batch])
            )
    _validate_embeddings(vectors, len(chunks))
    return vectors


async def process_one_index_job(
    sessions: async_sessionmaker[AsyncSession],
    settings: Settings,
    embeddings: Embeddings,
    token_counter: Callable[[str], int],
) -> bool:
    claim = await claim_index_job(sessions, settings)
    if claim is None:
        return False

    try:
        _check_job_compatibility(claim, settings)
        source = await asyncio.to_thread(_read_source, settings, claim)
        chunks = await _parse_and_chunk(
            sessions, settings, claim, source, token_counter
        )
        vectors = await _embed_chunks(sessions, settings, claim, chunks, embeddings)
        await _publish_index(sessions, claim, chunks, vectors)
        logger.info(
            "Indexed document %s version %s", claim.document_id, claim.index_version
        )
    except LeaseLost:
        logger.warning(
            "Index job lease lost: %s attempt %s", claim.job_id, claim.attempt
        )
    except Exception as exc:
        logger.exception("Index job failed: %s attempt %s", claim.job_id, claim.attempt)
        await _record_failure(sessions, claim, settings, exc)
    return True
