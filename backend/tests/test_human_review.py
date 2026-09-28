"""Ensure manual quality claims require complete independent evidence."""

import hashlib
import json
from pathlib import Path

import pytest

from app.evaluation.human_review import review_template, score_reviews


def _report(tmp_path: Path) -> tuple[Path, Path]:
    dataset = tmp_path / "dataset.json"
    dataset.write_text(
        json.dumps(
            {
                "version": "test-v1",
                "qa": [
                    {
                        "id": "answer",
                        "query": "What is the rule?",
                        "expect_abstain": False,
                    },
                    {"id": "missing", "query": "Unknown?", "expect_abstain": True},
                ],
            }
        ),
        encoding="utf-8",
    )
    path = tmp_path / "report.json"
    path.write_text(
        json.dumps(
            {
                "dataset_version": "test-v1",
                "dataset_sha256": hashlib.sha256(dataset.read_bytes()).hexdigest(),
                "qa_cases": [
                    {
                        "id": "answer",
                        "query": "What is the rule?",
                        "answer": "A",
                        "cited_evidence": [{"content": "A"}],
                    },
                    {
                        "id": "missing",
                        "query": "Unknown?",
                        "answer": "Unknown",
                        "cited_evidence": [],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    return path, dataset


def _review(tmp_path: Path, report: Path, dataset: Path, reviewer: str) -> Path:
    data = review_template(report, dataset)
    data["reviewer"] = reviewer
    data["reviewed_at"] = "2026-09-28"
    data["cases"][0]["verdict"] = "supported"
    data["cases"][1]["verdict"] = "correct_abstention"
    path = tmp_path / f"{reviewer}.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_two_complete_reviews_are_scored(tmp_path: Path) -> None:
    report, dataset = _report(tmp_path)
    first = _review(tmp_path, report, dataset, "Alice")
    second = _review(tmp_path, report, dataset, "Bob")
    result = score_reviews(report, dataset, [first, second])
    assert result["agreement_rate"] == result["fact_support_rate"] == 1
    data = json.loads(second.read_text(encoding="utf-8"))
    data["cases"][0]["verdict"] = "partial"
    second.write_text(json.dumps(data), encoding="utf-8")
    result = score_reviews(report, dataset, [first, second])
    assert result["agreement_rate"] == result["fact_support_rate"] == 0.5


def test_review_rejects_incomplete_stale_or_same_reviewer(tmp_path: Path) -> None:
    report, dataset = _report(tmp_path)
    first = _review(tmp_path, report, dataset, "Alice")
    second = _review(tmp_path, report, dataset, "Bob")
    with pytest.raises(ValueError, match="distinct"):
        score_reviews(report, dataset, [first, first])
    data = json.loads(second.read_text(encoding="utf-8"))
    data["cases"][0]["verdict"] = None
    second.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="verdict"):
        score_reviews(report, dataset, [first, second])
    report.write_text(report.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="different benchmark report"):
        score_reviews(report, dataset, [first, second])
