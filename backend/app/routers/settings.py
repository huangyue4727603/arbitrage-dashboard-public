from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.utils.auth import require_auth

router = APIRouter(prefix="/api/settings", tags=["settings"])


# ---------- Schemas ----------

class ThemeRequest(BaseModel):
    theme: str  # "light" or "dark"


class NotificationRequest(BaseModel):
    sound_enabled: Optional[bool] = None
    popup_enabled: Optional[bool] = None


class SettingsResponse(BaseModel):
    theme: str
    sound_enabled: bool
    popup_enabled: bool

    model_config = {"from_attributes": True}


# ---------- Routes ----------

@router.get("/notification", response_model=SettingsResponse)
async def get_notification(
    user: User = Depends(require_auth),
):
    """Get current notification settings."""
    return SettingsResponse(
        theme=user.theme,
        sound_enabled=user.sound_enabled,
        popup_enabled=user.popup_enabled,
    )


@router.put("/theme", response_model=SettingsResponse)
async def update_theme(
    body: ThemeRequest,
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Toggle user theme between light and dark."""
    if body.theme not in ("light", "dark"):
        from fastapi import HTTPException, status

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Theme must be 'light' or 'dark'",
        )

    user.theme = body.theme
    db.add(user)
    await db.flush()

    return SettingsResponse(
        theme=user.theme,
        sound_enabled=user.sound_enabled,
        popup_enabled=user.popup_enabled,
    )


@router.put("/notification", response_model=SettingsResponse)
async def update_notification(
    body: NotificationRequest,
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Update global sound and popup notification switches."""
    if body.sound_enabled is not None:
        user.sound_enabled = body.sound_enabled
    if body.popup_enabled is not None:
        user.popup_enabled = body.popup_enabled

    db.add(user)
    await db.flush()

    # Invalidate basis alert config cache
    from app.schedulers.basis_alert_scheduler import basis_alert_scheduler
    basis_alert_scheduler.invalidate_config()

    return SettingsResponse(
        theme=user.theme,
        sound_enabled=user.sound_enabled,
        popup_enabled=user.popup_enabled,
    )
