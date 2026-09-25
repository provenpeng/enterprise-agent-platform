"""Live, fixed-case evaluation against a seeded and indexed local API."""

import argparse
import asyncio
import json
import os
import uuid
from pathlib import Path

import httpx

from app.evaluation.score import fraction, load_dataset, retrieval_hit, score_diagnostic

DATASET = Path(__file__).resolve().parents[1] / "evals" / "demo_cases.json"


async def evaluate(base_url: str, knowledge_base_id: uuid.UUID, token: str) -> dict:
    dataset = load_dataset(DATASET)
    path = f"/api/v1/knowledge-bases/{knowledge_base_id}"
    retrieval_results = []
    diagnostic_results = []
    total_tokens = 0
    async with httpx.AsyncClient(
        base_url=base_url.rstrip("/"),
        headers={"Authorization": f"Bearer {token}"},
        timeout=90,
    ) as client:
        for case in dataset.retrieval:
            response = await client.post(
                f"{path}/search", json={"query": case.query, "top_k": 5}
            )
            response.raise_for_status()
            retrieval_results.append(
                {"id": case.id, "hit": retrieval_hit(case, response.json()["hits"])}
            )
        for case in dataset.diagnostic:
            response = await client.post(
                f"{path}/diagnose",
                json={"question": case.question, "order_id": case.order_id},
            )
            response.raise_for_status()
            answer = response.json()
            trace = await client.get(f"/api/v1/agent-runs/{answer['run_id']}")
            trace.raise_for_status()
            run = trace.json()
            total_tokens += run["total_tokens"] or 0
            diagnostic_results.append(
                {"id": case.id, **score_diagnostic(case, answer, run["steps"])}
            )
    return {
        "dataset": "synthetic-demo-v1",
        "retrieval_recall_at_5": fraction([item["hit"] for item in retrieval_results]),
        "order_lookup_accuracy": fraction(
            [item["order_lookup"] for item in diagnostic_results]
        ),
        "reason_code_accuracy": fraction(
            [item["reason_code"] for item in diagnostic_results]
        ),
        "policy_route_accuracy": fraction(
            [item["policy_route"] for item in diagnostic_results]
        ),
        "citation_accuracy": fraction(
            [item["citation"] for item in diagnostic_results]
        ),
        "reported_model_tokens": total_tokens,
        "retrieval_cases": retrieval_results,
        "diagnostic_cases": diagnostic_results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate synthetic demo retrieval and Agent behavior"
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--knowledge-base-id", required=True, type=uuid.UUID)
    parser.add_argument("--min-score", type=float, default=0.75)
    args = parser.parse_args()
    if not 0 <= args.min_score <= 1:
        parser.error("--min-score must be between 0 and 1")
    token = os.environ.get("EAP_EVAL_TOKEN")
    if not token:
        parser.error(
            "Set EAP_EVAL_TOKEN to an admin token; it is needed to read Agent traces"
        )
    result = asyncio.run(evaluate(args.base_url, args.knowledge_base_id, token))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    metrics = (
        "retrieval_recall_at_5",
        "order_lookup_accuracy",
        "reason_code_accuracy",
        "policy_route_accuracy",
        "citation_accuracy",
    )
    if any(result[name] < args.min_score for name in metrics):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
