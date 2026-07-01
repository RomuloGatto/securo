import uuid
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.account import Account
from app.models.bank_connection import BankConnection
from app.models.category import Category
from app.models.transaction import Transaction
from app.models.transaction_allocation import TransactionAllocation
from app.models.transaction_split import TransactionSplit
from app.schemas.transaction_allocation import TransactionAllocationInput
from app.services.credit_card_service import apply_effective_date
from app.services.fx_rate_service import stamp_primary_amount

_CENT = Decimal("0.01")


def _quantize(amount: Decimal) -> Decimal:
    return Decimal(str(amount)).copy_abs().quantize(_CENT, rounding=ROUND_HALF_UP)


def _opposite_type(tx_type: str) -> str:
    return "credit" if tx_type == "debit" else "debit"


async def _workspace_account(
    session: AsyncSession,
    account_id: uuid.UUID,
    workspace_id: uuid.UUID,
) -> Optional[Account]:
    result = await session.execute(
        select(Account)
        .outerjoin(BankConnection)
        .where(
            Account.id == account_id,
            or_(Account.workspace_id == workspace_id, BankConnection.workspace_id == workspace_id),
        )
    )
    return result.scalar_one_or_none()


async def _workspace_category(
    session: AsyncSession,
    category_id: uuid.UUID,
    workspace_id: uuid.UUID,
) -> Optional[Category]:
    result = await session.execute(
        select(Category).where(Category.id == category_id, Category.workspace_id == workspace_id)
    )
    return result.scalar_one_or_none()


async def _counterpart_already_used(
    session: AsyncSession,
    tx_id: uuid.UUID,
    *,
    excluding_transaction_id: Optional[uuid.UUID] = None,
) -> bool:
    filters = [TransactionAllocation.counterpart_transaction_id == tx_id]
    if excluding_transaction_id is not None:
        filters.append(TransactionAllocation.transaction_id != excluding_transaction_id)
    result = await session.execute(select(TransactionAllocation.id).where(*filters).limit(1))
    return result.scalar_one_or_none() is not None


