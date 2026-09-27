"""Admin-only access to tenant-scoped diagnostic run history."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.auth import Principal, get_principal, require_admin
from app.db.session import get_db
from app.models.agent_run import AgentRun
from app.schemas.agent_run import (
    AgentRunDetail,
    AgentRunSummary,
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
