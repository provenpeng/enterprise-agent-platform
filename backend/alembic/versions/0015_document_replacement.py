"""Stage a replacement source until its index is atomically published."""

import sqlalchemy as sa

from alembic import op

revision = "0015_document_replacement"
down_revision = "0014_diagnostic_history"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("pending_storage_uri", sa.String(2048)))
    op.add_column("documents", sa.Column("pending_checksum", sa.String(128)))
    op.add_column("documents", sa.Column("pending_filename", sa.String(255)))
    op.add_column("documents", sa.Column("pending_file_type", sa.String(100)))
    op.add_column("documents", sa.Column("archived_storage_uri", sa.String(2048)))
    op.create_check_constraint(
        "ck_documents_pending_source_complete",
        "documents",
        "(pending_storage_uri IS NULL AND pending_checksum IS NULL AND pending_filename IS NULL AND pending_file_type IS NULL) OR "
        "(pending_storage_uri IS NOT NULL AND pending_checksum IS NOT NULL AND pending_filename IS NOT NULL AND pending_file_type IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_documents_pending_source_complete", "documents", type_="check"
    )
    op.drop_column("documents", "archived_storage_uri")
    op.drop_column("documents", "pending_file_type")
    op.drop_column("documents", "pending_filename")
    op.drop_column("documents", "pending_checksum")
    op.drop_column("documents", "pending_storage_uri")
