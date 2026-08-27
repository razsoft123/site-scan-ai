import asyncio
import socket
from collections.abc import Callable, Sequence
from ipaddress import ip_address
from urllib.parse import urlsplit

import httpx


DEFAULT_TIMEOUT_SECONDS = 10.0
DEFAULT_MAX_REDIRECTS = 5
REDIRECT_STATUS_CODES = {301, 302, 303, 307, 308}
BLOCKED_HOST_SUFFIXES = (".internal", ".lan", ".local", ".localhost")
HostResolver = Callable[[str, int], Sequence[str]]


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


def resolve_hostname(hostname: str, port: int) -> list[str]:
    addresses = {
        sockaddr[0]
        for _, _, _, _, sockaddr in socket.getaddrinfo(
            hostname,
            port,
            type=socket.SOCK_STREAM,
        )
    }
    return sorted(addresses)


def validate_public_url(
    url: str,
    resolver: HostResolver | None = None,
) -> str:
    normalized_url = validate_target_url(url)
    parsed = urlsplit(normalized_url)
    hostname = parsed.hostname
    if hostname is None:
        raise ValueError("The target URL must contain a hostname.")

    try:
        address = ip_address(hostname)
    except ValueError:
        pass
    else:
        if not address.is_global:
            raise ValueError("Private and non-public IP addresses cannot be inspected.")
        return normalized_url

    port = parsed.port or (443 if parsed.scheme.casefold() == "https" else 80)
    active_resolver = resolver or resolve_hostname
    try:
        resolved_addresses = active_resolver(hostname, port)
    except OSError as exc:
        raise ValueError("The target hostname could not be resolved.") from exc

    if not resolved_addresses:
        raise ValueError("The target hostname did not resolve to an IP address.")

    for resolved_address in resolved_addresses:
        address_text = resolved_address.split("%", 1)[0]
        try:
            address = ip_address(address_text)
        except ValueError as exc:
            raise ValueError("The target hostname resolved to an invalid address.") from exc
        if not address.is_global:
            raise ValueError(
                "The target hostname resolves to a private or non-public address."
            )

    return normalized_url


async def validate_public_url_async(
    url: str,
    resolver: HostResolver | None = None,
) -> str:
    return await asyncio.to_thread(validate_public_url, url, resolver)
