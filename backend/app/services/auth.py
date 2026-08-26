from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions.user import (
    EmailAlreadyRegisteredError,
    InactiveUserError,
    InvalidAccessTokenError,
    InvalidCredentialsError,
)
from app.core.security import (
    decode_access_token,
    dummy_password_hash,
    hash_password,
    verify_password,
)
from app.db.database import get_db
from app.models.user import User
from app.schemas.user import CreateUser


bearer_scheme = HTTPBearer(auto_error=False)


def get_user_by_email(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(User.email == email))


def register_user(db: Session, user_data: CreateUser) -> User:
    email = str(user_data.email)
    if get_user_by_email(db, email) is not None:
        raise EmailAlreadyRegisteredError

    user = User(
        name=user_data.name,
        email=email,
        password_hash=hash_password(user_data.password),
    )
    db.add(user)

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise EmailAlreadyRegisteredError from exc

    db.refresh(user)
    return user


def authenticate_user(db: Session, email: str, password: str) -> User:
    user = get_user_by_email(db, email)
    password_hash = user.password_hash if user is not None else dummy_password_hash
    password_is_valid = verify_password(password, password_hash)

    if user is None or not password_is_valid:
        raise InvalidCredentialsError
    if not user.is_active:
        raise InactiveUserError

    return user


def get_current_user(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(bearer_scheme),
    ],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise InvalidAccessTokenError

    user_id = decode_access_token(credentials.credentials)
    user = db.get(User, user_id)

    if user is None:
        raise InvalidAccessTokenError
    if not user.is_active:
        raise InactiveUserError

    return user
