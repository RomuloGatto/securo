from __future__ import annotations

import io
import json
import logging
import re
import uuid
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import pyzipper
from fastapi import HTTPException, status
from pydantic import ValidationError
from sqlalchemy import Date, DateTime, Numeric, delete, insert, select, update
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.account import Account
from app.models.app_settings import AppSetting
from app.models.asset import Asset
from app.models.asset_group import AssetGroup
from app.models.asset_transaction import AssetTransaction
from app.models.asset_value import AssetValue
from app.models.budget import Budget
from app.models.category import Category
from app.models.category_group import CategoryGroup
from app.models.collection import Collection, collection_accounts, collection_asset_groups
from app.models.credit_card_bill import CreditCardBill
from app.models.goal import Goal
from app.models.group import Group, GroupMember
from app.models.group_settlement import GroupSettlement
from app.models.import_log import ImportLog
from app.models.invoice import (
    Invoice,
    InvoiceAllocation,
    InvoiceDeduction,
    InvoiceInstallment,
    InvoiceLine,
    InvoiceSettings,
)
from app.models.invoice_attachment import InvoiceAttachment
from app.models.invoice_schedule import InvoiceSchedule, InvoiceScheduleTerm
from app.models.payee import Payee, PayeeMapping, PayeeTaxId
from app.models.product import Product, ProductPrice
from app.models.reconciliation import (
    ReconciliationEvent,
    ReconciliationRule,
    ReconciliationSuggestion,
)
from app.models.recurring_transaction import RecurringTransaction
from app.models.rule import Rule
from app.models.transaction import Transaction
from app.models.transaction_attachment import TransactionAttachment
from app.models.transaction_split import TransactionSplit
from app.models.workspace import Workspace, WorkspaceTaxId
from app.providers import get_storage_provider
from app.services import invoice_logo_service, workspace_service
from app.services.attachment_service import sanitize_filename
from app.schemas.backup import (
    BackupConfig,
    BackupContent,
    BackupItem,
    BackupPreview,
    BackupRestoreMode,
    BackupRestoreResult,
)

FORMAT_VERSION = "1.1"
BACKUP_PREFIX = "securo-backup"
CONFIG_KEY_PREFIX = "backup:"
CONFIG_KEY_SUFFIX = ":config"
BACKUP_STORAGE_PATH = Path("/app/data/backups")
_COMPRESSION = zipfile.ZIP_DEFLATED
logger = logging.getLogger(__name__)


def build_backup_archive(files: dict[str, object], password: str | None = None) -> bytes:
    """Pack JSON payloads into a plain or AES-256 encrypted ZIP archive."""
    buffer = io.BytesIO()
    if password:
        archive = pyzipper.AESZipFile(
            buffer,
            "w",
            compression=_COMPRESSION,
            encryption=pyzipper.WZ_AES,
        )
        archive.setpassword(password.encode("utf-8"))
    else:
        archive = zipfile.ZipFile(buffer, "w", _COMPRESSION)

    with archive as output:
        for name, payload in files.items():
            output.writestr(name, json.dumps(payload, indent=2, ensure_ascii=False))

    return buffer.getvalue()


@dataclass(frozen=True)
class EntitySpec:
    name: str
    model: type | None = None


RESTORE_ORDER: list[str] = [
    "workspace_tax_ids",
    "category_groups",
    "categories",
    "payees",
    "payee_tax_ids",
    "payee_mappings",
    "accounts",
    "asset_groups",
    "collections",
    "collection_accounts",
    "collection_asset_groups",
    "rules",
    "reconciliation_rules",
    "budgets",
    "recurring_transactions",
    "import_logs",
    "credit_card_bills",
    "groups",
    "group_members",
    "products",
    "product_prices",
    "invoice_settings",
    "invoice_schedules",
    "invoice_schedule_terms",
    "assets",
    "asset_values",
    "asset_transactions",
    "transactions",
    "transaction_splits",
    "group_settlements",
    "transaction_attachments",
    "invoices",
    "invoice_lines",
    "invoice_installments",
    "invoice_deductions",
    "invoice_allocations",
    "invoice_attachments",
    "reconciliation_suggestions",
    "reconciliation_events",
    "goals",
]

