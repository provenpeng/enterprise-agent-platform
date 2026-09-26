"""The chat adapter maps short evidence labels to authorized retrieval IDs."""

import uuid

import pytest

from app.rag.answer_generator import LangChainAnswerGenerator, _EvidenceAnswer
from app.schemas.retrieval import SearchHit


class FixedChain:
    def __init__(self, draft: _EvidenceAnswer) -> None:
        self.draft = draft
        self.messages = None

    async def ainvoke(self, messages):
        self.messages = messages
        return self.draft


def _hit(content: str) -> SearchHit:
    return SearchHit(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        document_name="policy.md",
        index_version=1,
        chunk_index=0,
        content=content,
        score=0.8,
        page_number=None,
        section_title="Policy",
        section_path=["Policy"],
    )


@pytest.mark.asyncio
async def test_model_sees_short_labels_and_both_citations_map_to_exact_chunks():
    hits = [_hit("退款从支付日计算"), _hit("报销从费用发生日计算")]
    chain = FixedChain(
        _EvidenceAnswer(answer="两个期限的起点不同。", cited_evidence_ids=["E1", "E2"])
    )
    generator = object.__new__(LangChainAnswerGenerator)
    generator._chain = chain
    generator._format_instruction = ""

    result = await generator.generate("分别从哪天起算？", hits)

    assert result.cited_chunk_ids == [str(hit.chunk_id) for hit in hits]
    prompt = chain.messages[1].content
    assert '"evidence_id": "E1"' in prompt
    assert '"evidence_id": "E2"' in prompt
    assert all(str(hit.chunk_id) not in prompt for hit in hits)


@pytest.mark.asyncio
async def test_unknown_label_invalidates_entire_draft():
    hit = _hit("仅 E1 是候选证据")
    chain = FixedChain(
        _EvidenceAnswer(answer="unsupported", cited_evidence_ids=["E1", "E99"])
    )
    generator = object.__new__(LangChainAnswerGenerator)
    generator._chain = chain
    generator._format_instruction = ""

    result = await generator.generate("question", [hit])

    assert result.answer == ""
    assert result.cited_chunk_ids == []
