class EmailAlreadyRegisteredError(Exception):
    """Raised when an account already exists for an email address."""


class InvalidCredentialsError(Exception):
    """Raised when login credentials cannot be authenticated."""


class InactiveUserError(Exception):
    """Raised when an inactive account attempts an authenticated action."""


class InvalidAccessTokenError(Exception):
    """Raised when an access token is missing, invalid, or expired."""
