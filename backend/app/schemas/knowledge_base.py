import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.models.knowledge_base import KnowledgeBaseStatus


KnowledgeBaseName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)
]


class KnowledgeBaseCreate(BaseModel):
    name: KnowledgeBaseName
    description: str | None = Field(default=None, max_length=2000)


class KnowledgeBaseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None
    status: KnowledgeBaseStatus
    created_at: datetime
    updated_at: datetime
