"""Authentication routes."""
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.auth import (
    verify_password,
    create_access_token,
    get_current_admin,
    ACCESS_TOKEN_EXPIRE_MINUTES,
)
from backend.database import get_db
from backend.models.db_models import Admin as DBAdmin
from backend.schemas.auth import LoginRequest, TokenResponse

router = APIRouter(prefix="/api/auth", tags=["Authentication"])


@router.post("/login", response_model=TokenResponse)
async def login(login_data: LoginRequest, db: Session = Depends(get_db)):
    """Admin login endpoint."""
    admin = db.query(DBAdmin).filter(DBAdmin.username == login_data.username).first()

    if not admin or not verify_password(login_data.password, admin.password_hash):
        raise HTTPException(
            status_code=401,
            detail="Incorrect username or password",
        )

    if not admin.is_active:
        raise HTTPException(
            status_code=403,
            detail="Admin account is inactive",
        )

    # Update last login
    admin.last_login = datetime.now()
    db.commit()

    # Create access token
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": admin.username},
        expires_delta=access_token_expires,
    )

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "username": admin.username,
    }


@router.get("/me")
async def get_current_user_info(current_admin: DBAdmin = Depends(get_current_admin)):
    """Get current authenticated admin info."""
    return {
        "admin_id": current_admin.admin_id,
        "username": current_admin.username,
        "email": current_admin.email,
        "is_active": current_admin.is_active,
    }
