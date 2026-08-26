from datetime import datetime, timedelta, timezone

import jwt
from jwt.exceptions import InvalidTokenError as PyJWTInvalidTokenError
from pwdlib import PasswordHash

from app.core.config import get_settings
from app.core.exceptions.user import InvalidAccessTokenError


password_hasher = PasswordHash.recommended()
dummy_password_hash = password_hasher.hash("not-a-real-user-password")


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return password_hasher.verify(password, password_hash)


def create_access_token(user_id: int) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=settings.access_token_expire_minutes)
    payload = {
        "sub": str(user_id),
        "type": "access",
        "iat": now,
        "exp": expires_at,
    }
    return jwt.encode(
        payload,
        settings.jwt_secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )


def decode_access_token(token: str) -> int:
    settings = get_settings()

    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
        )
        if payload.get("type") != "access":
            raise InvalidAccessTokenError

        subject = payload.get("sub")
        if subject is None:
            raise InvalidAccessTokenError

        return int(subject)
    except (PyJWTInvalidTokenError, TypeError, ValueError) as exc:
        raise InvalidAccessTokenError from exc
