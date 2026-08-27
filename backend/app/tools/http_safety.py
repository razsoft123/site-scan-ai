from ipaddress import ip_address
from urllib.parse import urlsplit

import httpx


DEFAULT_TIMEOUT_SECONDS = 10.0
DEFAULT_MAX_REDIRECTS = 5
REDIRECT_STATUS_CODES = {301, 302, 303, 307, 308}
BLOCKED_HOST_SUFFIXES = (".internal", ".lan", ".local", ".localhost")


def validate_target_url(url: str) -> str:
    try:
        parsed = urlsplit(url)
        hostname = parsed.hostname
    except ValueError as exc:
        raise ValueError("The target URL is malformed.") from exc

    if parsed.scheme.lower() not in {"http", "https"}:
        raise ValueError("Only HTTP and HTTPS URLs can be inspected.")
    if hostname is None:
        raise ValueError("The target URL must contain a hostname.")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("URLs containing credentials cannot be inspected.")

    hostname = hostname.lower().rstrip(".")
    if (
        hostname == "localhost"
        or hostname.endswith(BLOCKED_HOST_SUFFIXES)
        or ("." not in hostname and ":" not in hostname)
    ):
        raise ValueError("Local and internal hostnames cannot be inspected.")

    try:
        address = ip_address(hostname)
    except ValueError:
        pass
    else:
        if not address.is_global:
            raise ValueError("Private and non-public IP addresses cannot be inspected.")

    try:
        return str(httpx.URL(url))
    except httpx.InvalidURL as exc:
        raise ValueError("The target URL is malformed.") from exc
