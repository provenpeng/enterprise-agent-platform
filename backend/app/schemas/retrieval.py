"""Public retrieval request and stable source metadata."""

import uuid
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints


class SearchRequest(BaseModel):
    query: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)
    ]
    top_k: int = Field(default=5, ge=1, le=20)
    min_score: float = Field(default=0.0, ge=0.0, le=1.0)


class SearchHit(BaseModel):
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_name: str
    index_version: int
    chunk_index: int
    content: str
    score: float
    page_number: int | None
    section_title: str | None
    section_path: list[str]


class SearchResponse(BaseModel):
    knowledge_base_id: uuid.UUID
    hits: list[SearchHit]
