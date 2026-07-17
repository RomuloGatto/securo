from datetime import date

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_session
from app.core.workspace_context import WorkspaceContext, current_workspace
from app.schemas.backup import BackupContent
from app.services import backup_service

router = APIRouter(prefix="/api/export", tags=["export"])


@router.get("/backup")
async def backup(
    content: BackupContent = Query(BackupContent.both),
    ctx: WorkspaceContext = Depends(current_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    """Export the current workspace as a JSON ZIP.

    Kept under `/api/export/backup` for backward compatibility with the old
    user-menu download action. The managed Backup page uses `/api/backups/*`.
    """
    data = await backup_service.build_backup_zip(session, ctx.workspace, content=content)
    today = date.today().isoformat()
    return StreamingResponse(
        iter([data]),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="securo-backup-{today}.zip"'},
    )
