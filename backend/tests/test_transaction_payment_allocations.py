import uuid
from datetime import date
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account
from app.models.budget import Budget
from app.models.category import Category
from app.models.transaction import Transaction
from app.models.transaction_allocation import TransactionAllocation
from app.models.user import User
from app.models.workspace import Workspace


async def _account(
    session: AsyncSession,
    user: User,
    workspace: Workspace,
    name: str,
    *,
    currency: str = "BRL",
    type_: str = "checking",
) -> Account:
    account = Account(
        id=uuid.uuid4(),
        user_id=user.id,
        workspace_id=workspace.id,
        name=name,
        type=type_,
        balance=Decimal("0"),
        currency=currency,
    )
    session.add(account)
    await session.commit()
    return account


async def _category(session: AsyncSession, user: User, workspace: Workspace, name: str) -> Category:
    category = Category(
        id=uuid.uuid4(),
        user_id=user.id,
        workspace_id=workspace.id,
        name=name,
        icon="circle",
        color="#6366F1",
        is_system=False,
    )
    session.add(category)
    await session.commit()
    return category


async def _manual_tx(
    session: AsyncSession,
    user: User,
    workspace: Workspace,
    account: Account,
    *,
    amount: Decimal,
    type_: str,
    description: str = "counterpart",
) -> Transaction:
    tx = Transaction(
        id=uuid.uuid4(),
        user_id=user.id,
        workspace_id=workspace.id,
        account_id=account.id,
        description=description,
        amount=amount,
        currency=account.currency,
        date=date(2026, 5, 15),
        effective_date=date(2026, 5, 15),
        type=type_,
        source="manual",
        status="posted",
    )
    session.add(tx)
    await session.commit()
    return tx


@pytest.mark.asyncio
async def test_create_payment_allocations_with_generated_counterpart(
    client: AsyncClient,
    auth_headers: dict,
    session: AsyncSession,
    test_user: User,
    test_workspace: Workspace,
):
    checking = await _account(session, test_user, test_workspace, "Checking")
    mortgage = await _account(session, test_user, test_workspace, "Mortgage")
    interest = await _category(session, test_user, test_workspace, "Mortgage Interest")
    insurance = await _category(session, test_user, test_workspace, "Insurance")
    legacy_parent_category = await _category(session, test_user, test_workspace, "Legacy Parent Category")

    response = await client.post(
        "/api/transactions",
        headers=auth_headers,
        json={
            "account_id": str(checking.id),
            "description": "Mortgage payment",
            "amount": "1000.00",
            "currency": "BRL",
            "date": "2026-05-15",
            "type": "debit",
            "category_id": str(legacy_parent_category.id),
            "allocations": [
                {"kind": "category", "amount": "600.00", "category_id": str(interest.id)},
                {"kind": "category", "amount": "100.00", "category_id": str(insurance.id)},
                {"kind": "transfer", "amount": "300.00", "transfer_account_id": str(mortgage.id)},
            ],
        },
    )

    assert response.status_code == 201, response.text
    tx = response.json()
    assert len(tx["allocations"]) == 3
    transfer_line = next(a for a in tx["allocations"] if a["kind"] == "transfer")
    assert transfer_line["counterpart_created"] is True
    assert transfer_line["counterpart_transaction_id"]

    counterpart = await session.get(Transaction, uuid.UUID(transfer_line["counterpart_transaction_id"]))
    assert counterpart is not None
    assert counterpart.account_id == mortgage.id
    assert counterpart.type == "credit"
    assert counterpart.amount == Decimal("300.00")
    assert counterpart.category_id is None

    spending = await client.get(
        "/api/dashboard/spending-by-category?month=2026-05-01",
        headers=auth_headers,
    )
    assert spending.status_code == 200, spending.text
    totals = {row["category_id"]: row["total"] for row in spending.json()}
    assert totals[str(interest.id)] == 600.0
    assert totals[str(insurance.id)] == 100.0

    summary = await client.get(
        "/api/dashboard/summary?month=2026-05-01&balance_date=2026-05-31",
        headers=auth_headers,
    )
    assert summary.status_code == 200, summary.text
    assert summary.json()["monthly_expenses"] == 700.0

    tx_list = await client.get(
        "/api/transactions",
        headers=auth_headers,
        params={
            "account_id": str(checking.id),
            "from": "2026-05-01",
            "to": "2026-05-31",
        },
    )
    assert tx_list.status_code == 200, tx_list.text
    assert tx_list.json()["summary"]["expense"] == 700.0
    assert tx_list.json()["summary"]["excluded"] == 300.0

    category_filtered = await client.get(
        "/api/transactions",
        headers=auth_headers,
        params={
            "category_id": str(interest.id),
            "from": "2026-05-01",
            "to": "2026-05-31",
        },
    )
    assert category_filtered.status_code == 200, category_filtered.text
    assert [row["id"] for row in category_filtered.json()["items"]] == [tx["id"]]
    assert category_filtered.json()["summary"]["expense"] == 600.0

    legacy_category_filtered = await client.get(
        "/api/transactions",
        headers=auth_headers,
        params={
            "category_id": str(legacy_parent_category.id),
            "from": "2026-05-01",
            "to": "2026-05-31",
        },
    )
    assert legacy_category_filtered.status_code == 200, legacy_category_filtered.text
    assert legacy_category_filtered.json()["items"] == []
    assert legacy_category_filtered.json()["summary"]["expense"] == 0.0


