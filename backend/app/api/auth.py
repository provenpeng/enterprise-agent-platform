"""Verify externally issued JWTs and scope resources to their owner."""

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Annotated
import uuid

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.models.document import Document
from app.models.knowledge_base import KnowledgeBase


bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class Principal:
    subject: str


@lru_cache
def _public_key(path: Path) -> bytes:
    return path.read_bytes()


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=401,
        detail="Invalid bearer token",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_principal(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> Principal:
    if credentials is None:
        raise _unauthorized()
    try:
        key = _public_key(settings.auth_public_key_path)
    except OSError as exc:
        raise HTTPException(
            status_code=503, detail="Authentication is not configured"
        ) from exc
    try:
        claims = jwt.decode(
            credentials.credentials,
            key,
            algorithms=["RS256"],
            issuer=settings.auth_issuer,
            audience=settings.auth_audience,
            options={"require": ["sub", "iss", "aud", "iat", "exp"]},
        )
    except jwt.PyJWTError as exc:
        raise _unauthorized() from exc
    subject = claims["sub"]
    if (
        not isinstance(subject, str)
        or not subject
        or len(subject) > 255
        or subject == "legacy-unassigned"
    ):
        raise _unauthorized()
    return Principal(subject=subject)


async def owned_knowledge_base(
    db: AsyncSession, knowledge_base_id: uuid.UUID, principal: Principal
) -> KnowledgeBase:
    knowledge_base = await db.scalar(
        select(KnowledgeBase).where(
            KnowledgeBase.id == knowledge_base_id,
            KnowledgeBase.owner_sub == principal.subject,
        )
    )
    if knowledge_base is None:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    return knowledge_base


async def owned_document(
    db: AsyncSession, document_id: uuid.UUID, principal: Principal
) -> Document:
    document = await db.scalar(
        select(Document)
        .join(KnowledgeBase)
        .where(Document.id == document_id, KnowledgeBase.owner_sub == principal.subject)
    )
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return document
