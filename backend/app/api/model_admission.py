"""Bound in-process model work after tenant authorization, without holding a DB lease."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import authorized_knowledge_base
from app.core.config import get_settings
from app.db.session import get_db
from app.models.knowledge_base import KnowledgeBase


class ModelAdmissionGate:
    def __init__(self, max_inflight: int, wait_seconds: float) -> None:
        self._slots = asyncio.Semaphore(max_inflight)
        self._wait_seconds = wait_seconds

    @asynccontextmanager
    async def slot(self) -> AsyncIterator[None]:
        try:
            await asyncio.wait_for(self._slots.acquire(), timeout=self._wait_seconds)
        except TimeoutError as exc:
            raise HTTPException(
                status_code=503,
                detail="Model capacity is busy",
                headers={"Retry-After": "1"},
            ) from exc
        try:
            yield
        finally:
            self._slots.release()


@lru_cache
def get_model_admission_gate() -> ModelAdmissionGate:
    settings = get_settings()
    return ModelAdmissionGate(
        settings.model_max_inflight_requests,
        settings.model_admission_wait_seconds,
    )


async def model_request_slot(
    _knowledge_base: Annotated[KnowledgeBase, Depends(authorized_knowledge_base)],
    db: Annotated[AsyncSession, Depends(get_db)],
    gate: Annotated[ModelAdmissionGate, Depends(get_model_admission_gate)],
) -> AsyncIterator[None]:
    # The authorization dependency has already scoped this knowledge base to
    # the caller. Do not keep its transaction or connection while queued.
    await db.rollback()
    async with gate.slot():
        yield