@pytest.mark.asyncio
async def test_payment_allocations_can_link_existing_counterpart_without_duplication(
    client: AsyncClient,
    auth_headers: dict,
    session: AsyncSession,
    test_user: User,
    test_workspace: Workspace,
):
    checking = await _account(session, test_user, test_workspace, "Checking")
    mortgage = await _account(session, test_user, test_workspace, "Mortgage")
    interest = await _category(session, test_user, test_workspace, "Mortgage Interest")
    counterpart = await _manual_tx(
        session,
        test_user,
        test_workspace,
        mortgage,
        amount=Decimal("300.00"),
        type_="credit",
        description="Principal received",
    )

    response = await client.post(
        "/api/transactions",
        headers=auth_headers,
        json={
            "account_id": str(checking.id),
            "description": "Mortgage payment",
            "amount": "900.00",
            "currency": "BRL",
            "date": "2026-05-15",
            "type": "debit",
            "allocations": [
                {"kind": "category", "amount": "600.00", "category_id": str(interest.id)},
                {
                    "kind": "transfer",
                    "amount": "300.00",
                    "transfer_account_id": str(mortgage.id),
                    "counterpart_transaction_id": str(counterpart.id),
                },
            ],
        },
    )

    assert response.status_code == 201, response.text
    transfer_line = next(a for a in response.json()["allocations"] if a["kind"] == "transfer")
    assert transfer_line["counterpart_created"] is False
    assert transfer_line["counterpart_transaction_id"] == str(counterpart.id)

    rows = (await session.execute(select(Transaction))).scalars().all()
    assert len(rows) == 2


@pytest.mark.asyncio
async def test_payment_allocation_validation_rejects_unbalanced_or_bad_counterparts(
    client: AsyncClient,
    auth_headers: dict,
    session: AsyncSession,
    test_user: User,
    test_workspace: Workspace,
):
    checking = await _account(session, test_user, test_workspace, "Checking")
    mortgage = await _account(session, test_user, test_workspace, "Mortgage")
    interest = await _category(session, test_user, test_workspace, "Mortgage Interest")
    wrong_amount_counterpart = await _manual_tx(
        session,
        test_user,
        test_workspace,
        mortgage,
        amount=Decimal("301.00"),
        type_="credit",
    )

    unbalanced = await client.post(
        "/api/transactions",
        headers=auth_headers,
        json={
            "account_id": str(checking.id),
            "description": "Bad split",
            "amount": "1000.00",
            "currency": "BRL",
            "date": "2026-05-15",
            "type": "debit",
            "allocations": [
                {"kind": "category", "amount": "600.00", "category_id": str(interest.id)},
            ],
        },
    )
    assert unbalanced.status_code == 400
    assert "sum to the transaction amount" in unbalanced.json()["detail"]

    bad_link = await client.post(
        "/api/transactions",
        headers=auth_headers,
        json={
            "account_id": str(checking.id),
            "description": "Bad counterpart",
            "amount": "900.00",
            "currency": "BRL",
            "date": "2026-05-15",
            "type": "debit",
            "allocations": [
                {"kind": "category", "amount": "600.00", "category_id": str(interest.id)},
                {
                    "kind": "transfer",
                    "amount": "300.00",
                    "transfer_account_id": str(mortgage.id),
                    "counterpart_transaction_id": str(wrong_amount_counterpart.id),
                },
            ],
        },
    )
    assert bad_link.status_code == 400
    assert "amount must match" in bad_link.json()["detail"]


