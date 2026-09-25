"""Prevent duplicate file content within a knowledge base.

Revision ID: 0002_document_checksum_unique
Revises: 0001_initial
"""

from alembic import op

revision = "0002_document_checksum_unique"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_documents_knowledge_base_checksum",
        "documents",
        ["knowledge_base_id", "checksum"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_documents_knowledge_base_checksum", "documents", type_="unique"
    )
