"""Persist owner and the complete diagnostic response for history."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0014_diagnostic_history"
down_revision = "0013_conversations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agent_runs", sa.Column("owner_sub", sa.String(255), nullable=True))
    op.add_column(
        "agent_runs", sa.Column("response_data", postgresql.JSONB(), nullable=True)
    )
    op.create_index(
        "ix_agent_runs_owner_started",
        "agent_runs",
        ["tenant_id", "owner_sub", "knowledge_base_id", "started_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_agent_runs_owner_started", table_name="agent_runs")
    op.drop_column("agent_runs", "response_data")
    op.drop_column("agent_runs", "owner_sub")
