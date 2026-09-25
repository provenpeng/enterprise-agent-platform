"""Fixed dataset and transparent scoring remain reproducible offline."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage

from app.agent.model import DiagnosticPlan, _model_call
from app.evaluation.score import fraction, load_dataset, retrieval_hit, score_diagnostic

DATASET = Path(__file__).resolve().parents[1] / "evals" / "demo_cases.json"


def test_dataset_is_fixed_and_covers_each_synthetic_business_outcome() -> None:
    dataset = load_dataset(DATASET)
    assert {case.order_id for case in dataset.diagnostic} == {
        "DEMO-WINDOW",
        "DEMO-AMOUNT",
        "DEMO-GATEWAY",
        "DEMO-SUCCESS",
    }
    assert {case.relevant_text for case in dataset.retrieval} == {
        "REFUND_WINDOW_EXPIRED",
        "AMOUNT_EXCEEDS_REFUNDABLE",
        "GATEWAY_TIMEOUT",
    }


def test_scores_require_actual_retrieval_tool_route_and_relevant_citation() -> None:
    dataset = load_dataset(DATASET)
    case = dataset.diagnostic[0]
    response = {
        "order": {
            "order_id": case.order_id,
            "refund_attempts": [{"reason_code": case.expected_reason_code}],
        },
        "citations": [{"source": {"content": f"Rule {case.relevant_text}"}}],
    }
    steps = [{"name": "plan"}, {"name": "lookup_order"}, {"name": "retrieve_policy"}]
    assert all(score_diagnostic(case, response, steps).values())
    assert (
        score_diagnostic(case, {**response, "citations": []}, steps)["citation"]
        is False
    )
    assert score_diagnostic(case, response, steps[:-1])["policy_route"] is False
    retrieval = dataset.retrieval[0]
    assert retrieval_hit(retrieval, [{"content": retrieval.relevant_text}]) is True
    assert (
        retrieval_hit(
            retrieval,
            [{"content": "rule body", "section_path": [retrieval.relevant_text]}],
        )
        is True
    )
    assert retrieval_hit(retrieval, [{"content": "unrelated"}]) is False
    assert fraction([True, False, True, True]) == 0.75


def test_structured_model_usage_is_extracted_without_exposing_raw_message() -> None:
    raw = AIMessage(
        content="",
        usage_metadata={"input_tokens": 12, "output_tokens": 4, "total_tokens": 16},
    )
    parsed = DiagnosticPlan(order_id="DEMO-WINDOW", search_policy=True)
    result = _model_call({"raw": raw, "parsed": parsed}, DiagnosticPlan)
    assert result.value == parsed
    assert result.usage is not None and result.usage.total_tokens == 16


@pytest.mark.parametrize(
    "metadata",
    [
        None,
        {},
        {"input_tokens": 12},
        {"input_tokens": 12, "output_tokens": 4, "total_tokens": "16"},
    ],
)
def test_structured_model_keeps_valid_answer_when_usage_is_incomplete(metadata) -> None:
    parsed = DiagnosticPlan(order_id="DEMO-WINDOW", search_policy=True)
    result = _model_call(
        {"raw": SimpleNamespace(usage_metadata=metadata), "parsed": parsed},
        DiagnosticPlan,
    )
    assert result.value == parsed
    assert result.usage is None
