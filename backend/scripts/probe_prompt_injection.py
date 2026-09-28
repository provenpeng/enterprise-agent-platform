"""Run live model probes against untrusted retrieved text and report failures."""

import argparse
import asyncio
import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.api.chat_config import require_chat_config
from app.core.config import get_settings
from app.rag.answer_generator import LangChainAnswerGenerator
from app.schemas.retrieval import SearchHit
from app.services.citations import attach_verified_citations

DEFAULT_CASES = (
    Path(__file__).resolve().parents[1] / "evals" / "prompt_injection_v1.json"
)


async def run(path: Path) -> dict:
    suite = json.loads(path.read_text(encoding="utf-8"))
    settings = get_settings()
    generator = LangChainAnswerGenerator(
        require_chat_config(settings, purpose="Answer")
    )
    results = []
    for index, case in enumerate(suite["cases"], start=1):
        hit = SearchHit(
            chunk_id=uuid.uuid5(
                uuid.NAMESPACE_URL, f"probe:{suite['version']}:{case['id']}"
            ),
            document_id=uuid.uuid5(uuid.NAMESPACE_URL, "probe:expense-policy"),
            document_name="untrusted_expense_policy.md",
            index_version=1,
            chunk_index=index,
            content=case["evidence"],
            score=0.9,
            page_number=None,
            section_title="报销期限",
            section_path=["员工报销", "报销期限"],
        )
        draft = await generator.generate(case["question"], [hit])
        verified = attach_verified_citations(draft.answer, draft.cited_chunk_ids, [hit])
        answer = verified[0] if verified else ""
        cited = bool(verified and verified[1])
        passed = (
            cited == case["expect_cited"]
            and case["must_contain"] in answer
            and not any(value in answer for value in case["forbidden_substrings"])
        )
        results.append(
            {"id": case["id"], "passed": passed, "answer": answer, "cited": cited}
        )
    return {
        "suite_version": suite["version"],
        "suite_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": settings.answer_model,
        "structured_output_method": settings.chat_structured_output_method,
        "passed": sum(case["passed"] for case in results),
        "total": len(results),
        "cases": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    result = asyncio.run(run(arguments.cases))
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Prompt injection probes: {result['passed']}/{result['total']}")
    print(f"Report: {arguments.output}")
    if result["passed"] != result["total"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
