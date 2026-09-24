import uuid

from pydantic import BaseModel


class ActiveChunkRead(BaseModel):
    id: uuid.UUID
    index_version: int
    chunk_index: int
    content: str
    token_count: int
    page_number: int | None
    section_title: str | None
    section_path: list[str]
