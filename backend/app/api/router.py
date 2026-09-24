from fastapi import APIRouter

from app.api.routes import (
    answer,
    agent_runs,
    business,
    diagnostic,
    documents,
    health,
    knowledge_bases,
    retrieval,
    tenants,
)


api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router)
api_router.include_router(tenants.router)
api_router.include_router(knowledge_bases.router)
api_router.include_router(retrieval.router)
api_router.include_router(answer.router)
api_router.include_router(business.router)
api_router.include_router(diagnostic.router)
api_router.include_router(agent_runs.router)
api_router.include_router(documents.knowledge_base_documents_router)
api_router.include_router(documents.documents_router)