MODEL_SPECS: dict[str, EntitySpec] = {
    "workspace_tax_ids": EntitySpec("workspace_tax_ids", WorkspaceTaxId),
    "category_groups": EntitySpec("category_groups", CategoryGroup),
    "categories": EntitySpec("categories", Category),
    "payees": EntitySpec("payees", Payee),
    "payee_tax_ids": EntitySpec("payee_tax_ids", PayeeTaxId),
    "payee_mappings": EntitySpec("payee_mappings", PayeeMapping),
    "accounts": EntitySpec("accounts", Account),
    "asset_groups": EntitySpec("asset_groups", AssetGroup),
    "collections": EntitySpec("collections", Collection),
    "rules": EntitySpec("rules", Rule),
    "reconciliation_rules": EntitySpec("reconciliation_rules", ReconciliationRule),
    "budgets": EntitySpec("budgets", Budget),
    "recurring_transactions": EntitySpec("recurring_transactions", RecurringTransaction),
    "import_logs": EntitySpec("import_logs", ImportLog),
    "credit_card_bills": EntitySpec("credit_card_bills", CreditCardBill),
    "groups": EntitySpec("groups", Group),
    "group_members": EntitySpec("group_members", GroupMember),
    "products": EntitySpec("products", Product),
    "product_prices": EntitySpec("product_prices", ProductPrice),
    "invoice_settings": EntitySpec("invoice_settings", InvoiceSettings),
    "invoice_schedules": EntitySpec("invoice_schedules", InvoiceSchedule),
    "invoice_schedule_terms": EntitySpec("invoice_schedule_terms", InvoiceScheduleTerm),
    "assets": EntitySpec("assets", Asset),
    "asset_values": EntitySpec("asset_values", AssetValue),
    "asset_transactions": EntitySpec("asset_transactions", AssetTransaction),
    "transactions": EntitySpec("transactions", Transaction),
    "transaction_splits": EntitySpec("transaction_splits", TransactionSplit),
    "group_settlements": EntitySpec("group_settlements", GroupSettlement),
    "transaction_attachments": EntitySpec("transaction_attachments", TransactionAttachment),
    "invoices": EntitySpec("invoices", Invoice),
    "invoice_lines": EntitySpec("invoice_lines", InvoiceLine),
    "invoice_installments": EntitySpec("invoice_installments", InvoiceInstallment),
    "invoice_deductions": EntitySpec("invoice_deductions", InvoiceDeduction),
    "invoice_allocations": EntitySpec("invoice_allocations", InvoiceAllocation),
    "invoice_attachments": EntitySpec("invoice_attachments", InvoiceAttachment),
    "reconciliation_suggestions": EntitySpec(
        "reconciliation_suggestions", ReconciliationSuggestion
    ),
    "reconciliation_events": EntitySpec("reconciliation_events", ReconciliationEvent),
    "goals": EntitySpec("goals", Goal),
}

# Configuration is intentionally limited to entities that can be restored without
# requiring provider credentials or bank tokens. Data restores include the
# dependency containers they need to be useful on their own.
CONFIG_NAMES = [
    "workspace_tax_ids",
    "category_groups",
    "categories",
    "payees",
    "payee_tax_ids",
    "payee_mappings",
    "rules",
    "reconciliation_rules",
    "budgets",
    "recurring_transactions",
    "products",
    "product_prices",
    "invoice_settings",
    "invoice_schedules",
    "invoice_schedule_terms",
    "goals",
]
DATA_NAMES = [
    "workspace_tax_ids",
    "category_groups",
    "categories",
    "payees",
    "payee_tax_ids",
    "payee_mappings",
    "accounts",
    "asset_groups",
    "collections",
    "collection_accounts",
    "collection_asset_groups",
    "budgets",
    "recurring_transactions",
    "import_logs",
    "credit_card_bills",
    "groups",
    "group_members",
    "products",
    "product_prices",
    "invoice_settings",
    "invoice_schedules",
    "invoice_schedule_terms",
    "assets",
    "asset_values",
    "asset_transactions",
    "transactions",
    "transaction_splits",
    "group_settlements",
    "transaction_attachments",
    "invoices",
    "invoice_lines",
    "invoice_installments",
    "invoice_deductions",
    "invoice_allocations",
    "invoice_attachments",
    "reconciliation_suggestions",
    "reconciliation_events",
    "goals",
]
BOTH_NAMES = list(dict.fromkeys([*DATA_NAMES, *CONFIG_NAMES]))

NULL_WHEN_UNMAPPED = {
    "connection_id",
    "account_id",
    "asset_id",
    "asset_group_id",
    "bill_id",
    "category_id",
    "corrects_id",
    "credit_note_id",
    "group_id",
    "group_member_id",
    "import_id",
    "invoice_id",
    "linked_user_id",
    "payee_id",
    "price_id",
    "product_id",
    "recurring_transaction_id",
    "resolved_by",
    "schedule_id",
    "transaction_id",
    "transfer_pair_id",
    "from_member_id",
    "to_member_id",
    "receiver_transaction_id",
    "target_id",
}


def entity_names_for_content(content: BackupContent | str | None) -> list[str]:
    content = BackupContent(content or BackupContent.both)
    if content == BackupContent.configuration:
        return CONFIG_NAMES.copy()
    if content == BackupContent.data:
        return DATA_NAMES.copy()
    return BOTH_NAMES.copy()


def _config_key(workspace_id: uuid.UUID) -> str:
    return f"{CONFIG_KEY_PREFIX}{workspace_id}{CONFIG_KEY_SUFFIX}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_dt(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _next_run(last_run_at: datetime | None, schedule: str) -> datetime | None:
    if last_run_at is None:
        return None
    delta = timedelta(days=7 if schedule == "weekly" else 1)
    return last_run_at + delta


