"""Add durable document index jobs and chunk embeddings.

Revision ID: 0003_document_index_jobs
Revises: 0002_document_checksum_unique
"""

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0003_document_index_jobs"
down_revision = "0002_document_checksum_unique"
branch_labels = None
depends_on = None


job_status = postgresql.ENUM(
    "PENDING",
    "RUNNING",
    "SUCCEEDED",
    "FAILED",
    name="index_job_status",
    create_type=False,
)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    job_status.create(op.get_bind(), checkfirst=True)
    op.add_column("chunks", sa.Column("embedding", Vector(1536), nullable=True))
    op.create_table(
        "document_index_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("index_version", sa.Integer(), nullable=False),
        sa.Column("processing_backend", sa.String(20), nullable=False),
        sa.Column("embedding_model", sa.String(100), nullable=False),
        sa.Column("status", job_status, server_default="PENDING", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
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
        sa.CheckConstraint("index_version > 0", name="ck_index_jobs_version_positive"),
        sa.CheckConstraint("attempts >= 0", name="ck_index_jobs_attempts_nonnegative"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "document_id", "index_version", name="uq_index_jobs_document_version"
        ),
    )
    op.create_index(
        "ix_index_jobs_status_due",
        "document_index_jobs",
        ["status", "next_attempt_at", "created_at"],
    )
    op.create_index(
        "ix_index_jobs_status_lease",
        "document_index_jobs",
        ["status", "lease_expires_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_index_jobs_status_lease", table_name="document_index_jobs")
    op.drop_index("ix_index_jobs_status_due", table_name="document_index_jobs")
    op.drop_table("document_index_jobs")
    op.drop_column("chunks", "embedding")
    job_status.drop(op.get_bind(), checkfirst=True)
