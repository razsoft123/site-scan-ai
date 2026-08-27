from fastapi import Request, status
from fastapi.responses import JSONResponse

from app.core.exceptions.audit import (
    AuditDatabaseError,
    AuditNotFoundError,
    InvalidAuditTransitionError,
    UnsafeAuditUrlError,
)


async def audit_not_found_handler(
    _: Request,
    __: AuditNotFoundError,
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content={"detail": "Audit not found."},
    )


async def unsafe_audit_url_handler(
    _: Request,
    exc: UnsafeAuditUrlError,
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={"detail": str(exc) or "The target URL is not safe to scan."},
    )


async def invalid_audit_transition_handler(
    _: Request,
    exc: InvalidAuditTransitionError,
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={"detail": str(exc) or "Invalid audit status transition."},
    )


async def audit_database_error_handler(
    _: Request,
    __: AuditDatabaseError,
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"detail": "The audit service is temporarily unavailable."},
    )