def _backup_storage_dir() -> Path:
    dest = BACKUP_STORAGE_PATH
    dest.mkdir(parents=True, exist_ok=True)
    return dest.resolve()


def _safe_backup_id(value: str) -> str:
    backup_id = value.removesuffix(".zip")
    if not re.fullmatch(r"[A-Za-z0-9._-]+", backup_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid backup id")
    return backup_id


def _backup_path(backup_id: str) -> Path:
    backup_id = _safe_backup_id(backup_id)
    base = _backup_storage_dir()
    path = base / f"{backup_id}.zip"
    if base not in path.resolve().parents and path.resolve() != base:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid backup path")
    return path


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.lower()).strip("-")
    return slug[:40] or "workspace"


def _serialize_value(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


def _serialize_model(obj: Any) -> dict[str, Any]:
    data = {col.key: _serialize_value(getattr(obj, col.key)) for col in obj.__table__.columns}
    # Bank provider links point at non-exported credential-bearing rows. Do not
    # carry those identifiers in backup files; restored records reconnect only
    # through an explicit fresh bank connection.
    if "connection_id" in data:
        data["connection_id"] = None
    # Invoice share tokens grant unauthenticated access to a public invoice.
    # A restore must create a private copy instead of cloning that capability.
    if "share_token" in data:
        data["share_token"] = None
    return data


def _is_uuid_column(column: Any) -> bool:
    if isinstance(column.type, PgUUID):
        return True
    try:
        return column.type.python_type is uuid.UUID
    except (AttributeError, NotImplementedError):
        return False


def _deserialize_column(column: Any, value: Any) -> Any:
    if value is None:
        return None
    if _is_uuid_column(column):
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    if isinstance(column.type, DateTime) and isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    if (
        isinstance(column.type, Date)
        and not isinstance(column.type, DateTime)
        and isinstance(value, str)
    ):
        return date.fromisoformat(value[:10])
    if isinstance(column.type, Numeric) and value is not None:
        return Decimal(str(value))
    return value


def _rewrite_json(value: Any, id_map: dict[str, str]) -> Any:
    if isinstance(value, str):
        return id_map.get(value, value)
    if isinstance(value, list):
        return [_rewrite_json(v, id_map) for v in value]
    if isinstance(value, dict):
        return {k: _rewrite_json(v, id_map) for k, v in value.items()}
    return value


def _invoice_logo_ids(name: str, row: dict[str, Any]) -> list[str]:
    if name == "invoice_settings" and row.get("logo_id"):
        return [str(row["logo_id"])]
    if name == "invoices":
        snapshot = row.get("snapshot") or {}
        issuer = snapshot.get("issuer") if isinstance(snapshot, dict) else None
        if isinstance(issuer, dict) and issuer.get("logo_id"):
            return [str(issuer["logo_id"])]
    return []


async def get_backup_config(session: AsyncSession, workspace_id: uuid.UUID) -> BackupConfig:
    setting = await session.get(AppSetting, _config_key(workspace_id))
    if setting is None:
        return BackupConfig(storage_shared=get_settings().backup_storage_shared)
    try:
        raw = json.loads(setting.value)
    except json.JSONDecodeError:
        raw = {}
    cfg = BackupConfig(**raw)
    cfg.storage_shared = get_settings().backup_storage_shared
    cfg.next_run_at = _next_run(cfg.last_run_at, cfg.schedule)
    return cfg


async def save_backup_config(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    updates: dict[str, Any],
) -> BackupConfig:
    if updates.get("scheduled_enabled") is True and not get_settings().backup_storage_shared:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Scheduled backups require shared persistent backup storage. "
                "Enable persistence.backups.enabled for Helm deployments."
            ),
        )
    current = await get_backup_config(session, workspace_id)
    data = current.model_dump(mode="json", exclude={"storage_shared"})
    data.update(
        {
            key: value
            for key, value in updates.items()
            if value is not None or key == "retention_days"
        }
    )
    cfg = BackupConfig(**data)
    cfg.storage_shared = get_settings().backup_storage_shared
    cfg.next_run_at = _next_run(cfg.last_run_at, cfg.schedule)
    setting = await session.get(AppSetting, _config_key(workspace_id))
    value = cfg.model_dump_json(exclude={"next_run_at", "storage_shared"})
    if setting is None:
        setting = AppSetting(key=_config_key(workspace_id), value=value)
        session.add(setting)
    else:
        setting.value = value
    await session.commit()
    return cfg


