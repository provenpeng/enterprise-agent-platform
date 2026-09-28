"""Bound model work after tenant authorization with local or shared slots."""

import asyncio
import itertools
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.api.auth import authorized_knowledge_base
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.models.knowledge_base import KnowledgeBase

logger = logging.getLogger(__name__)
LOCK_NAMESPACE = 0x454150


def _busy() -> HTTPException:
    return HTTPException(
        status_code=503,
        detail="Model capacity is busy",
        headers={"Retry-After": "1"},
    )


class ModelAdmissionGate:
    def __init__(self, max_inflight: int, wait_seconds: float) -> None:
        self._slots = asyncio.Semaphore(max_inflight)
        self._wait_seconds = wait_seconds

    @asynccontextmanager
    async def slot(self) -> AsyncIterator[None]:
        try:
            await asyncio.wait_for(self._slots.acquire(), timeout=self._wait_seconds)
        except TimeoutError as exc:
            raise _busy() from exc
        try:
            yield
        finally:
            self._slots.release()


class PostgresModelAdmissionGate:
    """Session advisory locks share capacity across API processes and replicas."""

    def __init__(self, database_url: str, max_inflight: int, wait_seconds: float):
        self._engine = create_async_engine(
            database_url, isolation_level="AUTOCOMMIT", poolclass=NullPool
        )
        self._max_inflight = max_inflight
        self._wait_seconds = wait_seconds
        self._offset = itertools.count()

    async def _acquire(self) -> tuple[AsyncConnection, int]:
        while True:
            connection = await self._engine.connect()
            locked_slot = None
            try:
                first = next(self._offset) % self._max_inflight
                for offset in range(self._max_inflight):
                    slot = (first + offset) % self._max_inflight
                    locked = await connection.scalar(
                        text("SELECT pg_try_advisory_lock(:namespace, :slot)"),
                        {"namespace": LOCK_NAMESPACE, "slot": slot},
                    )
                    if locked:
                        locked_slot = slot
                        return connection, slot
            finally:
                if locked_slot is None:
                    await connection.close()
            await asyncio.sleep(0.01)

    @asynccontextmanager
    async def slot(self) -> AsyncIterator[None]:
        connection = None
        try:
            async with asyncio.timeout(self._wait_seconds):
                connection, slot = await self._acquire()
        except TimeoutError as exc:
            if connection is not None:
                await connection.close()
            raise _busy() from exc
        except SQLAlchemyError as exc:
            if connection is not None:
                await connection.close()
            raise HTTPException(
                status_code=503, detail="Model capacity is unavailable"
            ) from exc
        try:
            yield
        finally:
            try:
                await connection.scalar(
                    text("SELECT pg_advisory_unlock(:namespace, :slot)"),
                    {"namespace": LOCK_NAMESPACE, "slot": slot},
                )
            except SQLAlchemyError:
                logger.exception("Could not explicitly release model admission slot")
            finally:
                await connection.close()

    async def dispose(self) -> None:
        await self._engine.dispose()


@lru_cache(maxsize=32)
def _cached_gate(
    backend: str, database_url: str, max_inflight: int, wait_seconds: float
) -> ModelAdmissionGate | PostgresModelAdmissionGate:
    if backend == "postgres":
        return PostgresModelAdmissionGate(
            database_url,
            max_inflight,
            wait_seconds,
        )
    return ModelAdmissionGate(max_inflight, wait_seconds)


def get_model_admission_gate(
    settings: Annotated[Settings, Depends(get_settings)],
) -> ModelAdmissionGate | PostgresModelAdmissionGate:
    return _cached_gate(
        settings.model_admission_backend,
        settings.database_url,
        settings.model_max_inflight_requests,
        settings.model_admission_wait_seconds,
    )


async def model_request_slot(
    _knowledge_base: Annotated[KnowledgeBase, Depends(authorized_knowledge_base)],
    db: Annotated[AsyncSession, Depends(get_db)],
    gate: Annotated[
        ModelAdmissionGate | PostgresModelAdmissionGate,
        Depends(get_model_admission_gate),
    ],
) -> AsyncIterator[None]:
    # The authorization dependency has already scoped this knowledge base to
    # the caller. Do not keep its transaction or connection while queued.
    await db.rollback()
    async with gate.slot():
        yield
