import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.index_job import IndexJobStatus


class IndexJobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    document_id: uuid.UUID
    index_version: int
    processing_backend: str
    processing_version: str
    embedding_model: str
    embedding_space_id: str | None
    target_tokens: int
    max_tokens: int
    max_chunks: int
    embed_batch_size: int
    tokenizer_name: str
    status: IndexJobStatus
    attempts: int
    next_attempt_at: datetime
    lease_expires_at: datetime | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime
