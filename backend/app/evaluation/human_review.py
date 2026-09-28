"""Bind independent answer reviews to an immutable benchmark report."""

import hashlib
import json
from pathlib import Path


def report_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def review_template(report_path: Path, dataset_path: Path) -> dict:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    dataset_raw = dataset_path.read_bytes()
    dataset = json.loads(dataset_raw)
    dataset_sha256 = hashlib.sha256(dataset_raw).hexdigest()
    if report["dataset_sha256"] != dataset_sha256:
        raise ValueError("Benchmark report and dataset checksum differ")
    if report["dataset_version"] != dataset["version"]:
        raise ValueError("Benchmark report and dataset version differ")
    labeled_cases = {case["id"]: case for case in dataset["qa"]}
    if {case["id"] for case in report["qa_cases"]} != set(labeled_cases):
        raise ValueError("Benchmark report and dataset QA cases differ")
    if any(
        case["query"] != labeled_cases[case["id"]]["query"]
        for case in report["qa_cases"]
    ):
        raise ValueError("Benchmark report and dataset questions differ")
    return {
        "report_sha256": report_digest(report_path),
        "dataset_sha256": dataset_sha256,
        "dataset_version": report["dataset_version"],
        "reviewer": "",
        "reviewed_at": "",
        "cases": [
            {
                "id": case["id"],
                "question": case["query"],
                "answer": case["answer"],
                "expect_abstain": labeled_cases[case["id"]].get(
                    "expect_abstain", False
                ),
                "cited_evidence": case["cited_evidence"],
                "verdict": None,
                "notes": "",
            }
            for case in report["qa_cases"]
        ],
    }


def score_reviews(
    report_path: Path, dataset_path: Path, review_paths: list[Path]
) -> dict:
    """Require two complete, distinct reviews; disagreements count as failures."""
    if len(review_paths) != 2:
        raise ValueError("Exactly two independent reviews are required")
    expected = review_template(report_path, dataset_path)
    case_expectations = {
        case["id"]: case["expect_abstain"] for case in expected["cases"]
    }
    original_cases = {case["id"]: case for case in expected["cases"]}
    reviews = [json.loads(path.read_text(encoding="utf-8")) for path in review_paths]
    names = []
    verdicts = []
    for review in reviews:
        if review.get("report_sha256") != expected["report_sha256"]:
            raise ValueError("Review targets a different benchmark report")
        if review.get("dataset_sha256") != expected["dataset_sha256"]:
            raise ValueError("Review targets a different benchmark dataset")
        if review.get("dataset_version") != expected["dataset_version"]:
            raise ValueError("Review targets a different dataset version")
        name = str(review.get("reviewer", "")).strip()
        if not name or not str(review.get("reviewed_at", "")).strip():
            raise ValueError("Review needs reviewer identity and review date")
        names.append(name)
        cases = review.get("cases", [])
        if len(cases) != len(case_expectations):
            raise ValueError("Review must cover every QA case exactly once")
        case_verdicts = {}
        for case in cases:
            case_id = case.get("id")
            if case_id not in case_expectations or case_id in case_verdicts:
                raise ValueError("Review has an unknown or duplicate QA case")
            if any(
                case.get(field) != original_cases[case_id][field]
                for field in ("question", "answer", "expect_abstain", "cited_evidence")
            ):
                raise ValueError(f"Review evidence was modified for {case_id}")
            allowed = (
                {"correct_abstention", "incorrect_abstention"}
                if case_expectations[case_id]
                else {"supported", "partial", "unsupported"}
            )
            if case.get("verdict") not in allowed:
                raise ValueError(f"Missing or invalid verdict for {case_id}")
            case_verdicts[case_id] = case["verdict"]
        verdicts.append(case_verdicts)
    if names[0].casefold() == names[1].casefold():
        raise ValueError("Reviews must have distinct reviewer identities")

    results = []
    for case_id, expect_abstain in case_expectations.items():
        first, second = (review[case_id] for review in verdicts)
        results.append(
            {
                "id": case_id,
                "expect_abstain": expect_abstain,
                "verdicts": [first, second],
                "agreed": first == second,
                "passed": first == second
                and first == ("correct_abstention" if expect_abstain else "supported"),
            }
        )
    return {
        "report_sha256": expected["report_sha256"],
        "dataset_version": expected["dataset_version"],
        "reviewers": names,
        "case_count": len(results),
        "agreement_rate": sum(item["agreed"] for item in results) / len(results),
        "fact_support_rate": sum(item["passed"] for item in results) / len(results),
        "cases": results,
    }
