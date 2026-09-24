"""Explicit retention cleanup for persisted diagnostic runs."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_run import AgentRun


async def prune_agent_runs(db: AsyncSession, *, days: int) -> int:
    if days < 1:
        raise ValueError("Retention days must be positive")
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    deleted = await db.scalars(
        delete(AgentRun).where(AgentRun.started_at < cutoff).returning(AgentRun.id)
    )
    count = len(list(deleted))
    await db.commit()
    return count
