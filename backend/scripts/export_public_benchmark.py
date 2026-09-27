"""Export a reviewed synthetic benchmark without local database identifiers."""

import argparse
import json
from pathlib import Path

from app.evaluation.benchmark import load_benchmark


def public_report(report: dict, dataset_path: Path) -> dict:
    dataset, digest = load_benchmark(dataset_path)
    if report.get("dataset_sha256") != digest:
        raise ValueError("Report and dataset SHA-256 differ")
    if not report.get("quality_gate", {}).get("passed"):
        raise ValueError("Report did not pass its quality gate")
    if {case["id"] for case in report["qa_cases"]} != {case.id for case in dataset.qa}:
        raise ValueError("Report QA cases differ from the dataset")
    qa = [
        {
            "id": case["id"],
            "query": case["query"],
            "answer": case["answer"],
            "citation_source": case["citation_source"],
            "abstained": case["abstained"],
            "cited_evidence": case["cited_evidence"],
            "error": case["error"],
        }
        for case in report["qa_cases"]
    ]
    return {
        "dataset_version": report["dataset_version"],
        "dataset_sha256": digest,
        "generated_at": report["generated_at"],
        "expected_model_config": report["expected_model_config"],
        "indexes": report["indexes"],
        "case_counts": report["case_counts"],
        "metrics": report["metrics"],
        "quality_gate": report["quality_gate"],
        "retrieval_cases": [
            {
                key: case[key]
                for key in (
                    "id",
                    "category",
                    "expect_no_hits",
                    "rank",
                    "no_hits",
                    "error",
                )
            }
            for case in report["retrieval_cases"]
        ],
        "qa_cases": qa,
        "diagnostic_cases": [
            {
                key: case[key]
                for key in (
                    "id",
                    "order_lookup",
                    "reason_code",
                    "policy_route",
                    "status",
                    "citation_source",
                    "error",
                )
            }
            for case in report["diagnostic_cases"]
        ],
        "authorization_cases": [
            {key: case[key] for key in ("id", "endpoint", "blocked", "error")}
            for case in report["authorization_cases"]
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = json.loads(args.report.read_text(encoding="utf-8"))
    exported = public_report(report, args.dataset)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(exported, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
