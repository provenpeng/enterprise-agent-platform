"""Owner-visible knowledge Q&A history."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.schemas.answer import AnswerCitation


class ConversationSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    knowledge_base_id: uuid.UUID
    title: str
    created_at: datetime
    updated_at: datetime


class ConversationTurnRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    question: str
    answer: str
    grounded: bool
    citations: list[AnswerCitation]
    created_at: datetime


class ConversationDetail(ConversationSummary):
    turns: list[ConversationTurnRead]
    has_older: bool