async def _fetch_entity_rows(
    session: AsyncSession, name: str, workspace_id: uuid.UUID
) -> list[dict[str, Any]]:
    if name == "asset_values":
        result = await session.execute(
            select(AssetValue)
            .join(Asset, AssetValue.asset_id == Asset.id)
            .where(Asset.workspace_id == workspace_id)
        )
        return [_serialize_model(row) for row in result.scalars().all()]
    if name == "collection_accounts":
        result = await session.execute(
            select(collection_accounts.c.collection_id, collection_accounts.c.account_id)
            .join(Collection, collection_accounts.c.collection_id == Collection.id)
            .where(Collection.workspace_id == workspace_id)
        )
        return [
            {"collection_id": str(collection_id), "account_id": str(account_id)}
            for collection_id, account_id in result.all()
        ]
    if name == "collection_asset_groups":
        result = await session.execute(
            select(
                collection_asset_groups.c.collection_id, collection_asset_groups.c.asset_group_id
            )
            .join(Collection, collection_asset_groups.c.collection_id == Collection.id)
            .where(Collection.workspace_id == workspace_id)
        )
        return [
            {"collection_id": str(collection_id), "asset_group_id": str(asset_group_id)}
            for collection_id, asset_group_id in result.all()
        ]
    spec = MODEL_SPECS[name]
    model = spec.model
    assert model is not None
    dynamic_model: Any = model
    result = await session.execute(
        select(dynamic_model).where(dynamic_model.workspace_id == workspace_id)
    )
    return [_serialize_model(row) for row in result.scalars().all()]


async def build_backup_zip(
    session: AsyncSession,
    workspace: Workspace,
    *,
    content: BackupContent = BackupContent.both,
) -> bytes:
    names = entity_names_for_content(content)
    buf = io.BytesIO()
    entity_counts: dict[str, int] = {}
    warnings: list[str] = []
    storage = get_storage_provider()
    archived_logo_ids: set[str] = set()

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in names:
            rows = await _fetch_entity_rows(session, name, workspace.id)
            if name in {"transaction_attachments", "invoice_attachments"}:
                rows_with_files = []
                for row in rows:
                    try:
                        stored_data = await storage.download(row["storage_key"])
                    except Exception:
                        warnings.append(
                            f"Attachment skipped because its stored file was unavailable: {row.get('filename')}"
                        )
                        continue
                    attachment_name = sanitize_filename(row.get("filename") or "attachment")
                    prefix = (
                        "attachments"
                        if name == "transaction_attachments"
                        else "invoice_attachments"
                    )
                    backup_path = f"{prefix}/{row['id']}/{attachment_name}"
                    zf.writestr(backup_path, stored_data)
                    row["backup_path"] = backup_path
                    row["storage_key"] = None
                    rows_with_files.append(row)
                rows = rows_with_files

            if name in {"invoice_settings", "invoices"}:
                for row in rows:
                    for logo_id in _invoice_logo_ids(name, row):
                        if logo_id in archived_logo_ids:
                            continue
                        logo_data = await invoice_logo_service.read(
                            workspace.id, uuid.UUID(logo_id)
                        )
                        if logo_data is None:
                            warnings.append(
                                "Invoice logo skipped because its stored file was "
                                f"unavailable: {logo_id}"
                            )
                            continue
                        zf.writestr(f"invoice_logos/{logo_id}.png", logo_data)
                        archived_logo_ids.add(logo_id)
            entity_counts[name] = len(rows)
            zf.writestr(f"{name}.json", json.dumps(rows, indent=2, ensure_ascii=False))

        metadata = {
            "export_date": _now().isoformat(),
            "format_version": FORMAT_VERSION,
            "workspace_id": str(workspace.id),
            "workspace_name": workspace.name,
            "content": content.value,
            "entity_counts": entity_counts,
            "warnings": warnings,
        }
        zf.writestr("metadata.json", json.dumps(metadata, indent=2, ensure_ascii=False))

    return buf.getvalue()


def _metadata_from_zip_bytes(data: bytes) -> tuple[dict[str, Any], list[str]]:
    warnings: list[str] = []
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            if "metadata.json" not in zf.namelist():
                raise ValueError("metadata.json missing")
            metadata = json.loads(zf.read("metadata.json"))
            if not isinstance(metadata, dict):
                raise ValueError("metadata.json must contain a JSON object")
            metadata_warnings = metadata.get("warnings") or []
            if not isinstance(metadata_warnings, list):
                raise ValueError("metadata warnings must contain a JSON array")
            warnings.extend(str(warning) for warning in metadata_warnings)
            return metadata, warnings
    except (RuntimeError, NotImplementedError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Encrypted backups cannot be restored here. "
                f"Upload an unencrypted Securo backup ZIP: {exc}"
            ),
        )
    except (zipfile.BadZipFile, OSError, json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid backup file: {exc}"
        )


