import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.models.document import Document
from app.models.knowledge_base import KnowledgeBase
from app.schemas.document import DocumentRead
from app.services.document import upload_document


knowledge_base_documents_router = APIRouter(
    prefix="/knowledge-bases/{knowledge_base_id}/documents", tags=["documents"]
)
documents_router = APIRouter(prefix="/documents", tags=["documents"])


@knowledge_base_documents_router.post(
    "", response_model=DocumentRead, status_code=status.HTTP_201_CREATED
)
async def upload_knowledge_base_document(
    knowledge_base_id: uuid.UUID,
    file: Annotated[UploadFile, File(...)],
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> Document:
    return await upload_document(db, knowledge_base_id, file, settings)


@knowledge_base_documents_router.get("", response_model=list[DocumentRead])
async def list_knowledge_base_documents(
    knowledge_base_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[Document]:
    if await db.get(KnowledgeBase, knowledge_base_id) is None:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    result = await db.scalars(
        select(Document)
        .where(Document.knowledge_base_id == knowledge_base_id)
        .order_by(Document.created_at.desc(), Document.id.desc())
    )
    return list(result)


@documents_router.get("/{document_id}", response_model=DocumentRead)
async def get_document(
    document_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Document:
    document = await db.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return document
