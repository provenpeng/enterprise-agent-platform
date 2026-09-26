"""Prepare and run the versioned RAG/Agent benchmark against a local API."""

import argparse
import asyncio
import json
import os
import tempfile
import uuid
from pathlib import Path

import httpx

from app.core.config import get_settings
from app.evaluation.benchmark import (
    assess_quality_gate,
    compare_baseline,
    load_benchmark,
    load_quality_profile,
)
from app.evaluation.runner import inspect_corpus, prepare_corpus, run_benchmark

DEFAULT_DATASET = Path(__file__).resolve().parents[1] / "evals" / "benchmark_v1.json"


async def execute(arguments: argparse.Namespace) -> int:
    token = os.getenv("EAP_EVAL_TOKEN")
    if not token:
        raise ValueError("Set EAP_EVAL_TOKEN to a tenant admin token")
    outsider_token = os.getenv("EAP_EVAL_OUTSIDER_TOKEN")
    if arguments.action == "run" and not outsider_token:
        raise ValueError("Set EAP_EVAL_OUTSIDER_TOKEN to another tenant's token")
    settings = get_settings()
    dataset, dataset_sha256 = load_benchmark(arguments.dataset)
    profile = (
        load_quality_profile(arguments.quality_profile, dataset.version)
        if arguments.action == "run" and arguments.quality_profile
        else None
    )
    async with httpx.AsyncClient(
        base_url=arguments.base_url.rstrip("/"),
        headers={"Authorization": f"Bearer {token}"},
        timeout=90,
    ) as client:
        if arguments.action == "prepare":
            knowledge_base_id = await prepare_corpus(
                client,
                arguments.dataset,
                dataset,
                timeout_seconds=arguments.timeout,
            )
            print(f"knowledge_base_id={knowledge_base_id}", flush=True)
            await inspect_corpus(
                client, knowledge_base_id, dataset, settings.embedding_space_id
            )
            return 0

        async with httpx.AsyncClient(
            base_url=arguments.base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {outsider_token}"},
            timeout=90,
        ) as outsider_client:
            report = await run_benchmark(
                client,
                outsider_client,
                arguments.knowledge_base_id,
                dataset,
                dataset_sha256,
                embedding_space_id=settings.embedding_space_id,
                model_config={
                    "source": "runner_environment",
                    "embedding_model": settings.embedding_model,
                    "embedding_native_dimensions": settings.embedding_native_dimensions,
                    "embedding_revision": settings.embedding_revision,
                    "embedding_space_id": settings.embedding_space_id,
                    "answer_model": settings.answer_model,
                    "chat_structured_output_method": settings.chat_structured_output_method,
                },
            )

    regressions = (
        compare_baseline(report, arguments.baseline, arguments.max_regression)
        if arguments.baseline
        else []
    )
    report["quality_gate"] = assess_quality_gate(
        report["metrics"],
        min_score=0
        if profile
        else (arguments.min_score if arguments.min_score is not None else 0.75),
        regressions=regressions,
        thresholds=profile[0].thresholds if profile else None,
    )
    if profile:
        report["quality_gate"]["profile"] = {
            "name": profile[0].name,
            "dataset_version": profile[0].dataset_version,
            "sha256": profile[1],
        }
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        prefix=arguments.output.name + ".",
        suffix=".tmp",
        dir=arguments.output.parent,
        delete=False,
    ) as temporary:
        json.dump(report, temporary, ensure_ascii=False, indent=2)
        temporary.write("\n")
    Path(temporary.name).replace(arguments.output)
    print(json.dumps(report["metrics"], ensure_ascii=False, indent=2))
    print(f"Report: {arguments.output}")
    if report["quality_gate"]["below_threshold"]:
        print(
            "Below threshold: " + ", ".join(report["quality_gate"]["below_threshold"])
        )
    if report["quality_gate"]["mandatory_failures"]:
        print(
            "Mandatory checks failed: "
            + ", ".join(report["quality_gate"]["mandatory_failures"])
        )
    if regressions:
        print(f"Regressions: {', '.join(regressions)}")
    return 0 if report["quality_gate"]["passed"] else 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    actions = parser.add_subparsers(dest="action", required=True)
    prepare = actions.add_parser("prepare", help="Create and index a fresh corpus")
    prepare.add_argument("--timeout", type=float, default=600)
    run = actions.add_parser("run", help="Score an indexed benchmark corpus")
    run.add_argument("--knowledge-base-id", type=uuid.UUID, required=True)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--baseline", type=Path)
    run.add_argument("--max-regression", type=float, default=0.05)
    threshold = run.add_mutually_exclusive_group()
    threshold.add_argument("--min-score", type=float)
    threshold.add_argument("--quality-profile", type=Path)
    arguments = parser.parse_args()
    if arguments.action == "prepare" and arguments.timeout <= 0:
        parser.error("--timeout must be positive")
    if arguments.action == "run" and not 0 <= arguments.max_regression <= 1:
        parser.error("--max-regression must be between 0 and 1")
    if (
        arguments.action == "run"
        and arguments.min_score is not None
        and not 0 <= arguments.min_score <= 1
    ):
        parser.error("--min-score must be between 0 and 1")
    try:
        raise SystemExit(asyncio.run(execute(arguments)))
    except (
        ValueError,
        FileNotFoundError,
        TimeoutError,
        RuntimeError,
        httpx.HTTPError,
    ) as exc:
        parser.exit(2, f"Benchmark setup error: {exc}\n")


if __name__ == "__main__":
    main()