@pytest.mark.asyncio
async def test_payment_allocation_candidates_hide_used_counterparts(
    client: AsyncClient,
    auth_headers: dict,
    session: AsyncSession,
    test_user: User,
    test_workspace: Workspace,
):
    checking = await _account(session, test_user, test_workspace, "Checking")
    mortgage = await _account(session, test_user, test_workspace, "Mortgage")
    interest = await _category(session, test_user, test_workspace, "Mortgage Interest")
    parent = await _manual_tx(
        session,
        test_user,
        test_workspace,
        checking,
        amount=Decimal("900.00"),
        type_="debit",
        description="Mortgage payment",
    )
    counterpart = await _manual_tx(
        session,
        test_user,
        test_workspace,
        mortgage,
        amount=Decimal("300.00"),
        type_="credit",
        description="Principal received",
    )

    candidates = await client.get(
        f"/api/transactions/{parent.id}/allocation-candidates",
        headers=auth_headers,
        params={"transfer_account_id": str(mortgage.id), "amount": "300.00"},
    )
    assert candidates.status_code == 200, candidates.text
    assert [row["id"] for row in candidates.json()] == [str(counterpart.id)]

    update = await client.patch(
        f"/api/transactions/{parent.id}",
        headers=auth_headers,
        json={
            "allocations": [
                {"kind": "category", "amount": "600.00", "category_id": str(interest.id)},
                {
                    "kind": "transfer",
                    "amount": "300.00",
                    "transfer_account_id": str(mortgage.id),
                    "counterpart_transaction_id": str(counterpart.id),
                },
            ]
        },
    )
    assert update.status_code == 200, update.text

    candidates_after = await client.get(
        f"/api/transactions/{parent.id}/allocation-candidates",
        headers=auth_headers,
        params={"transfer_account_id": str(mortgage.id), "amount": "300.00"},
    )
    assert candidates_after.status_code == 200, candidates_after.text
    assert candidates_after.json() == []


