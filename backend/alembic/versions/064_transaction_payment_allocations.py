"""add transaction payment allocations

Revision ID: 064
Revises: 063
Create Date: 2026-07-01
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "064"
down_revision: Union[str, None] = "063"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _uuid_type():
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        return postgresql.UUID(as_uuid=True)
    return sa.String(36)


def upgrade() -> None:
    uuid_type = _uuid_type()
    op.create_table(
        "transaction_allocations",
        sa.Column("id", uuid_type, primary_key=True, nullable=False),
        sa.Column("workspace_id", uuid_type, sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("transaction_id", uuid_type, sa.ForeignKey("transactions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("amount", sa.Numeric(precision=15, scale=2), nullable=False),
        sa.Column("category_id", uuid_type, sa.ForeignKey("categories.id", ondelete="SET NULL"), nullable=True),
        sa.Column("transfer_account_id", uuid_type, sa.ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True),
        sa.Column("counterpart_transaction_id", uuid_type, sa.ForeignKey("transactions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("counterpart_created", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("notes", sa.String(length=500), nullable=True),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("kind IN ('category', 'transfer')", name="ck_transaction_allocations_kind"),
        sa.CheckConstraint("amount > 0", name="ck_transaction_allocations_amount_positive"),
        sa.UniqueConstraint(
            "counterpart_transaction_id",
            name="uq_transaction_allocations_counterpart_transaction_id",
        ),
    )
    op.create_index("ix_transaction_allocations_workspace_id", "transaction_allocations", ["workspace_id"])
    op.create_index("ix_transaction_allocations_transaction_id", "transaction_allocations", ["transaction_id"])
    op.create_index("ix_transaction_allocations_counterpart_transaction_id", "transaction_allocations", ["counterpart_transaction_id"])


def downgrade() -> None:
    op.drop_index("ix_transaction_allocations_counterpart_transaction_id", table_name="transaction_allocations")
    op.drop_index("ix_transaction_allocations_transaction_id", table_name="transaction_allocations")
    op.drop_index("ix_transaction_allocations_workspace_id", table_name="transaction_allocations")
    op.drop_table("transaction_allocations")
