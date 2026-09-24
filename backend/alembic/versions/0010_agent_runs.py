"""Persist tenant-scoped Agent runs and ordered step traces.

Revision ID: 0010_agent_runs
Revises: 0009_demo_business
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "0010_agent_runs"
down_revision = "0009_demo_business"
branch_labels = None
depends_on = None

run_status = postgresql.ENUM(
    "RUNNING", "SUCCEEDED", "FAILED", name="agent_run_status", create_type=False
)


def upgrade() -> None:
    run_status.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "agent_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("knowledge_base_id", postgresql.UUID(as_uuid=True)),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("model_name", sa.String(100), nullable=False),
        sa.Column("status", run_status, nullable=False),
        sa.Column("outcome", sa.String(40)),
        sa.Column("answer", sa.Text()),
        sa.Column("error_code", sa.String(100)),
        sa.Column("input_tokens", sa.Integer()),
        sa.Column("output_tokens", sa.Integer()),
        sa.Column("total_tokens", sa.Integer()),
        sa.Column("duration_ms", sa.Integer()),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["knowledge_base_id"], ["knowledge_bases.id"], ondelete="SET NULL"
        ),
    )
    op.create_index(
        "ix_agent_runs_tenant_started", "agent_runs", ["tenant_id", "started_at"]
    )
    op.create_table(
        "agent_run_steps",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(40), nullable=False),
        sa.Column("input_data", postgresql.JSONB(), nullable=False),
        sa.Column("output_data", postgresql.JSONB(), nullable=False),
        sa.Column("error_code", sa.String(100)),
        sa.Column("input_tokens", sa.Integer()),
        sa.Column("output_tokens", sa.Integer()),
        sa.Column("total_tokens", sa.Integer()),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("run_id", "sequence", name="uq_agent_run_step_sequence"),
    )


def downgrade() -> None:
    op.drop_table("agent_run_steps")
    op.drop_index("ix_agent_runs_tenant_started", table_name="agent_runs")
    op.drop_table("agent_runs")
    run_status.drop(op.get_bind(), checkfirst=True)
