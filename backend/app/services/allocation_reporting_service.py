import uuid
from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account
from app.models.category import Category
from app.models.transaction import Transaction
from app.models.transaction_allocation import TransactionAllocation


def allocation_report_date_col(use_effective_date: bool):
    base = Transaction.effective_date if use_effective_date else Transaction.date
    return func.coalesce(Transaction.effective_bill_date, base)


def allocation_category_filter():
    return and_(
        TransactionAllocation.kind == "category",
        Transaction.is_ignored.is_(False),
        Transaction.transfer_pair_id.is_(None),
        Transaction.source != "opening_balance",
        or_(
            TransactionAllocation.category_id.is_(None),
            TransactionAllocation.category_id.not_in(
                select(Category.id).where(
                    or_(
                        Category.treat_as_transfer.is_(True),
                        Category.is_ignored.is_(True),
                    )
                )
            ),
        ),
    )


def proportional_allocation_amount_expr(
    tx_amount,
    tx_amount_primary,
    allocation_amount=TransactionAllocation.amount,
):
    """Scale an allocation line into the same currency as amount_primary.

    Allocation rows store native transaction-currency amounts. When a parent
    transaction already has a primary-currency amount, multiply each line by
    the parent's primary/native ratio so transaction-list/account summaries do
    not count the whole converted parent for every line.
    """
    return case(
        (
            func.abs(tx_amount) > 0,
            allocation_amount
            * (func.abs(func.coalesce(tx_amount_primary, tx_amount)) / func.abs(tx_amount)),
        ),
        else_=allocation_amount,
    )


async def allocation_pnl_totals(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    start: date,
    end: date,
    *,
    use_effective_date: bool = False,
    primary_currency: Optional[str] = None,
    account_ids: Optional[list[uuid.UUID]] = None,
) -> tuple[float, float]:
    date_col = allocation_report_date_col(use_effective_date)
    acct_filter = [Transaction.account_id.in_(account_ids)] if account_ids is not None else []
    amount_expr = (
        proportional_allocation_amount_expr(Transaction.amount, Transaction.amount_primary)
        if primary_currency is not None
        else TransactionAllocation.amount
    )
    result = await session.execute(
        select(
            Transaction.currency,
            Transaction.type,
            func.sum(amount_expr),
        )
        .select_from(TransactionAllocation)
        .join(Transaction, TransactionAllocation.transaction_id == Transaction.id)
        .join(Account, Transaction.account_id == Account.id)
        .where(
            Transaction.workspace_id == workspace_id,
            Account.is_closed == False,
            date_col >= start,
            date_col < end,
            allocation_category_filter(),
            *acct_filter,
        )
        .group_by(Transaction.currency, Transaction.type)
    )

    income = 0.0
    expenses = 0.0
    for currency, tx_type, total in result.all():
        if not total:
            continue
        amount = Decimal(str(total))
        if tx_type == "credit":
            income += float(amount)
        else:
            expenses += float(amount)
    return income, expenses


async def allocation_spending_by_category(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    start: date,
    end: date,
    *,
    use_effective_date: bool = False,
    primary_currency: Optional[str] = None,
    account_ids: Optional[list[uuid.UUID]] = None,
) -> dict[uuid.UUID | None, Decimal]:
    date_col = allocation_report_date_col(use_effective_date)
    acct_filter = [Transaction.account_id.in_(account_ids)] if account_ids is not None else []
    amount_expr = (
        proportional_allocation_amount_expr(Transaction.amount, Transaction.amount_primary)
        if primary_currency is not None
        else TransactionAllocation.amount
    )
    result = await session.execute(
        select(
            TransactionAllocation.category_id,
            Transaction.currency,
            func.sum(amount_expr),
        )
        .select_from(TransactionAllocation)
        .join(Transaction, TransactionAllocation.transaction_id == Transaction.id)
        .join(Account, Transaction.account_id == Account.id)
        .where(
            Transaction.workspace_id == workspace_id,
            Account.is_closed == False,
            Transaction.type == "debit",
            date_col >= start,
            date_col < end,
            allocation_category_filter(),
            *acct_filter,
        )
        .group_by(TransactionAllocation.category_id, Transaction.currency)
    )

    out: dict[uuid.UUID | None, Decimal] = {}
    for cat_id, currency, total in result.all():
        if not total:
            continue
        amount = Decimal(str(total))
        out[cat_id] = out.get(cat_id, Decimal("0")) + amount
    return out
