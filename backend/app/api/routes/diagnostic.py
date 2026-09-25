"""Tenant-scoped order diagnostic Agent endpoint."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from langchain_core.embeddings import Embeddings
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.model import DiagnosticModel
from app.agent.trace import RunRecorder
from app.agent.workflow import DiagnosticOptions, DiagnosticWorkflow
from app.api.auth import Principal, authorized_knowledge_base, get_principal
from app.api.diagnostic_provider import get_diagnostic_model
from app.api.embedding_provider import get_query_embeddings
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.models.knowledge_base import KnowledgeBase
from app.schemas.diagnostic import DiagnoseRequest, DiagnoseResponse

router = APIRouter(prefix="/knowledge-bases/{knowledge_base_id}", tags=["diagnostics"])


@router.post("/diagnose", response_model=DiagnoseResponse)
async def diagnose(
    knowledge_base_id: uuid.UUID,
    payload: DiagnoseRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    principal: Annotated[Principal, Depends(get_principal)],
    _knowledge_base: Annotated[KnowledgeBase, Depends(authorized_knowledge_base)],
    embeddings: Annotated[Embeddings, Depends(get_query_embeddings)],
    model: Annotated[DiagnosticModel, Depends(get_diagnostic_model)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> DiagnoseResponse:
    recorder = RunRecorder(
        db,
        tenant_id=principal.tenant_id,
        knowledge_base_id=knowledge_base_id,
        question=payload.question,
        model_name=settings.answer_model,
    )
    workflow = DiagnosticWorkflow(
        db,
        embeddings,
        model,
        recorder,
        DiagnosticOptions(
            tenant_id=principal.tenant_id,
            knowledge_base_id=knowledge_base_id,
            embedding_model=settings.embedding_model,
            explicit_order_id=payload.order_id,
            planning_timeout_seconds=settings.diagnostic_planning_timeout_seconds,
            embedding_timeout_seconds=settings.retrieval_embedding_timeout_seconds,
            generation_timeout_seconds=settings.answer_generation_timeout_seconds,
        ),
    )
    return await workflow.run(payload.question)
