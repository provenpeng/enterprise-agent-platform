"""Create tenant-scoped synthetic orders and refund attempts.

Revision ID: 0009_demo_business
Revises: 0008_tenants
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "0009_demo_business"
down_revision = "0008_tenants"
branch_labels = None
depends_on = None

payment_status = postgresql.ENUM(
    "PAID", "UNPAID", "REFUNDED", name="demo_payment_status", create_type=False
)
refund_status = postgresql.ENUM(
    "PENDING", "FAILED", "SUCCEEDED", name="demo_refund_status", create_type=False
)


def upgrade() -> None:
    bind = op.get_bind()
    payment_status.create(bind, checkfirst=True)
    refund_status.create(bind, checkfirst=True)
    op.create_table(
        "demo_orders",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("order_id", sa.String(64), nullable=False),
        sa.Column("payment_status", payment_status, nullable=False),
        sa.Column("total_amount_cents", sa.Integer(), nullable=False),
        sa.Column("refundable_amount_cents", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("tenant_id", "order_id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.CheckConstraint(
            "total_amount_cents >= 0", name="ck_demo_orders_total_nonnegative"
        ),
        sa.CheckConstraint(
            "refundable_amount_cents >= 0", name="ck_demo_orders_refundable_nonnegative"
        ),
        sa.CheckConstraint(
            "refundable_amount_cents <= total_amount_cents",
            name="ck_demo_orders_refundable_not_above_total",
        ),
    )
    op.create_table(
        "demo_refund_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("order_id", sa.String(64), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("status", refund_status, nullable=False),
        sa.Column("reason_code", sa.String(64), nullable=True),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "order_id"],
            ["demo_orders.tenant_id", "demo_orders.order_id"],
            ondelete="CASCADE",
            name="fk_demo_refund_attempts_order",
        ),
        sa.CheckConstraint(
            "attempt_number > 0", name="ck_demo_refund_attempt_number_positive"
        ),
        sa.CheckConstraint(
            "amount_cents > 0", name="ck_demo_refund_attempt_amount_positive"
        ),
        sa.CheckConstraint(
            "status != 'FAILED' OR reason_code IS NOT NULL",
            name="ck_demo_refund_failed_reason",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "order_id",
            "attempt_number",
            name="uq_demo_refund_attempt_number",
        ),
    )


def downgrade() -> None:
    op.drop_table("demo_refund_attempts")
    op.drop_table("demo_orders")
    refund_status.drop(op.get_bind(), checkfirst=True)
    payment_status.drop(op.get_bind(), checkfirst=True)
