"""Scope knowledge bases to authenticated subjects.

Revision ID: 0005_knowledge_base_owner
Revises: 0004_chunk_vector_index
"""

import sqlalchemy as sa

from alembic import op

revision = "0005_knowledge_base_owner"
down_revision = "0004_chunk_vector_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "knowledge_bases", sa.Column("owner_sub", sa.String(255), nullable=True)
    )
    op.execute("UPDATE knowledge_bases SET owner_sub = 'legacy-unassigned'")
    op.alter_column("knowledge_bases", "owner_sub", nullable=False)
    op.drop_constraint("uq_knowledge_bases_name", "knowledge_bases", type_="unique")
    op.create_unique_constraint(
        "uq_knowledge_bases_owner_name", "knowledge_bases", ["owner_sub", "name"]
    )
    op.create_index("ix_knowledge_bases_owner_sub", "knowledge_bases", ["owner_sub"])


def downgrade() -> None:
    duplicate_name = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT name FROM knowledge_bases GROUP BY name HAVING count(*) > 1 LIMIT 1"
            )
        )
        .scalar()
    )
    if duplicate_name is not None:
        raise RuntimeError(
            "Cannot restore global knowledge base name uniqueness while owners share a name"
        )
    op.drop_index("ix_knowledge_bases_owner_sub", table_name="knowledge_bases")
    op.drop_constraint(
        "uq_knowledge_bases_owner_name", "knowledge_bases", type_="unique"
    )
    op.create_unique_constraint("uq_knowledge_bases_name", "knowledge_bases", ["name"])
    op.drop_column("knowledge_bases", "owner_sub")
