"""Cited answer contract returned by the knowledge base API."""

import uuid

from pydantic import BaseModel, Field

from app.schemas.retrieval import SearchHit, SearchRequest


class AskRequest(SearchRequest):
    top_k: int = Field(default=10, ge=1, le=10)
    min_score: float = Field(default=0.5, ge=0.0, le=1.0)


class AnswerCitation(BaseModel):
    number: int
    source: SearchHit


class AskResponse(BaseModel):
    knowledge_base_id: uuid.UUID
    answer: str
    grounded: bool
    citations: list[AnswerCitation]
