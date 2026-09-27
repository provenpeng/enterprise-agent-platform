"""Admin-only Agent run views."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.models.agent_run import AgentRunStatus
from app.schemas.diagnostic import DiagnoseResponse


class AgentRunSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    knowledge_base_id: uuid.UUID | None
    question: str
    model_name: str
    status: AgentRunStatus
    outcome: str | None
    answer: str | None
    error_code: str | None
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    duration_ms: int | None
    started_at: datetime
    finished_at: datetime | None


class AgentRunStepRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    sequence: int
    name: str
    input_data: dict[str, Any]
    output_data: dict[str, Any]
    error_code: str | None
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    duration_ms: int
    created_at: datetime


class AgentRunDetail(AgentRunSummary):
    response_data: DiagnoseResponse | None
    steps: list[AgentRunStepRead]


class DiagnosticHistorySummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    question: str
    outcome: str | None
    started_at: datetime


class DiagnosticHistoryDetail(DiagnosticHistorySummary):
    response: DiagnoseResponse
