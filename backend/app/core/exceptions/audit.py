class AuditNotFoundError(Exception):
    """Raised when an audit is missing or does not belong to the current user."""


class UnsafeAuditUrlError(Exception):
    """Raised when an audit target is not safe for a public website scan."""


class InvalidAuditTransitionError(Exception):
    """Raised when an audit lifecycle transition is not allowed."""


class AuditDatabaseError(Exception):
    """Raised when an audit operation cannot be persisted or retrieved."""
