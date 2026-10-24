import io
import json
import uuid
import zipfile
from datetime import date
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account
from app.models.invoice import Invoice, InvoiceLine, InvoiceSettings
from app.models.invoice_attachment import InvoiceAttachment
from app.models.product import Product, ProductPrice
from app.models.transaction import Transaction
from app.models.workspace import Workspace, WorkspaceMember
from app.providers import get_storage_provider
from app.services import backup_service, invoice_logo_service


@pytest.fixture
def backup_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(backup_service, "BACKUP_STORAGE_PATH", tmp_path)
    yield tmp_path


@pytest.mark.asyncio
async def test_backup_preview_upload_requires_auth(client: AsyncClient):
    response = await client.post(
        "/api/backups/preview-upload",
        files={"file": ("backup.zip", b"not-a-zip", "application/zip")},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_viewer_can_preview_backup_upload(client: AsyncClient, viewer_auth_headers):
    response = await client.post(
        "/api/backups/preview-upload",
        headers=viewer_auth_headers,
        files={"file": ("backup.zip", b"not-a-zip", "application/zip")},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_viewer_cannot_run_stored_backup(client: AsyncClient, viewer_auth_headers):
    response = await client.post(
        "/api/backups/run",
        headers=viewer_auth_headers,
        json={"content": "both"},
    )
    assert response.status_code == 403
    assert "read-only" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_backup_config_roundtrip(client: AsyncClient, auth_headers, backup_dir):
    default_resp = await client.get("/api/backups/config", headers=auth_headers)
    assert default_resp.status_code == 200
    assert default_resp.json()["scheduled_enabled"] is False
    assert "destination_path" not in default_resp.json()

    update_resp = await client.put(
        "/api/backups/config",
        json={
            "scheduled_enabled": True,
            "schedule": "weekly",
            "content": "configuration",
            "retention_count": 3,
            "retention_days": 30,
        },
        headers=auth_headers,
    )
    assert update_resp.status_code == 200
    body = update_resp.json()
    assert body["scheduled_enabled"] is True
    assert body["schedule"] == "weekly"
    assert body["content"] == "configuration"
    assert body["retention_count"] == 3
    assert body["retention_days"] == 30

    rejected_resp = await client.put(
        "/api/backups/config",
        json={"destination_path": "/tmp/should-not-be-configurable"},
        headers=auth_headers,
    )
    assert rejected_resp.status_code == 422


@pytest.mark.asyncio
async def test_run_list_preview_and_download_stored_backup(
    client: AsyncClient,
    auth_headers,
    backup_dir,
    test_account,
    test_transactions,
):
    run_resp = await client.post(
        "/api/backups/run",
        json={"content": "both"},
        headers=auth_headers,
    )
    assert run_resp.status_code == 200, run_resp.text
    item = run_resp.json()
    assert item["id"].startswith("securo-backup-")
    assert item["entity_counts"]["accounts"] == 1
    assert item["entity_counts"]["transactions"] == len(test_transactions)

    list_resp = await client.get("/api/backups", headers=auth_headers)
    assert list_resp.status_code == 200
    assert [b["id"] for b in list_resp.json()] == [item["id"]]

    preview_resp = await client.get(f"/api/backups/{item['id']}/preview", headers=auth_headers)
    assert preview_resp.status_code == 200
    assert preview_resp.json()["valid"] is True
    assert preview_resp.json()["content"] == "both"

    download_resp = await client.get(f"/api/backups/{item['id']}/download", headers=auth_headers)
    assert download_resp.status_code == 200
    with zipfile.ZipFile(io.BytesIO(download_resp.content)) as zf:
        metadata = json.loads(zf.read("metadata.json"))
        assert metadata["content"] == "both"
        assert "transactions.json" in zf.namelist()


@pytest.mark.asyncio
async def test_preview_uploaded_backup(client: AsyncClient, auth_headers, test_account):
    export_resp = await client.get("/api/export/backup?content=data", headers=auth_headers)
    assert export_resp.status_code == 200

    preview_resp = await client.post(
        "/api/backups/preview-upload",
        files={"file": ("backup.zip", export_resp.content, "application/zip")},
        headers=auth_headers,
    )
    assert preview_resp.status_code == 200
    body = preview_resp.json()
    assert body["valid"] is True
    assert body["content"] == "data"
    assert body["entity_counts"]["accounts"] == 1


@pytest.mark.asyncio
async def test_restore_upload_creates_new_workspace_without_bank_connection(
    client: AsyncClient,
    auth_headers,
    session: AsyncSession,
    test_workspace: Workspace,
    test_account,
    test_transactions,
):
    export_resp = await client.get("/api/export/backup?content=data", headers=auth_headers)
    assert export_resp.status_code == 200

    restore_resp = await client.post(
        "/api/backups/restore-upload",
        files={"file": ("backup.zip", export_resp.content, "application/zip")},
        data={"content": "data", "mode": "new_workspace"},
        headers=auth_headers,
    )
    assert restore_resp.status_code == 200, restore_resp.text
    body = restore_resp.json()
    restored_workspace_id = uuid.UUID(body["workspace_id"])
    assert body["mode"] == "new_workspace"
    assert body["workspace_name"].endswith("(restored)")
    assert restored_workspace_id != test_workspace.id

    account_count = await session.scalar(
        select(func.count())
        .select_from(Account)
        .where(Account.workspace_id == restored_workspace_id)
    )
    tx_count = await session.scalar(
        select(func.count())
        .select_from(Transaction)
        .where(Transaction.workspace_id == restored_workspace_id)
    )
    assert account_count == 1
    assert tx_count == len(test_transactions)

    restored_account = (
        await session.execute(select(Account).where(Account.workspace_id == restored_workspace_id))
    ).scalar_one()
    assert restored_account.connection_id is None

    membership_count = await session.scalar(
        select(func.count())
        .select_from(WorkspaceMember)
        .where(WorkspaceMember.workspace_id == restored_workspace_id)
    )
    assert membership_count == 1


@pytest.mark.asyncio
async def test_restore_stored_backup_to_current_workspace_requires_confirmation_then_restores(
    client: AsyncClient,
    auth_headers,
    backup_dir,
    session: AsyncSession,
    test_workspace: Workspace,
    test_account,
    test_transactions,
):
    run_resp = await client.post(
        "/api/backups/run",
        json={"content": "data"},
        headers=auth_headers,
    )
    assert run_resp.status_code == 200, run_resp.text
    backup_id = run_resp.json()["id"]

    missing_confirm = await client.post(
        f"/api/backups/{backup_id}/restore",
        json={"content": "data", "mode": "current_workspace"},
        headers=auth_headers,
    )
    assert missing_confirm.status_code == 400

    restore_resp = await client.post(
        f"/api/backups/{backup_id}/restore",
        json={"content": "data", "mode": "current_workspace", "confirmation": "RESTORE"},
        headers=auth_headers,
    )
    assert restore_resp.status_code == 200, restore_resp.text
    body = restore_resp.json()
    assert body["workspace_id"] == str(test_workspace.id)
    assert body["restored_counts"]["transactions"] == len(test_transactions)

    workspace_id = test_workspace.id
    session.expire_all()
    account = (
        await session.execute(select(Account).where(Account.workspace_id == workspace_id))
    ).scalar_one()
    assert account.connection_id is None


@pytest.mark.asyncio
async def test_backup_round_trip_invoices_products_and_files(
    session: AsyncSession,
    test_user,
    test_workspace: Workspace,
):
    storage = get_storage_provider()
    logo_id = uuid.uuid4()
    logo_data = b"restored invoice logo"
    await storage.upload(
        invoice_logo_service.storage_key(test_workspace.id, logo_id),
        logo_data,
        "image/png",
    )

    product = Product(
        workspace_id=test_workspace.id,
        user_id=test_user.id,
        name="Consulting",
    )
    session.add(product)
    await session.flush()
    price = ProductPrice(
        product_id=product.id,
        workspace_id=test_workspace.id,
        currency="USD",
        unit_price=Decimal("125.00"),
    )
    settings = InvoiceSettings(
        workspace_id=test_workspace.id,
        logo_id=logo_id,
        issuer_display_name="Securo Test",
    )
    invoice = Invoice(
        workspace_id=test_workspace.id,
        user_id=test_user.id,
        issue_date=date(2026, 10, 24),
        due_date=date(2026, 11, 23),
        currency="USD",
        total=Decimal("125.00"),
        share_token="must-not-be-restored",
        snapshot={"issuer": {"logo_id": str(logo_id)}},
    )
    session.add_all([price, settings, invoice])
    await session.flush()
    line = InvoiceLine(
        invoice_id=invoice.id,
        workspace_id=test_workspace.id,
        description="Consulting",
        unit_price=Decimal("125.00"),
        total=Decimal("125.00"),
        product_id=product.id,
        price_id=price.id,
    )
    attachment_key = f"{test_workspace.id}/invoices/{invoice.id}/source.pdf"
    attachment_data = b"invoice attachment"
    stored = await storage.upload(attachment_key, attachment_data, "application/pdf")
    attachment = InvoiceAttachment(
        invoice_id=invoice.id,
        workspace_id=test_workspace.id,
        user_id=test_user.id,
        filename="source.pdf",
        storage_key=stored.storage_key,
        content_type=stored.content_type,
        size=stored.size,
    )
    session.add_all([line, attachment])
    await session.commit()

    data = await backup_service.build_backup_zip(session, test_workspace)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        metadata = json.loads(zf.read("metadata.json"))
        assert metadata["entity_counts"]["products"] == 1
        assert metadata["entity_counts"]["invoices"] == 1
        assert metadata["entity_counts"]["invoice_attachments"] == 1
        assert f"invoice_logos/{logo_id}.png" in zf.namelist()

    result = await backup_service.restore_backup_bytes(
        session,
        data=data,
        target_user_id=test_user.id,
        current_workspace=test_workspace,
        content=backup_service.BackupContent.both,
        mode=backup_service.BackupRestoreMode.new_workspace,
    )

    restored_invoice = (
        await session.execute(select(Invoice).where(Invoice.workspace_id == result.workspace_id))
    ).scalar_one()
    restored_line = (
        await session.execute(
            select(InvoiceLine).where(InvoiceLine.workspace_id == result.workspace_id)
        )
    ).scalar_one()
    restored_product = (
        await session.execute(select(Product).where(Product.workspace_id == result.workspace_id))
    ).scalar_one()
    restored_price = (
        await session.execute(
            select(ProductPrice).where(ProductPrice.workspace_id == result.workspace_id)
        )
    ).scalar_one()
    restored_attachment = (
        await session.execute(
            select(InvoiceAttachment).where(InvoiceAttachment.workspace_id == result.workspace_id)
        )
    ).scalar_one()

    assert restored_invoice.id != invoice.id
    assert restored_invoice.share_token is None
    assert restored_line.invoice_id == restored_invoice.id
    assert restored_line.product_id == restored_product.id
    assert restored_line.price_id == restored_price.id
    assert await storage.download(restored_attachment.storage_key) == attachment_data
    assert await invoice_logo_service.read(result.workspace_id, logo_id) == logo_data