def preview_backup_bytes(data: bytes) -> BackupPreview:
    metadata, warnings = _metadata_from_zip_bytes(data)
    export_date = _parse_dt(metadata.get("export_date"))
    workspace_id = None
    if metadata.get("workspace_id"):
        try:
            workspace_id = uuid.UUID(str(metadata["workspace_id"]))
        except ValueError:
            warnings.append("Backup metadata has an invalid workspace_id")
    content = metadata.get("content") or BackupContent.both.value
    try:
        backup_content = BackupContent(content)
    except ValueError:
        backup_content = BackupContent.both
        warnings.append(f"Unknown backup content '{content}', treating as both")
    entity_counts = metadata.get("entity_counts") or {}
    if not isinstance(entity_counts, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid backup file: entity_counts must contain a JSON object",
        )
    try:
        return BackupPreview(
            valid=True,
            format_version=str(metadata.get("format_version") or "unknown"),
            export_date=export_date,
            workspace_id=workspace_id,
            workspace_name=metadata.get("workspace_name"),
            content=backup_content,
            entity_counts=entity_counts,
            warnings=warnings,
        )
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid backup metadata: {exc}",
        ) from exc


def _item_from_path(path: Path) -> BackupItem | None:
    try:
        data = path.read_bytes()
        preview = preview_backup_bytes(data)
        stat = path.stat()
    except Exception:
        return None
    return BackupItem(
        id=path.stem,
        filename=path.name,
        size_bytes=stat.st_size,
        created_at=preview.export_date or datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
        workspace_id=preview.workspace_id,
        workspace_name=preview.workspace_name,
        content=preview.content,
        entity_counts=preview.entity_counts,
    )


async def list_stored_backups(
    session: AsyncSession,
    workspace_id: uuid.UUID,
) -> list[BackupItem]:
    dest = _backup_storage_dir()
    items = []
    for path in dest.glob(f"{BACKUP_PREFIX}-*.zip"):
        item = _item_from_path(path)
        if item and item.workspace_id == workspace_id:
            items.append(item)
    return sorted(items, key=lambda item: item.created_at, reverse=True)


async def _apply_retention(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    config: BackupConfig,
) -> None:
    items = await list_stored_backups(session, workspace_id)
    to_delete: set[str] = set()
    if config.retention_count and len(items) > config.retention_count:
        to_delete.update(item.id for item in items[config.retention_count :])
    if config.retention_days:
        cutoff = _now() - timedelta(days=config.retention_days)
        to_delete.update(item.id for item in items if item.created_at < cutoff)
    for backup_id in to_delete:
        try:
            _backup_path(backup_id).unlink(missing_ok=True)
        except OSError:
            pass


async def create_stored_backup(
    session: AsyncSession,
    workspace: Workspace,
    *,
    content: BackupContent | None = None,
    update_schedule: bool = True,
) -> BackupItem:
    config = await get_backup_config(session, workspace.id)
    selected_content = content or config.content
    data = await build_backup_zip(session, workspace, content=selected_content)
    timestamp = _now().strftime("%Y%m%dT%H%M%SZ")
    backup_id = f"{BACKUP_PREFIX}-{_slug(workspace.name)}-{timestamp}-{uuid.uuid4().hex[:8]}"
    path = _backup_path(backup_id)
    path.write_bytes(data)

    if update_schedule:
        config.last_run_at = _now()
        setting = await session.get(AppSetting, _config_key(workspace.id))
        if setting is None:
            setting = AppSetting(
                key=_config_key(workspace.id), value=config.model_dump_json(exclude={"next_run_at"})
            )
            session.add(setting)
        else:
            setting.value = config.model_dump_json(exclude={"next_run_at"})
        await session.commit()
    await _apply_retention(session, workspace.id, config)
    item = _item_from_path(path)
    if item is None:
        raise HTTPException(status_code=500, detail="Backup was created but could not be read")
    return item


async def get_stored_backup_bytes(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    backup_id: str,
) -> tuple[str, bytes]:
    path = _backup_path(backup_id)
    if not path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Backup not found")
    data = path.read_bytes()
    preview = preview_backup_bytes(data)
    if preview.workspace_id != workspace_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Backup not found")
    return path.name, data


async def preview_stored_backup(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    backup_id: str,
) -> BackupPreview:
    _, data = await get_stored_backup_bytes(session, workspace_id, backup_id)
    return preview_backup_bytes(data)


def _read_json_file(zf: zipfile.ZipFile, name: str) -> list[dict[str, Any]]:
    filename = f"{name}.json"
    if filename not in zf.namelist():
        return []
    raw = json.loads(zf.read(filename))
    if not isinstance(raw, list):
        raise ValueError(f"{filename} must contain a JSON array")
    return [row for row in raw if isinstance(row, dict)]


def _archive_entity_names(zf: zipfile.ZipFile, selected_names: list[str]) -> list[str]:
    """Return only selected entities represented by files in this archive."""
    members = set(zf.namelist())
    return [name for name in selected_names if f"{name}.json" in members]


def _build_id_map(
    zf: zipfile.ZipFile,
    names: list[str],
    *,
    remap: bool,
) -> dict[str, str]:
    id_map: dict[str, str] = {}
    for name in names:
        if name in ("collection_accounts", "collection_asset_groups"):
            continue
        for row in _read_json_file(zf, name):
            old_id = row.get("id")
            if old_id:
                id_map[str(old_id)] = str(uuid.uuid4()) if remap else str(old_id)
    return id_map


