import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.account import Account
    from app.models.category import Category
    from app.models.transaction import Transaction


class TransactionAllocation(Base):
    """A category/transfer line inside a single bank transaction.

    This is intentionally separate from TransactionSplit, which models
    Splitwise-style sharing across people/groups. Allocations break one
    payment into category and account-transfer legs.
    """

    __tablename__ = "transaction_allocations"
    __table_args__ = (
        CheckConstraint("kind IN ('category', 'transfer')", name="ck_transaction_allocations_kind"),
        CheckConstraint("amount > 0", name="ck_transaction_allocations_amount_positive"),
        UniqueConstraint(
            "counterpart_transaction_id",
            name="uq_transaction_allocations_counterpart_transaction_id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    transaction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("transactions.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(20))  # category, transfer
    amount: Mapped[Decimal] = mapped_column(Numeric(precision=15, scale=2))
    category_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("categories.id", ondelete="SET NULL"), nullable=True
    )
    transfer_account_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True
    )
    counterpart_transaction_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("transactions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    counterpart_created: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    notes: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    transaction: Mapped["Transaction"] = relationship(
        back_populates="allocations", foreign_keys=[transaction_id]
    )
    category: Mapped[Optional["Category"]] = relationship()
    transfer_account: Mapped[Optional["Account"]] = relationship(foreign_keys=[transfer_account_id])
    counterpart_transaction: Mapped[Optional["Transaction"]] = relationship(
        foreign_keys=[counterpart_transaction_id]
    )
