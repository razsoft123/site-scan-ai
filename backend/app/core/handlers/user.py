from fastapi import Request, status
from fastapi.responses import JSONResponse

from app.core.exceptions.user import (
    EmailAlreadyRegisteredError,
    InactiveUserError,
    InvalidAccessTokenError,
    InvalidCredentialsError,
)


async def email_already_registered_handler(
    _: Request,
    __: EmailAlreadyRegisteredError,
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={"detail": "An account with this email already exists."},
    )


async def invalid_credentials_handler(
    _: Request,
    __: InvalidCredentialsError,
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_401_UNAUTHORIZED,
        content={"detail": "Invalid email or password."},
        headers={"WWW-Authenticate": "Bearer"},
    )


async def inactive_user_handler(
    _: Request,
    __: InactiveUserError,
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_403_FORBIDDEN,
        content={"detail": "This account is inactive."},
    )


async def invalid_access_token_handler(
    _: Request,
    __: InvalidAccessTokenError,
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_401_UNAUTHORIZED,
        content={"detail": "Could not validate authentication credentials."},
        headers={"WWW-Authenticate": "Bearer"},
    )
