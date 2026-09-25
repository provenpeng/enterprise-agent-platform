"""Give every knowledge base a durable tenant boundary.

Revision ID: 0008_tenants
Revises: 0007_index_job_constraints
"""

import uuid

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "0008_tenants"
down_revision = "0007_index_job_constraints"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.add_column(
        "knowledge_bases", sa.Column("tenant_id", UUID(as_uuid=True), nullable=True)
    )
    connection = op.get_bind()
    owners = connection.execute(
        sa.text("SELECT DISTINCT owner_sub FROM knowledge_bases")
    ).scalars()
    for owner_sub in owners:
        tenant_id = uuid.uuid5(
            uuid.NAMESPACE_URL, f"enterprise-agent-platform:{owner_sub}"
        )
        connection.execute(
            sa.text("INSERT INTO tenants (id, name) VALUES (:id, :name)"),
            {"id": tenant_id, "name": f"Migrated {owner_sub}"[:255]},
        )
        connection.execute(
            sa.text(
                "UPDATE knowledge_bases SET tenant_id = :tenant_id WHERE owner_sub = :owner_sub"
            ),
            {"tenant_id": tenant_id, "owner_sub": owner_sub},
        )
    op.alter_column("knowledge_bases", "tenant_id", nullable=False)
    op.create_foreign_key(
        "fk_knowledge_bases_tenant_id",
        "knowledge_bases",
        "tenants",
        ["tenant_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_knowledge_bases_tenant_id", "knowledge_bases", ["tenant_id"])
    op.drop_constraint(
        "uq_knowledge_bases_owner_name", "knowledge_bases", type_="unique"
    )
    op.create_unique_constraint(
        "uq_knowledge_bases_tenant_name", "knowledge_bases", ["tenant_id", "name"]
    )


def downgrade() -> None:
    duplicate = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT owner_sub, name FROM knowledge_bases GROUP BY owner_sub, name HAVING count(*) > 1 LIMIT 1"
            )
        )
        .first()
    )
    if duplicate is not None:
        raise RuntimeError(
            "Cannot restore owner name uniqueness while a tenant has duplicate owner names"
        )
    op.drop_constraint(
        "uq_knowledge_bases_tenant_name", "knowledge_bases", type_="unique"
    )
    op.create_unique_constraint(
        "uq_knowledge_bases_owner_name", "knowledge_bases", ["owner_sub", "name"]
    )
    op.drop_index("ix_knowledge_bases_tenant_id", table_name="knowledge_bases")
    op.drop_constraint(
        "fk_knowledge_bases_tenant_id", "knowledge_bases", type_="foreignkey"
    )
    op.drop_column("knowledge_bases", "tenant_id")
    op.drop_table("tenants")