def _prepare_model_data(
    model: Any,
    row: dict[str, Any],
    *,
    id_map: dict[str, str],
    target_workspace_id: uuid.UUID,
    target_user_id: uuid.UUID,
    remap: bool,
) -> dict[str, Any]:
    columns = {col.key: col for col in model.__table__.columns}
    data: dict[str, Any] = {}
    for key, value in row.items():
        if key == "backup_path" or key not in columns:
            continue
        rewritten = _rewrite_json(value, id_map)
        if key == "id" and value is not None:
            rewritten = id_map.get(str(value), str(value))
        elif key == "workspace_id" and "workspace_id" in columns:
            rewritten = str(target_workspace_id)
        elif key in {
            "user_id",
            "created_by",
            "uploaded_by",
            "verified_by",
            "resolved_by",
        }:
            rewritten = str(target_user_id) if value is not None else None
        elif key == "connection_id" and "connection_id" in columns:
            rewritten = None
        elif key == "share_token":
            rewritten = None
        elif key == "logo_id":
            # Logo IDs are storage object identifiers, not entity primary keys.
            rewritten = value
        elif key in NULL_WHEN_UNMAPPED and value is not None and remap and str(value) not in id_map:
            rewritten = None
        data[key] = _deserialize_column(columns[key], rewritten)

    if "workspace_id" in columns:
        data["workspace_id"] = target_workspace_id
    if "user_id" in columns:
        data["user_id"] = target_user_id
    if "connection_id" in columns:
        data["connection_id"] = None
    return data


async def _clear_workspace_entities(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    names: list[str],
) -> list[str]:
    name_set = set(names)
    stale_storage_keys: list[str] = []
    attachment_models = []
    if "transaction_attachments" in name_set:
        attachment_models.append(TransactionAttachment)
    if "invoice_attachments" in name_set:
        attachment_models.append(InvoiceAttachment)
    for attachment_model in attachment_models:
        result = await session.execute(
            select(attachment_model.storage_key).where(
                attachment_model.workspace_id == workspace_id
            )
        )
        stale_storage_keys.extend(result.scalars().all())

    # Break nullable references when a configuration-only restore replaces
    # referenced rows but leaves transaction data in place.
    if "categories" in name_set and "transactions" not in name_set:
        await session.execute(
            update(Transaction)
            .where(Transaction.workspace_id == workspace_id)
            .values(category_id=None)
        )
    if "payees" in name_set and "transactions" not in name_set:
        await session.execute(
            update(Transaction)
            .where(Transaction.workspace_id == workspace_id)
            .values(payee_id=None)
        )
    if "payees" in name_set and "invoices" not in name_set:
        await session.execute(
            update(Invoice).where(Invoice.workspace_id == workspace_id).values(payee_id=None)
        )
    if "payees" in name_set and "invoice_schedules" not in name_set:
        await session.execute(
            update(InvoiceSchedule)
            .where(InvoiceSchedule.workspace_id == workspace_id)
            .values(payee_id=None)
        )
    if "recurring_transactions" in name_set and "transactions" not in name_set:
        await session.execute(
            update(Transaction)
            .where(Transaction.workspace_id == workspace_id)
            .values(recurring_transaction_id=None)
        )
    if "credit_card_bills" in name_set and "transactions" not in name_set:
        await session.execute(
            update(Transaction).where(Transaction.workspace_id == workspace_id).values(bill_id=None)
        )

    collection_ids = select(Collection.id).where(Collection.workspace_id == workspace_id)
    if "collection_accounts" in name_set or "collections" in name_set:
        await session.execute(
            delete(collection_accounts).where(
                collection_accounts.c.collection_id.in_(collection_ids)
            )
        )
    if "collection_asset_groups" in name_set or "collections" in name_set:
        await session.execute(
            delete(collection_asset_groups).where(
                collection_asset_groups.c.collection_id.in_(collection_ids)
            )
        )

    delete_order = [
        "reconciliation_events",
        "reconciliation_suggestions",
        "invoice_attachments",
        "invoice_allocations",
        "invoice_deductions",
        "invoice_installments",
        "invoice_lines",
        "transaction_attachments",
        "group_settlements",
        "transaction_splits",
        "transactions",
        "invoices",
        "invoice_schedule_terms",
        "invoice_schedules",
        "product_prices",
        "products",
        "credit_card_bills",
        "import_logs",
        "asset_transactions",
        "asset_values",
        "goals",
        "assets",
        "collections",
        "budgets",
        "recurring_transactions",
        "reconciliation_rules",
        "rules",
        "payee_tax_ids",
        "payee_mappings",
        "payees",
        "categories",
        "category_groups",
        "accounts",
        "group_members",
        "groups",
        "asset_groups",
        "invoice_settings",
        "workspace_tax_ids",
    ]
    for name in delete_order:
        if name not in name_set:
            continue
        if name == "asset_values":
            asset_ids = select(Asset.id).where(Asset.workspace_id == workspace_id)
            await session.execute(delete(AssetValue).where(AssetValue.asset_id.in_(asset_ids)))
            continue
        model = MODEL_SPECS[name].model
        assert model is not None
        dynamic_model: Any = model
        await session.execute(
            delete(dynamic_model).where(dynamic_model.workspace_id == workspace_id)
        )
    return list(dict.fromkeys(stale_storage_keys))


