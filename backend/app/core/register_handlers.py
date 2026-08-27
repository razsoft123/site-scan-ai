from fastapi import FastAPI

from app.core.exceptions.audit import (
    AuditDatabaseError,
    AuditNotFoundError,
    InvalidAuditTransitionError,
    UnsafeAuditUrlError,
)
from app.core.exceptions.user import (
    EmailAlreadyRegisteredError,
    InactiveUserError,
    InvalidAccessTokenError,
    InvalidCredentialsError,
)
from app.core.handlers.audit import (
    audit_database_error_handler,
    audit_not_found_handler,
    invalid_audit_transition_handler,
    unsafe_audit_url_handler,
)
from app.core.handlers.user import (
    email_already_registered_handler,
    inactive_user_handler,
    invalid_access_token_handler,
    invalid_credentials_handler,
)


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(
        EmailAlreadyRegisteredError,
        email_already_registered_handler,
    )
    app.add_exception_handler(InvalidCredentialsError, invalid_credentials_handler)
    app.add_exception_handler(InactiveUserError, inactive_user_handler)
    app.add_exception_handler(InvalidAccessTokenError, invalid_access_token_handler)
    app.add_exception_handler(AuditNotFoundError, audit_not_found_handler)
    app.add_exception_handler(UnsafeAuditUrlError, unsafe_audit_url_handler)
    app.add_exception_handler(
        InvalidAuditTransitionError,
        invalid_audit_transition_handler,
    )
    app.add_exception_handler(AuditDatabaseError, audit_database_error_handler)
