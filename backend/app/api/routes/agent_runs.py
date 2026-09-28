"""Admin-only access to tenant-scoped diagnostic run history."""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.auth import Principal, get_principal, require_admin
from app.db.session import get_db
from app.models.agent_run import AgentRun, AgentRunStatus, AgentRunStep
from app.schemas.agent_run import (
    AgentRunDetail,
    AgentRunMetrics,
    AgentRunSummary,
    AgentStepMetrics,
    DiagnosticHistoryDetail,
    DiagnosticHistorySummary,
)
from app.schemas.diagnostic import DiagnoseResponse

router = APIRouter(prefix="/agent-runs", tags=["agent-runs"])


@router.get("/mine", response_model=list[DiagnosticHistorySummary])
async def list_my_diagnostics(
    knowledge_base_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    principal: Annotated[Principal, Depends(get_principal)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[AgentRun]:
    rows = await db.scalars(
        select(AgentRun)
        .where(
            AgentRun.tenant_id == principal.tenant_id,
            AgentRun.owner_sub == principal.subject,
            AgentRun.knowledge_base_id == knowledge_base_id,
            AgentRun.response_data.is_not(None),
        )
        .order_by(AgentRun.started_at.desc(), AgentRun.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(rows)


@router.get("/mine/{run_id}", response_model=DiagnosticHistoryDetail)
async def get_my_diagnostic(
    run_id: uuid.UUID,
    knowledge_base_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> DiagnosticHistoryDetail:
    run = await db.scalar(
        select(AgentRun).where(
            AgentRun.id == run_id,
            AgentRun.tenant_id == principal.tenant_id,
            AgentRun.owner_sub == principal.subject,
            AgentRun.knowledge_base_id == knowledge_base_id,
            AgentRun.response_data.is_not(None),
        )
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Diagnostic run not found")
    return DiagnosticHistoryDetail(
        id=run.id,
        question=run.question,
        outcome=run.outcome,
        started_at=run.started_at,
        response=DiagnoseResponse.model_validate(run.response_data),
    )


@router.get("", response_model=list[AgentRunSummary])
async def list_agent_runs(
    db: Annotated[AsyncSession, Depends(get_db)],
    principal: Annotated[Principal, Depends(get_principal)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[AgentRun]:
    require_admin(principal)
    rows = await db.scalars(
        select(AgentRun)
        .where(AgentRun.tenant_id == principal.tenant_id)
        .order_by(AgentRun.started_at.desc(), AgentRun.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(rows)


@router.get("/metrics", response_model=AgentRunMetrics)
async def get_agent_run_metrics(
    db: Annotated[AsyncSession, Depends(get_db)],
    principal: Annotated[Principal, Depends(get_principal)],
    hours: Annotated[int, Query(ge=1, le=720)] = 24,
) -> AgentRunMetrics:
    require_admin(principal)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    scope = (
        AgentRun.tenant_id == principal.tenant_id,
        AgentRun.started_at >= cutoff,
    )
    row = (
        await db.execute(
            select(
                func.count().label("total"),
                func.count()
                .filter(AgentRun.status == AgentRunStatus.RUNNING)
                .label("running"),
                func.count()
                .filter(AgentRun.status == AgentRunStatus.SUCCEEDED)
                .label("succeeded"),
                func.count()
                .filter(AgentRun.status == AgentRunStatus.FAILED)
                .label("failed"),
                func.percentile_cont(0.5)
                .within_group(AgentRun.duration_ms)
                .label("p50"),
                func.percentile_cont(0.95)
                .within_group(AgentRun.duration_ms)
                .label("p95"),
                func.coalesce(func.sum(AgentRun.total_tokens), 0).label("tokens"),
                func.count()
                .filter(
                    AgentRun.status == AgentRunStatus.SUCCEEDED,
                    AgentRun.total_tokens.is_(None),
                )
                .label("unreported"),
            ).where(*scope)
        )
    ).one()
    outcome_rows = await db.execute(
        select(AgentRun.outcome, func.count())
        .where(*scope, AgentRun.outcome.is_not(None))
        .group_by(AgentRun.outcome)
    )
    step_rows = await db.execute(
        select(
            AgentRunStep.name,
            func.count(),
            func.percentile_cont(0.95).within_group(AgentRunStep.duration_ms),
            func.coalesce(func.sum(AgentRunStep.total_tokens), 0),
        )
        .join(AgentRun, AgentRun.id == AgentRunStep.run_id)
        .where(*scope)
        .group_by(AgentRunStep.name)
        .order_by(AgentRunStep.name)
    )
    return AgentRunMetrics(
        window_hours=hours,
        total=row.total,
        running=row.running,
        succeeded=row.succeeded,
        failed=row.failed,
        p50_duration_ms=row.p50,
        p95_duration_ms=row.p95,
        reported_model_tokens=row.tokens,
        succeeded_without_reported_tokens=row.unreported,
        outcomes={name: count for name, count in outcome_rows},
        steps=[
            AgentStepMetrics(
                name=name,
                count=count,
                p95_duration_ms=p95,
                reported_model_tokens=tokens,
            )
            for name, count, p95, tokens in step_rows
        ],
    )


@router.get("/{run_id}", response_model=AgentRunDetail)
async def get_agent_run(
    run_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> AgentRun:
    require_admin(principal)
    run = await db.scalar(
        select(AgentRun)
        .options(selectinload(AgentRun.steps))
        .where(AgentRun.id == run_id, AgentRun.tenant_id == principal.tenant_id)
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Agent run not found")
    return run
