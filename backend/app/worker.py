"""Run the durable document indexing worker with ``python -m app.worker``."""

import asyncio
import logging

import tiktoken
from langchain_openai import OpenAIEmbeddings

from app.core.config import get_settings
from app.db.session import SessionLocal, engine
from app.rag.embeddings import EMBEDDING_DIMENSIONS
from app.services.index_jobs import TOKENIZER_NAME
from app.services.indexer import process_one_index_job

logger = logging.getLogger(__name__)


async def run_worker() -> None:
    settings = get_settings()
    if settings.openai_api_key is None:
        raise RuntimeError("OPENAI_API_KEY is required to run the indexing worker")
    embeddings = OpenAIEmbeddings(
        model=settings.embedding_model,
        dimensions=EMBEDDING_DIMENSIONS,
        api_key=settings.openai_api_key,
        request_timeout=settings.index_embedding_timeout_seconds,
        max_retries=0,
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
