"""Create knowledge bases, documents and versioned chunks.

Revision ID: 0001_initial
Revises:
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


knowledge_base_status = postgresql.ENUM(
    "ACTIVE", "ARCHIVED", name="knowledge_base_status", create_type=False
)
document_status = postgresql.ENUM(
    "UPLOADED",
    "PARSING",
    "CHUNKING",
    "EMBEDDING",
    "READY",
    "FAILED",
    name="document_status",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    knowledge_base_status.create(bind, checkfirst=True)
    document_status.create(bind, checkfirst=True)

    op.create_table(
        "knowledge_bases",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.String(2000), nullable=True),
        sa.Column(
            "status", knowledge_base_status, server_default="ACTIVE", nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("name", name="uq_knowledge_bases_name"),
    )
    op.create_table(
        "documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("knowledge_base_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("file_type", sa.String(100), nullable=False),
        sa.Column("storage_uri", sa.String(2048), nullable=False),
        sa.Column("checksum", sa.String(128), nullable=False),
        sa.Column("status", document_status, server_default="UPLOADED", nullable=False),
        sa.Column("active_index_version", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "active_index_version IS NULL OR active_index_version > 0",
            name="ck_documents_active_index_version_positive",
        ),
        sa.ForeignKeyConstraint(
            ["knowledge_base_id"], ["knowledge_bases.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_documents_knowledge_base_id", "documents", ["knowledge_base_id"]
    )
    op.create_table(
        "chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("index_version", sa.Integer(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("section_title", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "index_version > 0", name="ck_chunks_index_version_positive"
        ),
        sa.CheckConstraint(
            "chunk_index >= 0", name="ck_chunks_chunk_index_nonnegative"
        ),
        sa.CheckConstraint(
            "token_count >= 0", name="ck_chunks_token_count_nonnegative"
        ),
        sa.CheckConstraint(
            "page_number IS NULL OR page_number > 0",
            name="ck_chunks_page_number_positive",
        ),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "document_id",
            "index_version",
            "chunk_index",
            name="uq_chunks_version_index",
        ),
    )
    op.create_index(
        "ix_chunks_document_version", "chunks", ["document_id", "index_version"]
    )


def downgrade() -> None:
    op.drop_index("ix_chunks_document_version", table_name="chunks")
    op.drop_table("chunks")
    op.drop_index("ix_documents_knowledge_base_id", table_name="documents")
    op.drop_table("documents")
    op.drop_table("knowledge_bases")
    document_status.drop(op.get_bind(), checkfirst=True)
    knowledge_base_status.drop(op.get_bind(), checkfirst=True)
