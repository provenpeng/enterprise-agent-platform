"""Enforce valid saved indexing limits.

Revision ID: 0007_index_job_constraints
Revises: 0006_index_job_settings
"""

from alembic import op


revision = "0007_index_job_constraints"
down_revision = "0006_index_job_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_check_constraint(
        "ck_index_jobs_token_limits",
        "document_index_jobs",
        "target_tokens > 0 AND target_tokens <= max_tokens",
    )
    op.create_check_constraint(
        "ck_index_jobs_max_chunks_positive", "document_index_jobs", "max_chunks > 0"
    )
    op.create_check_constraint(
        "ck_index_jobs_embed_batch_positive",
        "document_index_jobs",
        "embed_batch_size > 0",
    )


def downgrade() -> None:
    for name in (
        "ck_index_jobs_embed_batch_positive",
        "ck_index_jobs_max_chunks_positive",
        "ck_index_jobs_token_limits",
    ):
        op.drop_constraint(name, "document_index_jobs", type_="check")
