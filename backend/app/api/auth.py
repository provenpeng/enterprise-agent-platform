"""Verify externally issued JWTs and scope resources to their tenant."""

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
from app.db.session import get_db
from app.models.document import Document
from app.models.knowledge_base import KnowledgeBase
from app.models.tenant import Tenant


bearer = HTTPBearer(auto_error=False)
LEGACY_TENANT_ID = uuid.uuid5(
    uuid.NAMESPACE_URL, "enterprise-agent-platform:legacy-unassigned"
)


@dataclass(frozen=True)
class Principal:
    subject: str
    tenant_id: uuid.UUID
    role: str


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
            options={
                "require": ["sub", "iss", "aud", "iat", "exp", "tenant_id", "role"]
            },
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
    try:
        tenant_id = uuid.UUID(claims["tenant_id"])
    except (TypeError, ValueError, AttributeError) as exc:
        raise _unauthorized() from exc
    role = claims["role"]
    if (
        tenant_id.int == 0
        or tenant_id == LEGACY_TENANT_ID
        or not isinstance(role, str)
        or role not in {"admin", "viewer"}
    ):
        raise _unauthorized()
    return Principal(subject=subject, tenant_id=tenant_id, role=role)


def require_admin(principal: Principal) -> None:
    if principal.role != "admin":
        raise HTTPException(
            status_code=403, detail="Tenant administrator role required"
        )


async def current_tenant(db: AsyncSession, principal: Principal) -> Tenant:
    tenant = await db.get(Tenant, principal.tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return tenant


async def tenant_knowledge_base(
    db: AsyncSession, knowledge_base_id: uuid.UUID, principal: Principal
) -> KnowledgeBase:
    knowledge_base = await db.scalar(
        select(KnowledgeBase).where(
            KnowledgeBase.id == knowledge_base_id,
            KnowledgeBase.tenant_id == principal.tenant_id,
        )
    )
    if knowledge_base is None:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    return knowledge_base


async def authorized_knowledge_base(
    knowledge_base_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> KnowledgeBase:
    return await tenant_knowledge_base(db, knowledge_base_id, principal)


async def tenant_document(
    db: AsyncSession, document_id: uuid.UUID, principal: Principal
) -> Document:
    document = await db.scalar(
        select(Document)
        .join(KnowledgeBase)
        .where(
            Document.id == document_id, KnowledgeBase.tenant_id == principal.tenant_id
        )
    )
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return document
