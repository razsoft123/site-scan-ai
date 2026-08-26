from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import create_access_token
from app.db.database import get_db
from app.models.user import User
from app.schemas.user import AuthUser, CreateUser, ResponseUser, TokenResponse
from app.services.auth import authenticate_user, get_current_user, register_user

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/register",
    response_model=ResponseUser,
    status_code=status.HTTP_201_CREATED,
)
def create_user(
    user_data: CreateUser,
    db: Annotated[Session, Depends(get_db)],
) -> User:
    return register_user(db, user_data)


@router.post("/login", response_model=TokenResponse)
def login_user(
    credentials: AuthUser,
    db: Annotated[Session, Depends(get_db)],
) -> TokenResponse:
    user = authenticate_user(db, str(credentials.email), credentials.password)
    settings = get_settings()
    return TokenResponse(
        access_token=create_access_token(user.id),
        expires_in=settings.access_token_expire_minutes * 60,
    )


@router.get("/me", response_model=ResponseUser)
def get_login_user(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    return current_user
