"""Bounded lexical reranking of authorized vector candidates.

Chinese character bigrams and Latin words avoid database-specific language
analyzers. The vector threshold and candidate pool remain retrieval boundaries;
lexical evidence only changes the order inside that pool.
"""

import math
import re
import unicodedata
from collections import Counter

from app.schemas.retrieval import SearchHit

_WORDS = re.compile(r"[\u4e00-\u9fff]+|[a-z0-9]+")
_RRF_K = 60


def _terms(value: str) -> set[str]:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    terms: set[str] = set()
    for match in _WORDS.finditer(normalized):
        word = match.group()
        if "\u4e00" <= word[0] <= "\u9fff":
            terms.update(word[index : index + 2] for index in range(len(word) - 1))
        elif len(word) > 1:
            terms.add(word)
    return terms


def rerank_hits(query: str, hits: list[SearchHit]) -> list[SearchHit]:
    """Fuse exact cosine order with query-term coverage inside a small pool."""
    query_terms = _terms(query)
    if len(hits) < 2 or not query_terms:
        return hits

    body_terms = [_terms(hit.content) & query_terms for hit in hits]
    heading_terms = [_terms(" ".join(hit.section_path)) & query_terms for hit in hits]
    document_frequency = Counter(
        term
        for body, heading in zip(body_terms, heading_terms, strict=True)
        for term in body | heading
    )
    if not document_frequency:
        return hits
    weights = {
        term: math.log((len(hits) + 1) / (count + 1)) + 1
        for term, count in document_frequency.items()
    }
    denominator = sum(weights.values())
    lexical_scores = [
        (
            sum(weights[term] for term in body)
            + 1.5 * sum(weights[term] for term in heading)
        )
        / denominator
        for body, heading in zip(body_terms, heading_terms, strict=True)
    ]
    lexical_order = sorted(
        range(len(hits)),
        key=lambda index: (-lexical_scores[index], index),
    )
    lexical_ranks = {index: rank for rank, index in enumerate(lexical_order, start=1)}

    def fused_score(index: int) -> float:
        vector_score = 1 / (_RRF_K + index + 1)
        lexical_score = lexical_scores[index]
        if lexical_score == 0:
            return vector_score
        return vector_score + 1.5 * min(1.0, lexical_score) / (
            _RRF_K + lexical_ranks[index]
        )

    return [
        hits[index]
        for index in sorted(
            range(len(hits)), key=lambda index: (-fused_score(index), index)
        )
    ]
