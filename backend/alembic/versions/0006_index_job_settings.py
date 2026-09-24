"""Snapshot result-affecting indexing settings on each job.

Revision ID: 0006_index_job_settings
Revises: 0005_knowledge_base_owner
"""

import sqlalchemy as sa
from alembic import op


revision = "0006_index_job_settings"
down_revision = "0005_knowledge_base_owner"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for name, default, type_ in (
        ("target_tokens", "400", sa.Integer()),
        ("max_tokens", "600", sa.Integer()),
        ("max_chunks", "1000", sa.Integer()),
        ("embed_batch_size", "32", sa.Integer()),
        ("tokenizer_name", "cl100k_base", sa.String(100)),
        ("processing_version", "1", sa.String(20)),
    ):
        op.add_column(
            "document_index_jobs",
            sa.Column(name, type_, nullable=False, server_default=default),
        )
        op.alter_column("document_index_jobs", name, server_default=None)


def downgrade() -> None:
    for name in (
        "processing_version",
        "tokenizer_name",
        "embed_batch_size",
        "max_chunks",
        "max_tokens",
        "target_tokens",
    ):
        op.drop_column("document_index_jobs", name)
