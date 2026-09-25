"""Attach source markers only for IDs from the current authorized retrieval."""

from app.schemas.answer import AnswerCitation
from app.schemas.retrieval import SearchHit


def attach_verified_citations(
    answer: str, cited_chunk_ids: list[str], hits: list[SearchHit]
) -> tuple[str, list[AnswerCitation]] | None:
    text = answer.strip()
    unique_ids = list(dict.fromkeys(cited_chunk_ids))
    authorized = {str(hit.chunk_id): hit for hit in hits}
    if not text or not unique_ids or any(id_ not in authorized for id_ in unique_ids):
        return None

    citations = [
        AnswerCitation(number=number, source=authorized[id_])
        for number, id_ in enumerate(unique_ids, start=1)
    ]
    markers = " ".join(f"[{citation.number}]" for citation in citations)
    return f"{text}\n\n来源：{markers}", citations
