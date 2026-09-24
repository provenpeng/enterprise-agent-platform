"""Score synthetic demo outcomes without an LLM judge or hidden heuristics."""

from pathlib import Path

from pydantic import BaseModel, Field


class RetrievalCase(BaseModel):
    id: str
    query: str
    relevant_text: str


class DiagnosticCase(BaseModel):
    id: str
    question: str
    order_id: str
    expected_reason_code: str | None
    expect_policy_search: bool
    relevant_text: str | None


class EvalDataset(BaseModel):
    retrieval: list[RetrievalCase] = Field(min_length=1)
    diagnostic: list[DiagnosticCase] = Field(min_length=1)


def load_dataset(path: Path) -> EvalDataset:
    return EvalDataset.model_validate_json(path.read_text(encoding="utf-8"))


def retrieval_hit(case: RetrievalCase, hits: list[dict]) -> bool:
    return any(case.relevant_text in _source_text(hit) for hit in hits)


def _source_text(source: dict) -> str:
    return " ".join(
        [source.get("content", ""), source.get("section_title") or ""]
        + list(source.get("section_path") or [])
    )


def score_diagnostic(
    case: DiagnosticCase, response: dict, steps: list[dict]
) -> dict[str, bool]:
    order = response.get("order")
    attempts = order.get("refund_attempts", []) if order else []
    reason = attempts[-1].get("reason_code") if attempts else None
    searched = any(step["name"] == "retrieve_policy" for step in steps)
    citations = response.get("citations", [])
    cited_relevant = bool(
        case.relevant_text
        and any(
            case.relevant_text in _source_text(citation["source"])
            for citation in citations
        )
    )
    return {
        "order_lookup": bool(order and order["order_id"] == case.order_id),
        "reason_code": reason == case.expected_reason_code,
        "policy_route": searched == case.expect_policy_search,
        "citation": cited_relevant if case.expect_policy_search else not citations,
    }


def fraction(values: list[bool]) -> float:
    if not values:
        raise ValueError("Cannot score an empty evaluation set")
    return sum(values) / len(values)
