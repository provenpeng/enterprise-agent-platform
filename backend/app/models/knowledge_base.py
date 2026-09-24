import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.document import Document
    from app.models.tenant import Tenant


class KnowledgeBaseStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class KnowledgeBase(Base):
    __tablename__ = "knowledge_bases"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_knowledge_bases_tenant_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    owner_sub: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(String(2000))
    status: Mapped[KnowledgeBaseStatus] = mapped_column(
        Enum(KnowledgeBaseStatus, name="knowledge_base_status"),
        nullable=False,
        default=KnowledgeBaseStatus.ACTIVE,
        server_default=KnowledgeBaseStatus.ACTIVE.value,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    documents: Mapped[list["Document"]] = relationship(
        back_populates="knowledge_base",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    tenant: Mapped["Tenant"] = relationship(back_populates="knowledge_bases")