async def _insert_associations(
    session: AsyncSession,
    table_name: str,
    rows: list[dict[str, Any]],
    id_map: dict[str, str],
) -> int:
    table = collection_accounts if table_name == "collection_accounts" else collection_asset_groups
    prepared = []
    for row in rows:
        mapped = {k: id_map.get(str(v), str(v)) for k, v in row.items() if v is not None}
        if all(mapped.values()):
            prepared.append({k: uuid.UUID(v) for k, v in mapped.items()})
    if prepared:
        await session.execute(insert(table), prepared)
    return len(prepared)


async def _undo_restore_storage_changes(
    storage: Any,
    changes: list[tuple[str, bytes | None, str]],
) -> None:
    """Restore overwritten files and remove new files after a DB rollback."""
    for key, previous_data, content_type in reversed(changes):
        try:
            if previous_data is None:
                await storage.delete(key)
            else:
                await storage.upload(key, previous_data, content_type)
        except Exception:
            # Preserve the original restore failure. Storage cleanup is best-effort
            # because there is no transaction spanning SQL and the file provider.
            logger.exception("Could not roll back restored storage object %s", key)


async def restore_backup_bytes(
    session: AsyncSession,
    *,
    data: bytes,
    target_user_id: uuid.UUID,
    current_workspace: Workspace,
    content: BackupContent,
    mode: BackupRestoreMode,
    confirmation: str | None = None,
) -> BackupRestoreResult:
    if mode == BackupRestoreMode.current_workspace and confirmation != "RESTORE":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Type RESTORE to confirm destructive restore",
        )

    preview = preview_backup_bytes(data)
    selected_names = entity_names_for_content(content)
    warnings = list(preview.warnings)
    restored_counts: dict[str, int] = {}

    # Workspace creation needs the User object; import here to avoid pulling the
    # auth model into module import paths that only need backup metadata helpers.
    from app.models.user import User

    storage = get_storage_provider()
    storage_changes: list[tuple[str, bytes | None, str]] = []
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = _archive_entity_names(zf, selected_names)
            missing_names = [name for name in selected_names if name not in names]
            if missing_names:
                warnings.append(
                    "Skipped entities that are not present in this backup: "
                    + ", ".join(missing_names)
                )
            remap = mode == BackupRestoreMode.new_workspace
            # Parse every selected entity file before a current-workspace restore
            # starts deleting rows. This also validates that each payload is a list.
            id_map = _build_id_map(zf, names, remap=remap)
            stale_storage_keys: list[str] = []
            if mode == BackupRestoreMode.new_workspace:
                user = await session.get(User, target_user_id)
                if user is None:
                    raise HTTPException(status_code=404, detail="User not found")
                workspace_name = preview.workspace_name or current_workspace.name
                target_workspace = await workspace_service.create_workspace(
                    session,
                    name=f"{workspace_name} (restored)",
                    creator=user,
                    kind=current_workspace.kind,
                    default_currency=current_workspace.default_currency,
                    locale=current_workspace.locale,
                    icon=current_workspace.icon,
                    color=current_workspace.color,
                    self_membership=True,
                    seed_defaults=False,
                )
            else:
                target_workspace = current_workspace
                stale_storage_keys = await _clear_workspace_entities(
                    session, target_workspace.id, names
                )

            uploaded_logo_ids: set[str] = set()
            for name in RESTORE_ORDER:
                if name not in names:
                    continue
                rows = _read_json_file(zf, name)
                if not rows:
                    restored_counts[name] = 0
                    continue
                if name in ("collection_accounts", "collection_asset_groups"):
                    restored_counts[name] = await _insert_associations(session, name, rows, id_map)
                    continue
                model = MODEL_SPECS[name].model
                assert model is not None

                if name in {"invoice_settings", "invoices"}:
                    for row in rows:
                        for logo_id in _invoice_logo_ids(name, row):
                            if logo_id in uploaded_logo_ids:
                                continue
                            backup_path = f"invoice_logos/{logo_id}.png"
                            if backup_path not in zf.namelist():
                                warnings.append(
                                    "Invoice logo skipped because backup data is "
                                    f"missing: {logo_id}"
                                )
                                continue
                            logo_key = invoice_logo_service.storage_key(
                                target_workspace.id, uuid.UUID(logo_id)
                            )
                            previous_logo = None
                            if mode == BackupRestoreMode.current_workspace:
                                try:
                                    previous_logo = await storage.download(logo_key)
                                except FileNotFoundError:
                                    pass
                            storage_changes.append((logo_key, previous_logo, "image/png"))
                            await storage.upload(logo_key, zf.read(backup_path), "image/png")
                            uploaded_logo_ids.add(logo_id)

                if name in {"transaction_attachments", "invoice_attachments"}:
                    count = 0
                    for row in rows:
                        backup_path = row.get("backup_path")
                        if not backup_path or backup_path not in zf.namelist():
                            warnings.append(
                                "Attachment skipped because backup data is missing: "
                                f"{row.get('filename')}"
                            )
                            continue
                        attachment_data = zf.read(backup_path)
                        prepared = _prepare_model_data(
                            model,
                            row,
                            id_map=id_map,
                            target_workspace_id=target_workspace.id,
                            target_user_id=target_user_id,
                            remap=remap,
                        )
                        filename = sanitize_filename(prepared.get("filename") or "attachment")
                        if name == "transaction_attachments":
                            parent_id = prepared["transaction_id"]
                            storage_key = (
                                f"{target_workspace.id}/{parent_id}/"
                                f"{uuid.uuid4().hex[:8]}_{filename}"
                            )
                        else:
                            parent_id = prepared["invoice_id"]
                            storage_key = (
                                f"{target_workspace.id}/invoices/{parent_id}/"
                                f"{uuid.uuid4().hex[:8]}_{filename}"
                            )
                        content_type = prepared.get("content_type") or "application/octet-stream"
                        storage_changes.append((storage_key, None, content_type))
                        stored = await storage.upload(
                            storage_key,
                            attachment_data,
                            content_type,
                        )
                        prepared["filename"] = filename
                        prepared["storage_key"] = stored.storage_key
                        prepared["content_type"] = stored.content_type
                        prepared["size"] = stored.size
                        session.add(model(**prepared))
                        count += 1
                    restored_counts[name] = count
                    continue

                if name == "invoices":
                    corrections: list[tuple[Invoice, uuid.UUID]] = []
                    for row in rows:
                        prepared = _prepare_model_data(
                            model,
                            row,
                            id_map=id_map,
                            target_workspace_id=target_workspace.id,
                            target_user_id=target_user_id,
                            remap=remap,
                        )
                        corrects_id = prepared.pop("corrects_id", None)
                        invoice = Invoice(**prepared)
                        session.add(invoice)
                        if corrects_id is not None:
                            corrections.append((invoice, corrects_id))
                    await session.flush()
                    for invoice, corrects_id in corrections:
                        invoice.corrects_id = corrects_id
                    await session.flush()
                    restored_counts[name] = len(rows)
                    continue

                count = 0
                for row in rows:
                    prepared = _prepare_model_data(
                        model,
                        row,
                        id_map=id_map,
                        target_workspace_id=target_workspace.id,
                        target_user_id=target_user_id,
                        remap=remap,
                    )
                    session.add(model(**prepared))
                    count += 1
                restored_counts[name] = count

            await session.refresh(target_workspace)
            response = BackupRestoreResult(
                workspace_id=target_workspace.id,
                workspace_name=target_workspace.name,
                mode=mode,
                content=content,
                restored_counts=restored_counts,
                warnings=warnings,
            )
            await session.commit()
            storage_changes.clear()
            for key in stale_storage_keys:
                try:
                    await storage.delete(key)
                except Exception:
                    response.warnings.append(
                        f"Old attachment file could not be deleted after restore: {key}"
                    )
            return response
    except HTTPException:
        try:
            await session.rollback()
        finally:
            await _undo_restore_storage_changes(storage, storage_changes)
        raise
    except Exception as exc:
        try:
            await session.rollback()
        finally:
            await _undo_restore_storage_changes(storage, storage_changes)
        raise HTTPException(status_code=400, detail=f"Could not restore backup: {exc}")


