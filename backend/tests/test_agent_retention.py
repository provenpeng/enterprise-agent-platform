"""Retention removes old runs and their trace steps as one unit."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app.agent.retention import prune_agent_runs
from app.models.agent_run import AgentRun, AgentRunStatus, AgentRunStep


@pytest.mark.asyncio
async def test_prune_old_runs_cascades_steps_and_keeps_recent_runs(api_client):
    _, _, sessions, _ = api_client
    tenant_id = uuid.uuid5(uuid.NAMESPACE_URL, "enterprise-agent-platform:test-user")
    old = AgentRun(
        tenant_id=tenant_id,
        question="old",
        model_name="test",
        status=AgentRunStatus.RUNNING,
        started_at=datetime.now(timezone.utc) - timedelta(days=40),
    )
    recent = AgentRun(
        tenant_id=tenant_id,
        question="recent",
        model_name="test",
        status=AgentRunStatus.SUCCEEDED,
        started_at=datetime.now(timezone.utc) - timedelta(days=1),
    )
    async with sessions() as db:
        db.add_all([old, recent])
        await db.flush()
        db.add(
            AgentRunStep(
                run_id=old.id,
                sequence=1,
                name="plan",
                input_data={},
                output_data={},
                duration_ms=1,
            )
        )
        await db.commit()
        assert await prune_agent_runs(db, days=30) == 1
        assert await db.get(AgentRun, old.id) is None
        assert await db.get(AgentRun, recent.id) is not None
        assert await db.scalar(select(func.count()).select_from(AgentRunStep)) == 0
        with pytest.raises(ValueError):
            await prune_agent_runs(db, days=0)