async def _transaction_has_allocations(session: AsyncSession, tx_id: uuid.UUID) -> bool:
    result = await session.execute(
        select(TransactionAllocation.id)
        .where(TransactionAllocation.transaction_id == tx_id)
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


async def get_counterpart_allocation(
    session: AsyncSession,
    tx_id: uuid.UUID,
) -> Optional[TransactionAllocation]:
    result = await session.execute(
        select(TransactionAllocation)
        .where(TransactionAllocation.counterpart_transaction_id == tx_id)
        .limit(1)
    )
    return result.scalar_one_or_none()


async def transaction_has_allocation_role(session: AsyncSession, tx_id: uuid.UUID) -> bool:
    if await _transaction_has_allocations(session, tx_id):
        return True
    return await get_counterpart_allocation(session, tx_id) is not None


async def ensure_not_allocation_counterpart(
    session: AsyncSession,
    tx_id: uuid.UUID,
    *,
    action: str,
) -> None:
    if await get_counterpart_allocation(session, tx_id) is not None:
        raise ValueError(f"Payment allocation counterparts cannot be {action} directly")


async def _transaction_has_group_splits(session: AsyncSession, tx_id: uuid.UUID) -> bool:
    result = await session.execute(
        select(TransactionSplit.id)
        .where(TransactionSplit.transaction_id == tx_id)
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


async def _delete_generated_counterparts(
    session: AsyncSession,
    transaction_id: uuid.UUID,
) -> None:
    result = await session.execute(
        select(TransactionAllocation)
        .where(TransactionAllocation.transaction_id == transaction_id)
        .options(selectinload(TransactionAllocation.counterpart_transaction))
    )
    for allocation in result.scalars().all():
        if allocation.counterpart_created and allocation.counterpart_transaction is not None:
            await session.delete(allocation.counterpart_transaction)


async def _create_counterpart(
    session: AsyncSession,
    parent: Transaction,
    target_account: Account,
    amount: Decimal,
    user_id: uuid.UUID,
    notes: Optional[str],
) -> Transaction:
    counterpart = Transaction(
        user_id=user_id,
        workspace_id=parent.workspace_id,
        account_id=target_account.id,
        category_id=None,
        description=parent.description,
        amount=amount,
        currency=target_account.currency,
        date=parent.date,
        type=_opposite_type(parent.type),
        source="manual",
        status=parent.status,
        notes=notes,
        raw_data={"allocation_counterpart_for": str(parent.id)},
    )
    apply_effective_date(counterpart, target_account)
    session.add(counterpart)
    await session.flush()
    await stamp_primary_amount(session, user_id, counterpart)
    return counterpart


async def _validate_linked_counterpart(
    session: AsyncSession,
    parent: Transaction,
    target_account: Account,
    amount: Decimal,
    counterpart_id: uuid.UUID,
) -> Transaction:
    candidate = await session.get(Transaction, counterpart_id)
    if candidate is None or candidate.workspace_id != parent.workspace_id:
        raise ValueError("Counterpart transaction not found")
    if candidate.id == parent.id:
        raise ValueError("Counterpart transaction cannot be the parent transaction")
    if candidate.account_id != target_account.id:
        raise ValueError("Counterpart transaction must belong to the selected transfer account")
    if candidate.type != _opposite_type(parent.type):
        raise ValueError("Counterpart transaction must have the opposite transaction type")
    if _quantize(candidate.amount) != amount:
        raise ValueError("Counterpart transaction amount must match the transfer allocation")
    if candidate.currency != parent.currency:
        raise ValueError("Counterpart transaction currency must match the parent transaction")
    if candidate.source == "opening_balance" or candidate.is_ignored:
        raise ValueError("Counterpart transaction cannot be opening-balance or ignored")
    if await _transaction_has_allocations(session, candidate.id):
        raise ValueError("Counterpart transaction already has payment allocations")
    if await _transaction_has_group_splits(session, candidate.id):
        raise ValueError("Counterpart transaction already has group splits")
    if candidate.transfer_pair_id is not None:
        raise ValueError("Counterpart transaction is already linked as a transfer")
    if await _counterpart_already_used(session, candidate.id, excluding_transaction_id=parent.id):
        raise ValueError("Counterpart transaction is already linked to another allocation")
    return candidate


async def sync_generated_counterparts(
    session: AsyncSession,
    transaction: Transaction,
    user_id: uuid.UUID,
) -> None:
    """Keep generated counterpart rows aligned after safe parent edits.

    Amount/currency/account/type edits require a full allocation replacement;
    this helper only mirrors descriptive/date/status fields for existing
    generated counterparts.
    """
    result = await session.execute(
        select(TransactionAllocation)
        .where(
            TransactionAllocation.transaction_id == transaction.id,
            TransactionAllocation.counterpart_created.is_(True),
        )
        .options(
            selectinload(TransactionAllocation.counterpart_transaction),
            selectinload(TransactionAllocation.transfer_account),
        )
    )
    for allocation in result.scalars().all():
        counterpart = allocation.counterpart_transaction
        if counterpart is None:
            continue
        counterpart.description = transaction.description
        counterpart.date = transaction.date
        counterpart.status = transaction.status
        counterpart.amount = allocation.amount
        counterpart.type = _opposite_type(transaction.type)
        if allocation.transfer_account is not None:
            counterpart.currency = allocation.transfer_account.currency
            apply_effective_date(counterpart, allocation.transfer_account)
        await stamp_primary_amount(session, user_id, counterpart)


async def replace_allocations(
    session: AsyncSession,
    transaction: Transaction,
    payload: Optional[list[TransactionAllocationInput]],
    user_id: uuid.UUID,
) -> None:
    """Replace category/transfer allocations for a transaction.

    Missing payload means untouched. Empty payload clears allocations and any
    generated counterparts. Linked existing counterpart transactions are left
    intact when their allocation is removed.
    """
    if payload is None:
        return

    if payload:
        if transaction.transfer_pair_id is not None:
            raise ValueError("Payment allocations cannot be added to transfer transactions")
        if await get_counterpart_allocation(session, transaction.id) is not None:
            raise ValueError("Payment allocation counterparts cannot have their own allocations")

    await _delete_generated_counterparts(session, transaction.id)
    await session.execute(
        delete(TransactionAllocation).where(TransactionAllocation.transaction_id == transaction.id)
    )

    if not payload:
        return

    parent_amount = _quantize(transaction.amount)
    line_amounts = [_quantize(item.amount) for item in payload]
    if sum(line_amounts, Decimal("0.00")) != parent_amount:
        raise ValueError("Allocation amounts must sum to the transaction amount")

    parent_account = await _workspace_account(session, transaction.account_id, transaction.workspace_id)
    if parent_account is None:
        raise ValueError("Transaction account not found")

    seen_counterpart_ids: set[uuid.UUID] = set()

    for index, item in enumerate(payload):
        amount = line_amounts[index]
        category_id = None
        transfer_account_id = None
        counterpart_id = None
        counterpart_created = False

        if item.kind == "category":
            if item.category_id is None:
                raise ValueError("category_id is required for category allocations")
            category = await _workspace_category(session, item.category_id, transaction.workspace_id)
            if category is None:
                raise ValueError("Allocation category not found")
            category_id = category.id
        elif item.kind == "transfer":
            if item.transfer_account_id is None:
                raise ValueError("transfer_account_id is required for transfer allocations")
            target_account = await _workspace_account(
                session, item.transfer_account_id, transaction.workspace_id
            )
            if target_account is None:
                raise ValueError("Transfer account not found")
            if target_account.id == parent_account.id:
                raise ValueError("Transfer allocation cannot target the parent account")
            if target_account.currency != transaction.currency:
                raise ValueError("Transfer allocation currency must match the parent transaction currency")
            transfer_account_id = target_account.id
            if item.counterpart_transaction_id:
                if item.counterpart_transaction_id in seen_counterpart_ids:
                    raise ValueError("Counterpart transaction is used more than once in this allocation")
                seen_counterpart_ids.add(item.counterpart_transaction_id)
                counterpart = await _validate_linked_counterpart(
                    session, transaction, target_account, amount, item.counterpart_transaction_id
                )
                counterpart_id = counterpart.id
            else:
                counterpart = await _create_counterpart(
                    session, transaction, target_account, amount, user_id, item.notes
                )
                counterpart_id = counterpart.id
                counterpart_created = True
        else:
            raise ValueError("Unknown allocation kind")

        session.add(
            TransactionAllocation(
                workspace_id=transaction.workspace_id,
                transaction_id=transaction.id,
                kind=item.kind,
                amount=amount,
                category_id=category_id,
                transfer_account_id=transfer_account_id,
                counterpart_transaction_id=counterpart_id,
                counterpart_created=counterpart_created,
                notes=item.notes,
                sort_order=index,
            )
        )


async def get_transfer_allocation_candidates(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    parent_transaction_id: uuid.UUID,
    transfer_account_id: uuid.UUID,
    amount: Decimal,
    *,
    limit: int = 10,
    window_days: int = 30,
) -> list[Transaction]:
    parent = await session.get(Transaction, parent_transaction_id)
    if parent is None or parent.workspace_id != workspace_id:
        return []
    target_account = await _workspace_account(session, transfer_account_id, workspace_id)
    if target_account is None or target_account.currency != parent.currency:
        return []

    amount = _quantize(amount)
    start = parent.date - timedelta(days=window_days)
    end = parent.date + timedelta(days=window_days)
    used_counterparts = select(TransactionAllocation.counterpart_transaction_id).where(
        TransactionAllocation.counterpart_transaction_id.isnot(None)
    )
    allocated_transactions = select(TransactionAllocation.transaction_id)
    split_transactions = select(TransactionSplit.transaction_id)
    result = await session.execute(
        select(Transaction)
        .options(
            selectinload(Transaction.category),
            selectinload(Transaction.payee_entity),
            selectinload(Transaction.splits),
            selectinload(Transaction.allocations),
        )
        .where(
            Transaction.workspace_id == workspace_id,
            Transaction.id != parent.id,
            Transaction.account_id == transfer_account_id,
            Transaction.type == _opposite_type(parent.type),
            Transaction.currency == parent.currency,
            func.abs(Transaction.amount) == amount,
            Transaction.date >= start,
            Transaction.date <= end,
            Transaction.transfer_pair_id.is_(None),
            Transaction.source != "opening_balance",
            Transaction.is_ignored.is_(False),
            Transaction.id.not_in(used_counterparts),
            Transaction.id.not_in(allocated_transactions),
            Transaction.id.not_in(split_transactions),
        )
        .order_by(Transaction.date.desc(), Transaction.id)
        .limit(max(limit * 5, 50))
    )
    candidates = list(result.scalars().all())
    candidates.sort(
        key=lambda tx: (
            abs((tx.date - parent.date).days),
            0 if (tx.description or "").strip().lower() == (parent.description or "").strip().lower() else 1,
            tx.date,
        )
    )
    return candidates[:limit]
