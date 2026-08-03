from fastapi import HTTPException, status

from app.core.config import get_settings


def require_local_auth_enabled() -> None:
    """Reject local credential operations when OIDC-only mode is active."""
    if not get_settings().local_auth_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="LOCAL_AUTH_DISABLED",
        )
