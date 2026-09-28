"""Measure tenant-scoped exact retrieval in a disposable PostgreSQL database."""

import argparse
import asyncio
import json
import math
import uuid
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

from langchain_core.embeddings import Embeddings
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401 - register all tables for the disposable database
from app.core.config import get_settings
from app.db.base import Base
from app.models.document import Document, DocumentStatus
from app.models.knowledge_base import KnowledgeBase
from app.models.tenant import Tenant
from app.services.retrieval import search_knowledge_base

SPACE_ID = "capacity-benchmark-v1"
VECTOR = [1.0] + [0.0] * 1535
VECTOR_LITERAL = (
    "[" + ",".join("1" if index == 0 else "0" for index in range(1536)) + "]"
)


class FixedEmbeddings(Embeddings):
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [VECTOR for _ in texts]

    def embed_query(self, text: str) -> list[float]:
        return VECTOR

    async def aembed_query(self, text: str) -> list[float]:
        return VECTOR


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return round(ordered[max(0, math.ceil(len(ordered) * fraction) - 1)], 2)


async def execute(sizes: list[int], trials: int, concurrency: int) -> dict:
    settings = get_settings()
    root_url = make_url(settings.database_url)
    database_name = f"eap_capacity_{uuid.uuid4().hex}"
    admin_engine = create_async_engine(
        root_url.set(database="postgres"), isolation_level="AUTOCOMMIT"
    )
    bench_engine = None
    created_database = False
    try:
        async with admin_engine.connect() as connection:
            await connection.execute(text(f'CREATE DATABASE "{database_name}"'))
        created_database = True
        bench_engine = create_async_engine(root_url.set(database=database_name))
        sessions = async_sessionmaker(bench_engine, expire_on_commit=False)
        async with bench_engine.begin() as connection:
            await connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await connection.run_sync(Base.metadata.create_all)

        tenant_id, knowledge_base_id = uuid.uuid4(), uuid.uuid4()
        async with sessions() as db:
            db.add(Tenant(id=tenant_id, name="Capacity benchmark"))
            db.add(
                KnowledgeBase(
                    id=knowledge_base_id,
                    tenant_id=tenant_id,
                    owner_sub="capacity-benchmark",
                    name="Capacity benchmark",
                )
            )
            await db.commit()

        async def add_chunks(count: int) -> None:
            async with sessions() as db:
                for sequence in range(count // 1000 + int(count % 1000 > 0)):
                    size = min(1000, count - sequence * 1000)
                    document_id = uuid.uuid4()
                    db.add(
                        Document(
                            id=document_id,
                            knowledge_base_id=knowledge_base_id,
                            filename=f"capacity-{document_id}.md",
                            file_type="text/markdown",
                            storage_uri=f"capacity/{document_id}/original.md",
                            checksum=document_id.hex,
                            status=DocumentStatus.READY,
                            active_index_version=1,
                        )
                    )
                    await db.flush()
                    await db.execute(
                        text(
                            """
                            INSERT INTO chunks
                              (id, document_id, index_version, chunk_index, content,
                               token_count, metadata, embedding)
                            SELECT gen_random_uuid(), :document_id, 1, value,
                                   'Synthetic refund window policy.', 6,
                                   CAST(:metadata AS jsonb), CAST(:embedding AS vector)
                            FROM generate_series(0, :last_index) AS value
                            """
                        ),
                        {
                            "document_id": document_id,
                            "last_index": size - 1,
                            "metadata": json.dumps({"embedding_space_id": SPACE_ID}),
                            "embedding": VECTOR_LITERAL,
                        },
                    )
                await db.commit()
            async with bench_engine.begin() as connection:
                await connection.execute(text("ANALYZE chunks"))

        embeddings = FixedEmbeddings()

        async def query_once() -> float:
            started = perf_counter()
            async with sessions() as db:
                hits = await search_knowledge_base(
                    db,
                    embeddings,
                    tenant_id=tenant_id,
                    knowledge_base_id=knowledge_base_id,
                    embedding_space_id=SPACE_ID,
                    query="refund window",
                    top_k=5,
                    min_score=0.5,
                    timeout_seconds=3,
                )
            if len(hits) != 5:
                raise RuntimeError("Capacity query returned fewer than five hits")
            return (perf_counter() - started) * 1000

        results = []
        previous = 0
        for size in sizes:
            await add_chunks(size - previous)
            previous = size
            for _ in range(3):
                await query_once()
            sequential = [await query_once() for _ in range(trials)]
            gate = asyncio.Semaphore(concurrency)

            async def limited_query(semaphore: asyncio.Semaphore) -> float:
                async with semaphore:
                    return await query_once()

            concurrent = await asyncio.gather(
                *(limited_query(gate) for _ in range(trials))
            )
            results.append(
                {
                    "active_chunks": size,
                    "sequential_p50_ms": percentile(sequential, 0.5),
                    "sequential_p95_ms": percentile(sequential, 0.95),
                    "concurrent_p50_ms": percentile(concurrent, 0.5),
                    "concurrent_p95_ms": percentile(concurrent, 0.95),
                }
            )
        async with bench_engine.connect() as connection:
            database_version = (
                await connection.execute(text("SHOW server_version"))
            ).scalar_one()
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "database_version": database_version,
            "vector_dimensions": 1536,
            "trials_per_mode": trials,
            "concurrency": concurrency,
            "model_calls": False,
            "corpus": "synthetic identical short chunks",
            "results": results,
        }
    finally:
        if bench_engine is not None:
            await bench_engine.dispose()
        if created_database:
            async with admin_engine.connect() as connection:
                await connection.execute(
                    text(f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)')
                )
        await admin_engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", type=int, nargs="+", default=[1000, 5000, 20000])
    parser.add_argument("--trials", type=int, default=20)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    if (
        arguments.trials < 2
        or arguments.concurrency < 1
        or any(size < 5 for size in arguments.sizes)
        or arguments.sizes != sorted(set(arguments.sizes))
    ):
        parser.error(
            "Use increasing unique sizes >= 5, trials >= 2 and concurrency >= 1"
        )
    report = asyncio.run(
        execute(arguments.sizes, arguments.trials, arguments.concurrency)
    )
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report["results"], ensure_ascii=False, indent=2))
    print(f"Report: {arguments.output}")


if __name__ == "__main__":
    main()
