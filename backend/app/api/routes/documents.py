import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Query, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import Principal, get_principal, owned_document, owned_knowledge_base
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.models.document import Document
from app.models.chunk import Chunk
from app.models.index_job import IndexJob
from app.schemas.document import DocumentRead
from app.schemas.chunk import ActiveChunkRead
from app.schemas.index_job import IndexJobRead
from app.services.document import upload_document
from app.services.index_jobs import enqueue_reindex


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
    principal: Annotated[Principal, Depends(get_principal)],
) -> Document:
    await owned_knowledge_base(db, knowledge_base_id, principal)
    return await upload_document(db, knowledge_base_id, file, settings)


@knowledge_base_documents_router.get("", response_model=list[DocumentRead])
async def list_knowledge_base_documents(
    knowledge_base_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    principal: Annotated[Principal, Depends(get_principal)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[Document]:
    await owned_knowledge_base(db, knowledge_base_id, principal)
    result = await db.scalars(
        select(Document)
        .where(Document.knowledge_base_id == knowledge_base_id)
        .order_by(Document.created_at.desc(), Document.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result)


@documents_router.get("/{document_id}", response_model=DocumentRead)
async def get_document(
    document_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> Document:
    return await owned_document(db, document_id, principal)


@documents_router.post(
    "/{document_id}/index-jobs",
    response_model=IndexJobRead,
    status_code=status.HTTP_201_CREATED,
)
async def reindex_document(
    document_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> IndexJob:
    await owned_document(db, document_id, principal)
    return await enqueue_reindex(db, document_id, settings)


@documents_router.get("/{document_id}/index-jobs", response_model=list[IndexJobRead])
async def list_document_index_jobs(
    document_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> list[IndexJob]:
    await owned_document(db, document_id, principal)
    result = await db.scalars(
        select(IndexJob)
        .where(IndexJob.document_id == document_id)
        .order_by(IndexJob.index_version.desc())
        .limit(20)
    )
    return list(result)


@documents_router.get("/{document_id}/chunks", response_model=list[ActiveChunkRead])
async def list_active_document_chunks(
    document_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    principal: Annotated[Principal, Depends(get_principal)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ActiveChunkRead]:
    document = await owned_document(db, document_id, principal)
    if document.active_index_version is None:
        return []
    chunks = await db.scalars(
        select(Chunk)
        .where(
            Chunk.document_id == document_id,
            Chunk.index_version == document.active_index_version,
        )
        .order_by(Chunk.chunk_index)
        .limit(limit)
        .offset(offset)
    )
    return [
        ActiveChunkRead(
            id=chunk.id,
            index_version=chunk.index_version,
            chunk_index=chunk.chunk_index,
            content=chunk.content,
            token_count=chunk.token_count,
            page_number=chunk.page_number,
            section_title=chunk.section_title,
            section_path=chunk.metadata_.get("section_path", []),
        )
        for chunk in chunks
    ]
