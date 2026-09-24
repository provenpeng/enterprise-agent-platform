"""Persist each diagnostic step while keeping provider error details out of API data."""

import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from time import perf_counter
from typing import AsyncIterator, Any

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.model import TokenUsage
from app.models.agent_run import AgentRun, AgentRunStatus, AgentRunStep
from app.schemas.diagnostic import DiagnoseResponse


@dataclass
class StepCapture:
    output: dict[str, Any] = field(default_factory=dict)
    usage: TokenUsage | None = None


class RunRecorder:
    def __init__(
        self,
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        knowledge_base_id: uuid.UUID,
        question: str,
        model_name: str,
    ) -> None:
        self._db = db
        self._run_id = uuid.uuid4()
        self._run = AgentRun(
            id=self._run_id,
            tenant_id=tenant_id,
            knowledge_base_id=knowledge_base_id,
            question=question,
            model_name=model_name,
            status=AgentRunStatus.RUNNING,
        )
        self._started = perf_counter()
        self._sequence = 0
        self._input_tokens = 0
        self._output_tokens = 0
        self._total_tokens = 0
        self._has_usage = False

    @property
    def run_id(self) -> uuid.UUID:
        return self._run_id

    async def start(self) -> None:
        self._db.add(self._run)
        await self._db.commit()

    @asynccontextmanager
    async def step(
        self, name: str, input_data: dict[str, Any]
    ) -> AsyncIterator[StepCapture]:
        started = perf_counter()
        capture = StepCapture()
        try:
            yield capture
        except Exception as exc:
            await self._db.rollback()
            await self._record(
                name, input_data, capture, started, error_code=type(exc).__name__
            )
            raise
        else:
            await self._record(name, input_data, capture, started, error_code=None)

    async def _record(
        self,
        name: str,
        input_data: dict[str, Any],
        capture: StepCapture,
        started: float,
        error_code: str | None,
    ) -> None:
        self._sequence += 1
        usage = capture.usage
        if usage is not None:
            self._has_usage = True
            self._input_tokens += usage.input_tokens
            self._output_tokens += usage.output_tokens
            self._total_tokens += usage.total_tokens
        self._db.add(
            AgentRunStep(
                run_id=self._run_id,
                sequence=self._sequence,
                name=name,
                input_data=input_data,
                output_data=capture.output,
                error_code=error_code,
                input_tokens=usage.input_tokens if usage else None,
                output_tokens=usage.output_tokens if usage else None,
                total_tokens=usage.total_tokens if usage else None,
                duration_ms=max(0, int((perf_counter() - started) * 1000)),
            )
        )
        await self._db.commit()

    async def finish(
        self,
        *,
        response: DiagnoseResponse | None = None,
        error: Exception | None = None,
    ) -> None:
        await self._db.execute(
            update(AgentRun)
            .where(AgentRun.id == self._run_id)
            .values(
                status=AgentRunStatus.FAILED if error else AgentRunStatus.SUCCEEDED,
                outcome=response.status if response else None,
                answer=response.answer if response else None,
                error_code=type(error).__name__ if error else None,
                input_tokens=self._input_tokens if self._has_usage else None,
                output_tokens=self._output_tokens if self._has_usage else None,
                total_tokens=self._total_tokens if self._has_usage else None,
                duration_ms=max(0, int((perf_counter() - self._started) * 1000)),
                finished_at=datetime.now(timezone.utc),
            )
        )
        await self._db.commit()
