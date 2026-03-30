import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.utils.auth import (
    create_access_token,
    hash_password,
    verify_password,
    require_auth,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


# ---------- Schemas ----------

class RegisterRequest(BaseModel):
    username: str
    password: str
    confirm_password: str
    invite_code: str

    @field_validator("username")
    @classmethod
    def validate_username(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 3 or len(v) > 30:
            raise ValueError("Username must be between 3 and 30 characters")
        return v

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        if len(v) < 6:
            raise ValueError("Password must be at least 6 characters")
        if not re.search(r"[a-zA-Z]", v):
            raise ValueError("Password must contain at least one letter")
        if not re.search(r"\d", v):
            raise ValueError("Password must contain at least one number")
        return v


class LoginRequest(BaseModel):
    username: str
    password: str


class AuthUserInfo(BaseModel):
    id: int
    username: str
    model_config = {"from_attributes": True}

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: Optional[AuthUserInfo] = None


class UserResponse(BaseModel):
    id: int
    username: str
    theme: str
    sound_enabled: bool
    popup_enabled: bool

    model_config = {"from_attributes": True}


class MessageResponse(BaseModel):
    message: str


# ---------- Routes ----------

@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest, db: AsyncSession = Depends(get_db)):
    """Register a new user account with invite code."""
    if body.password != body.confirm_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="密码不一致",
        )

    # Validate invite code
    from app.models.invite_code import InviteCode
    from datetime import datetime

    invite_result = await db.execute(
        select(InviteCode).where(
            InviteCode.code == body.invite_code.strip(),
            InviteCode.is_used == False,
        )
    )
    invite = invite_result.scalar_one_or_none()
    if invite is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="邀请码无效或已被使用",
        )

    result = await db.execute(select(User).where(User.username == body.username))
    if result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="用户名已存在",
        )

    user = User(
        username=body.username,
        password_hash=hash_password(body.password),
    )
    db.add(user)
    await db.flush()

    # Mark invite code as used
    invite.is_used = True
    invite.used_by = user.id
    invite.used_at = datetime.now()
    await db.commit()

    token = create_access_token(user.id)
    return TokenResponse(
        access_token=token,
        user=AuthUserInfo(id=user.id, username=user.username),
    )


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    """Authenticate user and return JWT token."""
    result = await db.execute(select(User).where(User.username == body.username))
    user = result.scalar_one_or_none()

    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    token = create_access_token(user.id)
    return TokenResponse(
        access_token=token,
        user=AuthUserInfo(id=user.id, username=user.username),
    )


@router.post("/logout", response_model=MessageResponse)
async def logout(user: User = Depends(require_auth)):
    """Logout current user (client should discard token)."""
    return MessageResponse(message="Logged out successfully")


@router.get("/me", response_model=UserResponse)
async def get_me(user: User = Depends(require_auth)):
    """Get current authenticated user info."""
    return user