async def run_scheduled_backups(session: AsyncSession) -> dict[str, Any]:
    if not get_settings().backup_storage_shared:
        return {"created": 0, "skipped": 0, "errors": []}
    result = await session.execute(
        select(AppSetting).where(AppSetting.key.like(f"{CONFIG_KEY_PREFIX}%{CONFIG_KEY_SUFFIX}"))
    )
    settings = result.scalars().all()
    now = _now()
    created = 0
    skipped = 0
    errors: list[str] = []
    for setting in settings:
        try:
            workspace_id = uuid.UUID(
                setting.key.removeprefix(CONFIG_KEY_PREFIX).removesuffix(CONFIG_KEY_SUFFIX)
            )
            cfg = await get_backup_config(session, workspace_id)
            if not cfg.scheduled_enabled:
                skipped += 1
                continue
            due_at = _next_run(cfg.last_run_at, cfg.schedule)
            if due_at and due_at > now:
                skipped += 1
                continue
            workspace = await session.get(Workspace, workspace_id)
            if workspace is None or workspace.is_archived:
                skipped += 1
                continue
            await create_stored_backup(
                session, workspace, content=cfg.content, update_schedule=True
            )
            created += 1
        except Exception as exc:
            errors.append(str(exc))
    return {"created": created, "skipped": skipped, "errors": errors}
