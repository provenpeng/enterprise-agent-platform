"""Run the durable document indexing worker with ``python -m app.worker``."""

import asyncio
import logging

import tiktoken

from app.core.config import get_settings
from app.db.session import SessionLocal, engine
from app.rag.embeddings import create_embeddings
from app.services.index_jobs import TOKENIZER_NAME
from app.services.indexer import process_one_index_job

logger = logging.getLogger(__name__)


async def run_worker() -> None:
    settings = get_settings()
    secret = settings.effective_embedding_api_key
    if secret is None or not secret.get_secret_value():
        raise RuntimeError(
            "An embedding API key is required to run the indexing worker"
        )
    embeddings = create_embeddings(
        model=settings.embedding_model,
        api_key=secret.get_secret_value(),
        base_url=str(settings.embedding_api_base_url)
        if settings.embedding_api_base_url
        else None,
        timeout_seconds=settings.index_embedding_timeout_seconds,
        native_dimensions=settings.embedding_native_dimensions,
    )
    encoding = tiktoken.get_encoding(TOKENIZER_NAME)

    def token_counter(value: str) -> int:
        return len(encoding.encode(value))

    try:
        while True:
            try:
                worked = await process_one_index_job(
                    SessionLocal, settings, embeddings, token_counter
                )
            except Exception:
                logger.exception("Index worker cycle failed")
                worked = False
            if not worked:
                await asyncio.sleep(settings.index_poll_interval_seconds)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(run_worker())
    except KeyboardInterrupt:
        pass
