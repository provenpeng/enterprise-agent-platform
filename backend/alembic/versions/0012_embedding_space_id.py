"""Record vector-space identity on new index jobs.

Revision ID: 0012_embedding_space_id
Revises: 0011_prune_chunk_indexes
"""

import sqlalchemy as sa

from alembic import op

revision = "0012_embedding_space_id"
down_revision = "0011_prune_chunk_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Historical provider URLs and native dimensions were not stored. Keep
    # their identity unknown instead of assigning a potentially false match.
    op.add_column(
        "document_index_jobs",
        sa.Column("embedding_space_id", sa.String(64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("document_index_jobs", "embedding_space_id")
