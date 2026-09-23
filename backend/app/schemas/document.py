import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.document import DocumentStatus


class DocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    knowledge_base_id: uuid.UUID
    filename: str
    file_type: str
    checksum: str
    status: DocumentStatus
    active_index_version: int | None
    created_at: datetime
    updated_at: datetime
