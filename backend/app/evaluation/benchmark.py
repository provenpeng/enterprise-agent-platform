"""Versioned synthetic corpus and evidence-based benchmark scoring."""

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class CorpusDocument(BaseModel):
    filename: str = Field(min_length=1)
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class SourceLabel(BaseModel):
    filename: str
    section_path: tuple[str, ...] = Field(min_length=1)


class RetrievalCase(BaseModel):
    id: str
    category: Literal["direct", "paraphrase", "confusable", "no_answer"]
    query: str = Field(min_length=1)
    relevant_source_ids: tuple[str, ...] = ()
    expect_no_hits: bool = False
    min_score: float = Field(default=0.0, ge=0, le=1)

    @model_validator(mode="after")
    def validate_expectation(self) -> "RetrievalCase":
        if self.expect_no_hits == bool(self.relevant_source_ids):
            raise ValueError(
                "Retrieval case needs either sources or no-hit expectation"
            )
        if (self.category == "no_answer") != self.expect_no_hits:
            raise ValueError("Retrieval category must match no-hit expectation")
        return self


class QACase(BaseModel):
    id: str
    query: str = Field(min_length=1)
    required_source_ids: tuple[str, ...] = ()
    expect_abstain: bool = False

    @model_validator(mode="after")
    def validate_expectation(self) -> "QACase":
        if self.expect_abstain == bool(self.required_source_ids):
            raise ValueError("QA case needs either sources or abstention expectation")
        return self


class DiagnosticCase(BaseModel):
    id: str
    question: str = Field(min_length=1)
    order_id: str = Field(min_length=1)
    expected_reason_code: str | None
    expect_policy_search: bool
    expected_status: Literal["ANSWERED", "BUSINESS_FACTS_ONLY"]
    required_source_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_expectation(self) -> "DiagnosticCase":
        if self.expect_policy_search != bool(self.required_source_ids):
            raise ValueError("Diagnostic citations must match expected policy route")
        return self


class AuthorizationCase(BaseModel):
    id: str
    endpoint: Literal["search", "ask", "diagnose"]
    query: str = Field(min_length=1)
    order_id: str | None = None

    @model_validator(mode="after")
    def validate_request(self) -> "AuthorizationCase":
        if self.endpoint == "diagnose" and not self.order_id:
            raise ValueError("Diagnostic authorization case needs an order ID")
        return self


class BenchmarkDataset(BaseModel):
    version: str = Field(min_length=1)
    corpus: list[CorpusDocument] = Field(min_length=1)
    sources: dict[str, SourceLabel] = Field(min_length=1)
    retrieval: list[RetrievalCase] = Field(min_length=1)
    qa: list[QACase] = Field(min_length=1)
    diagnostic: list[DiagnosticCase] = Field(min_length=1)
    authorization: list[AuthorizationCase] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_references(self) -> "BenchmarkDataset":
        filenames = [document.filename for document in self.corpus]
        if len(filenames) != len(set(filenames)):
            raise ValueError("Corpus filenames must be unique")
        if any(label.filename not in filenames for label in self.sources.values()):
            raise ValueError("A source label references a missing corpus document")
        labels = [
            (label.filename, label.section_path) for label in self.sources.values()
        ]
        if len(labels) != len(set(labels)):
            raise ValueError("Source labels must identify distinct sections")
        cases = [*self.retrieval, *self.qa, *self.diagnostic, *self.authorization]
        ids = [case.id for case in cases]
        if len(ids) != len(set(ids)):
            raise ValueError("Benchmark case IDs must be unique")
        used_sources = {
            source for case in self.retrieval for source in case.relevant_source_ids
        }
        used_sources.update(
            source for case in self.qa for source in case.required_source_ids
        )
        used_sources.update(
            source for case in self.diagnostic for source in case.required_source_ids
        )
        if used_sources - self.sources.keys():
            raise ValueError("A case references an undefined source label")
        if not any(case.expect_no_hits for case in self.retrieval) or not any(
            not case.expect_no_hits for case in self.retrieval
        ):
            raise ValueError("Retrieval cases need positive and no-answer examples")
        if not any(case.expect_abstain for case in self.qa) or not any(
            not case.expect_abstain for case in self.qa
        ):
            raise ValueError("QA cases need positive and abstention examples")
        if {case.endpoint for case in self.authorization} != {
            "search",
            "ask",
            "diagnose",
        }:
            raise ValueError("Authorization cases must cover all knowledge base APIs")
        return self


def corpus_files(
    path: Path, dataset: BenchmarkDataset
) -> list[tuple[CorpusDocument, Path]]:
    """Resolve only files below the dataset directory and verify their content."""
    root = path.parent.resolve()
    resolved = []
    for document in dataset.corpus:
        source = (root / document.path).resolve()
        if not source.is_relative_to(root) or source.name != document.filename:
            raise ValueError(f"Invalid corpus path for {document.filename}")
        if hashlib.sha256(source.read_bytes()).hexdigest() != document.sha256:
            raise ValueError(f"Corpus checksum mismatch for {document.filename}")
        resolved.append((document, source))
    return resolved