@pytest.mark.asyncio
async def test_clearing_or_deleting_allocations_removes_generated_counterparts(
    client: AsyncClient,
    auth_headers: dict,
    session: AsyncSession,
    test_user: User,
    test_workspace: Workspace,
):
    checking = await _account(session, test_user, test_workspace, "Checking")
    mortgage = await _account(session, test_user, test_workspace, "Mortgage")
    interest = await _category(session, test_user, test_workspace, "Mortgage Interest")

    created = await client.post(
        "/api/transactions",
        headers=auth_headers,
        json={
            "account_id": str(checking.id),
            "description": "Mortgage payment",
            "amount": "900.00",
            "currency": "BRL",
            "date": "2026-05-15",
            "type": "debit",
            "allocations": [
                {"kind": "category", "amount": "600.00", "category_id": str(interest.id)},
                {"kind": "transfer", "amount": "300.00", "transfer_account_id": str(mortgage.id)},
            ],
        },
    )
    assert created.status_code == 201, created.text
    tx_id = created.json()["id"]
    counterpart_id = next(
        row["counterpart_transaction_id"]
        for row in created.json()["allocations"]
        if row["kind"] == "transfer"
    )

    cleared = await client.patch(
        f"/api/transactions/{tx_id}",
        headers=auth_headers,
        json={"allocations": []},
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["allocations"] == []
    assert await session.get(Transaction, uuid.UUID(counterpart_id)) is None

    recreated = await client.patch(
        f"/api/transactions/{tx_id}",
        headers=auth_headers,
        json={
            "allocations": [
                {"kind": "category", "amount": "600.00", "category_id": str(interest.id)},
                {"kind": "transfer", "amount": "300.00", "transfer_account_id": str(mortgage.id)},
            ]
        },
    )
    assert recreated.status_code == 200, recreated.text
    new_counterpart_id = next(
        row["counterpart_transaction_id"]
        for row in recreated.json()["allocations"]
        if row["kind"] == "transfer"
    )
    assert await session.get(Transaction, uuid.UUID(new_counterpart_id)) is not None

    deleted = await client.delete(f"/api/transactions/{tx_id}", headers=auth_headers)
    assert deleted.status_code == 204, deleted.text
    assert await session.get(Transaction, uuid.UUID(new_counterpart_id)) is None


@pytest.mark.asyncio
async def test_editing_allocated_transaction_requires_allocation_payload_for_sensitive_fields_and_syncs_safe_fields(
    client: AsyncClient,
    auth_headers: dict,
    session: AsyncSession,
    test_user: User,
    test_workspace: Workspace,
):
    checking = await _account(session, test_user, test_workspace, "Checking")
    mortgage = await _account(session, test_user, test_workspace, "Mortgage")
    interest = await _category(session, test_user, test_workspace, "Mortgage Interest")

    created = await client.post(
        "/api/transactions",
        headers=auth_headers,
        json={
            "account_id": str(checking.id),
            "description": "Mortgage payment",
            "amount": "900.00",
            "currency": "BRL",
            "date": "2026-05-15",
            "type": "debit",
            "allocations": [
                {"kind": "category", "amount": "600.00", "category_id": str(interest.id)},
                {"kind": "transfer", "amount": "300.00", "transfer_account_id": str(mortgage.id)},
            ],
        },
    )
    assert created.status_code == 201, created.text
    tx_id = created.json()["id"]
    counterpart_id = next(
        row["counterpart_transaction_id"]
        for row in created.json()["allocations"]
        if row["kind"] == "transfer"
    )

    safe_update = await client.patch(
        f"/api/transactions/{tx_id}",
        headers=auth_headers,
        json={"description": "Mortgage payment adjusted", "date": "2026-05-16"},
    )
    assert safe_update.status_code == 200, safe_update.text
    session.expire_all()
    counterpart = await session.get(Transaction, uuid.UUID(counterpart_id))
    assert counterpart is not None
    assert counterpart.description == "Mortgage payment adjusted"
    assert counterpart.date == date(2026, 5, 16)

    sensitive_update = await client.patch(
        f"/api/transactions/{tx_id}",
        headers=auth_headers,
        json={"amount": "901.00"},
    )
    assert sensitive_update.status_code == 400
    assert "requires allocations" in sensitive_update.json()["detail"]


@pytest.mark.asyncio
async def test_budget_comparison_uses_payment_allocation_category_amounts(
    client: AsyncClient,
    auth_headers: dict,
    session: AsyncSession,
    test_user: User,
    test_workspace: Workspace,
):
    checking = await _account(session, test_user, test_workspace, "Checking")
    mortgage = await _account(session, test_user, test_workspace, "Mortgage")
    interest = await _category(session, test_user, test_workspace, "Mortgage Interest")
    insurance = await _category(session, test_user, test_workspace, "Insurance")
    session.add_all([
        Budget(
            id=uuid.uuid4(),
            user_id=test_user.id,
            workspace_id=test_workspace.id,
            category_id=interest.id,
            amount=Decimal("800.00"),
            month=date(2026, 5, 1),
            is_recurring=False,
        ),
        Budget(
            id=uuid.uuid4(),
            user_id=test_user.id,
            workspace_id=test_workspace.id,
            category_id=insurance.id,
            amount=Decimal("200.00"),
            month=date(2026, 5, 1),
            is_recurring=False,
        ),
    ])
    await session.commit()

    response = await client.post(
        "/api/transactions",
        headers=auth_headers,
        json={
            "account_id": str(checking.id),
            "description": "Mortgage payment",
            "amount": "1000.00",
            "currency": "BRL",
            "date": "2026-05-15",
            "type": "debit",
            "allocations": [
                {"kind": "category", "amount": "600.00", "category_id": str(interest.id)},
                {"kind": "category", "amount": "100.00", "category_id": str(insurance.id)},
                {"kind": "transfer", "amount": "300.00", "transfer_account_id": str(mortgage.id)},
            ],
        },
    )
    assert response.status_code == 201, response.text

    comparison = await client.get(
        "/api/budgets/comparison?month=2026-05-01",
        headers=auth_headers,
    )
    assert comparison.status_code == 200, comparison.text
    actuals = {row["category_id"]: row["actual_amount"] for row in comparison.json()}
    assert Decimal(str(actuals[str(interest.id)])) == Decimal("600.00")
    assert Decimal(str(actuals[str(insurance.id)])) == Decimal("100.00")

    allocation_rows = (await session.execute(select(TransactionAllocation))).scalars().all()
    assert len(allocation_rows) == 3


async def _create_group_for_bulk(client: AsyncClient, auth_headers: dict) -> str:
    group = await client.post(
        "/api/groups",
        headers=auth_headers,
        json={"name": "Mortgage group", "kind": "social", "default_currency": "BRL"},
    )
    assert group.status_code == 201, group.text
    group_id = group.json()["id"]
    for name, is_self in (("Me", True), ("Partner", False)):
        member = await client.post(
            f"/api/groups/{group_id}/members",
            headers=auth_headers,
            json={"name": name, "is_self": is_self},
        )
        assert member.status_code == 201, member.text
    return group_id


@pytest.mark.asyncio
async def test_payment_allocation_counterparts_cannot_be_mutated_directly_or_used_as_transfers(
    client: AsyncClient,
    auth_headers: dict,
    session: AsyncSession,
    test_user: User,
    test_workspace: Workspace,
):
    checking = await _account(session, test_user, test_workspace, "Checking")
    mortgage = await _account(session, test_user, test_workspace, "Mortgage")
    savings = await _account(session, test_user, test_workspace, "Savings")
    interest = await _category(session, test_user, test_workspace, "Mortgage Interest")

    created = await client.post(
        "/api/transactions",
        headers=auth_headers,
        json={
            "account_id": str(checking.id),
            "description": "Mortgage payment",
            "amount": "900.00",
            "currency": "BRL",
            "date": "2026-05-15",
            "type": "debit",
            "allocations": [
                {"kind": "category", "amount": "600.00", "category_id": str(interest.id)},
                {"kind": "transfer", "amount": "300.00", "transfer_account_id": str(mortgage.id)},
            ],
        },
    )
    assert created.status_code == 201, created.text
    parent_id = created.json()["id"]
    counterpart_id = next(
        row["counterpart_transaction_id"]
        for row in created.json()["allocations"]
        if row["kind"] == "transfer"
    )

    direct_edit = await client.patch(
        f"/api/transactions/{counterpart_id}",
        headers=auth_headers,
        json={"description": "Edited directly"},
    )
    assert direct_edit.status_code == 400
    assert "counterparts cannot be edited" in direct_edit.json()["detail"]

    direct_delete = await client.delete(f"/api/transactions/{counterpart_id}", headers=auth_headers)
    assert direct_delete.status_code == 400
    assert "counterparts cannot be deleted" in direct_delete.json()["detail"]

    make_transfer = await client.post(
        f"/api/transactions/{parent_id}/create-counterpart",
        headers=auth_headers,
        json={"to_account_id": str(savings.id)},
    )
    assert make_transfer.status_code == 400
    assert "Payment-split transactions" in make_transfer.json()["detail"]

    candidates = await client.get(
        f"/api/transactions/{parent_id}/transfer-candidates",
        headers=auth_headers,
    )
    assert candidates.status_code == 200
    assert candidates.json() == []


@pytest.mark.asyncio
async def test_payment_allocation_rejects_duplicate_counterpart_in_single_payload(
    client: AsyncClient,
    auth_headers: dict,
    session: AsyncSession,
    test_user: User,
    test_workspace: Workspace,
):
    checking = await _account(session, test_user, test_workspace, "Checking")
    mortgage = await _account(session, test_user, test_workspace, "Mortgage")
    interest = await _category(session, test_user, test_workspace, "Mortgage Interest")
    counterpart = await _manual_tx(
        session,
        test_user,
        test_workspace,
        mortgage,
        amount=Decimal("150.00"),
        type_="credit",
        description="Principal received",
    )

    response = await client.post(
        "/api/transactions",
        headers=auth_headers,
        json={
            "account_id": str(checking.id),
            "description": "Bad duplicate counterpart",
            "amount": "600.00",
            "currency": "BRL",
            "date": "2026-05-15",
            "type": "debit",
            "allocations": [
                {"kind": "category", "amount": "300.00", "category_id": str(interest.id)},
                {
                    "kind": "transfer",
                    "amount": "150.00",
                    "transfer_account_id": str(mortgage.id),
                    "counterpart_transaction_id": str(counterpart.id),
                },
                {
                    "kind": "transfer",
                    "amount": "150.00",
                    "transfer_account_id": str(mortgage.id),
                    "counterpart_transaction_id": str(counterpart.id),
                },
            ],
        },
    )
    assert response.status_code == 400
    assert "more than once" in response.json()["detail"]


@pytest.mark.asyncio
async def test_bulk_group_split_and_pending_categorization_skip_payment_allocations(
    client: AsyncClient,
    auth_headers: dict,
    session: AsyncSession,
    test_user: User,
    test_workspace: Workspace,
):
    checking = await _account(session, test_user, test_workspace, "Checking")
    mortgage = await _account(session, test_user, test_workspace, "Mortgage")
    interest = await _category(session, test_user, test_workspace, "Mortgage Interest")
    group_id = await _create_group_for_bulk(client, auth_headers)

    allocated = await client.post(
        "/api/transactions",
        headers=auth_headers,
        json={
            "account_id": str(checking.id),
            "description": "Mortgage payment",
            "amount": "900.00",
            "currency": "BRL",
            "date": "2026-05-15",
            "type": "debit",
            "allocations": [
                {"kind": "category", "amount": "600.00", "category_id": str(interest.id)},
                {"kind": "transfer", "amount": "300.00", "transfer_account_id": str(mortgage.id)},
            ],
        },
    )
    assert allocated.status_code == 201, allocated.text
    fresh = await _manual_tx(
        session,
        test_user,
        test_workspace,
        checking,
        amount=Decimal("40.00"),
        type_="debit",
        description="Dinner",
    )

    bulk = await client.patch(
        "/api/transactions/bulk-add-to-group",
        headers=auth_headers,
        json={"transaction_ids": [allocated.json()["id"], str(fresh.id)], "group_id": group_id},
    )
    assert bulk.status_code == 200, bulk.text
    assert bulk.json() == {"updated": 1, "skipped": 1}

    allocated_full = await client.get(
        f"/api/transactions/{allocated.json()['id']}",
        headers=auth_headers,
    )
    assert allocated_full.status_code == 200, allocated_full.text
    assert allocated_full.json()["splits"] == []
    assert len(allocated_full.json()["allocations"]) == 2

    summary = await client.get(
        "/api/dashboard/summary?month=2026-05-01&balance_date=2026-05-31",
        headers=auth_headers,
    )
    assert summary.status_code == 200, summary.text
    # The allocated parent and its generated transfer counterpart are already
    # represented by allocation lines, so they must not inflate categorization
    # work. Only the fresh dinner transaction remains pending.
    assert summary.json()["pending_categorization"] == 1
