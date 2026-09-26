"""Exercise host embeddings, Compose indexing, retrieval, QA and diagnosis."""

import argparse
import asyncio
import json
import os
import uuid
from pathlib import Path

import httpx

from app.business.demo_seed import seed_demo_orders
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.evaluation.benchmark import citations_match, load_benchmark
from app.evaluation.runner import inspect_corpus, prepare_corpus
from app.rag.embeddings import create_embeddings, validate_embedding

DATASET = Path(__file__).resolve().parents[1] / "evals" / "benchmark_v1.json"


async def _post(client: httpx.AsyncClient, path: str, payload: dict) -> dict:
    response = await client.post(path, json=payload)
    response.raise_for_status()
    return response.json()


async def run(base_url: str, tenant_id: uuid.UUID, timeout: float) -> dict:
    token = os.getenv("EAP_EVAL_TOKEN")
    if not token:
        raise ValueError("Set EAP_EVAL_TOKEN to a tenant admin token")
    settings = get_settings()
    secret = settings.effective_embedding_api_key
    if secret is None or not secret.get_secret_value():
        raise ValueError("Embedding API key is not configured")
    embeddings = create_embeddings(
        model=settings.embedding_model,
        api_key=secret.get_secret_value(),
        base_url=str(settings.embedding_api_base_url)
        if settings.embedding_api_base_url
        else None,
        timeout_seconds=settings.retrieval_embedding_timeout_seconds,
        native_dimensions=settings.embedding_native_dimensions,
    )
    validate_embedding(await embeddings.aembed_query("本地模型连接检查"))
    dataset, _ = load_benchmark(DATASET)
    async with httpx.AsyncClient(
        base_url=base_url.rstrip("/"),
        headers={"Authorization": f"Bearer {token}"},
        timeout=90,
    ) as client:
        knowledge_base_id = await prepare_corpus(
            client, DATASET, dataset, timeout_seconds=timeout
        )
        source_by_chunk, indexes = await inspect_corpus(
            client, knowledge_base_id, dataset, settings.embedding_space_id
        )
        async with SessionLocal() as db:
            await seed_demo_orders(db, tenant_id)
        base = f"/api/v1/knowledge-bases/{knowledge_base_id}"
        search = await _post(
            client,
            f"{base}/search",
            {"query": "客户退款申请的截止时间是什么？", "top_k": 10},
        )
        if not any(
            source_by_chunk.get(hit["chunk_id"]) == "refund_window"
            for hit in search["hits"]
        ):
            raise RuntimeError("Search did not find the refund window")
        answer = await _post(
            client, f"{base}/ask", {"query": "客户退款申请的截止时间是什么？"}
        )
        if not answer["grounded"] or not citations_match(
            answer["citations"], ("refund_window",), source_by_chunk
        ):
            raise RuntimeError("Answer did not cite the refund window exclusively")
        diagnosis = await _post(
            client,
            f"{base}/diagnose",
            {"question": "DEMO-WINDOW 为什么退款失败？", "order_id": "DEMO-WINDOW"},
        )
        if diagnosis["status"] != "ANSWERED" or not citations_match(
            diagnosis["citations"], ("refund_window_error",), source_by_chunk
        ):
            raise RuntimeError("Diagnosis did not cite the exact reason-code rule")
    return {
        "status": "passed",
        "knowledge_base_id": str(knowledge_base_id),
        "embedding_space_id": settings.embedding_space_id,
        "indexes": len(indexes),
        "search": "refund_window",
        "answer": "refund_window",
        "diagnosis": "refund_window_error",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--tenant-id", type=uuid.UUID, required=True)
    parser.add_argument("--timeout", type=float, default=600)
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    try:
        print(
            json.dumps(
                asyncio.run(run(args.base_url, args.tenant_id, args.timeout)),
                ensure_ascii=False,
                indent=2,
            )
        )
    except (ValueError, RuntimeError, TimeoutError, httpx.HTTPError) as exc:
        parser.exit(1, f"Model smoke failed: {exc}\n")


if __name__ == "__main__":
    main()