def load_benchmark(path: Path) -> tuple[BenchmarkDataset, str]:
    raw = path.read_bytes()
    dataset = BenchmarkDataset.model_validate_json(raw)
    corpus_files(path, dataset)
    return dataset, hashlib.sha256(raw).hexdigest()


def relevant_rank(
    hits: list[dict], expected_sources: tuple[str, ...], source_by_chunk: dict[str, str]
) -> int | None:
    for rank, hit in enumerate(hits, start=1):
        if source_by_chunk.get(hit["chunk_id"]) in expected_sources:
            return rank
    return None


def citations_match(
    citations: list[dict],
    expected_sources: tuple[str, ...],
    source_by_chunk: dict[str, str],
) -> bool:
    """Require every labeled source, and reject any citation outside that set."""
    observed = [
        source_by_chunk.get(citation["source"]["chunk_id"]) for citation in citations
    ]
    return bool(observed) and set(observed) == set(expected_sources)


def score_diagnostic(
    case: DiagnosticCase,
    response: dict,
    steps: list[dict],
    source_by_chunk: dict[str, str],
) -> dict[str, bool]:
    order = response.get("order")
    attempts = order.get("refund_attempts", []) if order else []
    reason = attempts[-1].get("reason_code") if attempts else None
    citations = response.get("citations", [])
    return {
        "order_lookup": bool(order and order.get("order_id") == case.order_id),
        "reason_code": reason == case.expected_reason_code,
        "policy_route": any(step.get("name") == "retrieve_policy" for step in steps)
        == case.expect_policy_search,
        "status": response.get("status") == case.expected_status,
        "citation_source": citations_match(
            citations, case.required_source_ids, source_by_chunk
        )
        if case.required_source_ids
        else not citations,
    }


def average(values: list[float]) -> float:
    if not values:
        raise ValueError("Cannot score an empty set")
    return sum(values) / len(values)


def benchmark_metrics(
    retrieval: list[dict],
    qa: list[dict],
    diagnostic: list[dict],
    authorization: list[dict],
) -> dict[str, float]:
    positives = [case for case in retrieval if not case["expect_no_hits"]]
    negatives = [case for case in retrieval if case["expect_no_hits"]]
    qa_positive = [case for case in qa if not case["expect_abstain"]]
    qa_negative = [case for case in qa if case["expect_abstain"]]
    return {
        "retrieval_recall_at_1": average(
            [float(case["rank"] == 1) for case in positives]
        ),
        "retrieval_recall_at_5": average(
            [
                float(case["rank"] is not None and case["rank"] <= 5)
                for case in positives
            ]
        ),
        "retrieval_mrr_at_5": average(
            [
                1 / case["rank"] if case["rank"] and case["rank"] <= 5 else 0
                for case in positives
            ]
        ),
        "retrieval_no_hit_rate": average(
            [float(case["no_hits"]) for case in negatives]
        ),
        "qa_citation_source_accuracy": average(
            [float(case["citation_source"]) for case in qa_positive]
        ),
        "qa_abstention_accuracy": average(
            [float(case["abstained"]) for case in qa_negative]
        ),
        "diagnostic_order_lookup_accuracy": average(
            [float(case["order_lookup"]) for case in diagnostic]
        ),
        "diagnostic_reason_code_accuracy": average(
            [float(case["reason_code"]) for case in diagnostic]
        ),
        "diagnostic_policy_route_accuracy": average(
            [float(case["policy_route"]) for case in diagnostic]
        ),
        "diagnostic_status_accuracy": average(
            [float(case["status"]) for case in diagnostic]
        ),
        "diagnostic_citation_source_accuracy": average(
            [float(case["citation_source"]) for case in diagnostic]
        ),
        "tenant_isolation_accuracy": average(
            [float(case["blocked"]) for case in authorization]
        ),
    }


def compare_baseline(report: dict, baseline_path: Path, tolerance: float) -> list[str]:
    """Compare quality metrics only when both runs used identical labeled data."""
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    if baseline.get("dataset_sha256") != report["dataset_sha256"]:
        raise ValueError("Baseline uses a different dataset or corpus manifest")
    if set(baseline.get("metrics", {})) != set(report["metrics"]):
        raise ValueError("Baseline has a different metric schema")
    regressions = []
    deltas = {}
    for metric, current in report["metrics"].items():
        previous = baseline["metrics"][metric]
        deltas[metric] = current - previous
        if current < previous - tolerance:
            regressions.append(metric)
    report["baseline_comparison"] = {
        "baseline": str(baseline_path),
        "max_regression": tolerance,
        "metric_deltas": deltas,
        "regressions": regressions,
    }
    return regressions


def assess_quality_gate(
    metrics: dict[str, float], *, min_score: float, regressions: list[str]
) -> dict:
    below_threshold = [name for name, value in metrics.items() if value < min_score]
    mandatory_failures = (
        ["tenant_isolation_accuracy"]
        if metrics["tenant_isolation_accuracy"] != 1.0
        else []
    )
    return {
        "min_score": min_score,
        "below_threshold": below_threshold,
        "mandatory_failures": mandatory_failures,
        "passed": not below_threshold and not mandatory_failures and not regressions,
    }
