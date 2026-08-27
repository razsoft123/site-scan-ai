from time import perf_counter
from urllib.parse import urljoin, urlsplit

import httpx

from app.schemas.tool import ToolError, ToolResult
from app.tools.http_safety import (
    DEFAULT_MAX_REDIRECTS,
    DEFAULT_TIMEOUT_SECONDS,
    REDIRECT_STATUS_CODES,
    validate_target_url,
)


TOOL_NAME = "inspect_security_headers"
REQUIRED_HEADERS = {
    "content_security_policy": "Content-Security-Policy",
    "strict_transport_security": "Strict-Transport-Security",
    "x_content_type_options": "X-Content-Type-Options",
    "referrer_policy": "Referrer-Policy",
    "permissions_policy": "Permissions-Policy",
}


def _duration_ms(started_at: float) -> int:
    return max(0, int((perf_counter() - started_at) * 1000))


def _result(
    started_at: float,
    *,
    success: bool,
    data: dict[str, object] | None = None,
    errors: list[ToolError] | None = None,
) -> ToolResult:
    return ToolResult(
        tool=TOOL_NAME,
        success=success,
        duration_ms=_duration_ms(started_at),
        data=data or {},
        errors=errors or [],
    )


def _header_value(headers: httpx.Headers, name: str) -> str | None:
    value = headers.get(name)
    if value is None or not value.strip():
        return None
    return value.strip()


def _frame_ancestors_directive(csp: str | None) -> str | None:
    if csp is None:
        return None

    for directive in csp.split(";"):
        parts = directive.strip().split()
        if parts and parts[0].casefold() == "frame-ancestors":
            return " ".join(parts[1:])
    return None


def _security_header_evidence(
    headers: httpx.Headers,
    final_url: str,
) -> dict[str, object]:
    values = {
        key: _header_value(headers, header_name)
        for key, header_name in REQUIRED_HEADERS.items()
    }
    x_frame_options = _header_value(headers, "X-Frame-Options")
    x_frame_options_valid = (
        x_frame_options is not None
        and x_frame_options.casefold() in {"deny", "sameorigin"}
    )
    frame_ancestors = _frame_ancestors_directive(
        values["content_security_policy"]
    )
    frame_ancestor_sources = (
        frame_ancestors.casefold().split() if frame_ancestors is not None else []
    )
    csp_frame_protection = (
        bool(frame_ancestor_sources) and "*" not in frame_ancestor_sources
    )

    mechanisms: list[str] = []
    if x_frame_options_valid:
        mechanisms.append("x-frame-options")
    if csp_frame_protection:
        mechanisms.append("csp-frame-ancestors")

    missing_headers = [
        header_name
        for key, header_name in REQUIRED_HEADERS.items()
        if values[key] is None
    ]
    if not mechanisms:
        missing_headers.append("Frame-Protection")

    final_scheme = urlsplit(final_url).scheme.casefold()
    return {
        **values,
        "x_frame_options": x_frame_options,
        "csp_frame_ancestors": frame_ancestors,
        "strict_transport_security_effective": bool(
            values["strict_transport_security"] and final_scheme == "https"
        ),
        "x_content_type_options_nosniff": (
            values["x_content_type_options"] is not None
            and values["x_content_type_options"].casefold() == "nosniff"
        ),
        "frame_protection": {
            "protected": bool(mechanisms),
            "mechanisms": mechanisms,
            "x_frame_options_valid": x_frame_options_valid,
            "csp_frame_ancestors_present": frame_ancestors is not None,
        },
        "missing_headers": missing_headers,
    }


def inspect_security_headers(
    url: str,
    *,
    client: httpx.Client | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    max_redirects: int = DEFAULT_MAX_REDIRECTS,
) -> ToolResult:
    started_at = perf_counter()
    try:
        requested_url = validate_target_url(url)
    except ValueError as exc:
        return _result(
            started_at,
            success=False,
            errors=[ToolError(code="invalid_url", message=str(exc))],
        )

    if timeout_seconds <= 0 or max_redirects < 0:
        return _result(
            started_at,
            success=False,
            errors=[
                ToolError(
                    code="invalid_configuration",
                    message="Timeout must be positive and redirects cannot be negative.",
                )
            ],
        )

    owns_client = client is None
    http_client = client or httpx.Client()
    current_url = requested_url
    redirect_count = 0

    try:
        while True:
            with http_client.stream(
                "GET",
                current_url,
                follow_redirects=False,
                timeout=timeout_seconds,
                headers={
                    "Accept": "text/html,application/xhtml+xml,*/*;q=0.1",
                    "User-Agent": "SiteScanAI/1.0 security-header-inspector",
                },
            ) as response:
                if response.status_code in REDIRECT_STATUS_CODES:
                    location = response.headers.get("location")
                    redirect_data = {
                        "requested_url": requested_url,
                        "final_url": str(response.url),
                        "http_status": response.status_code,
                        "redirect_count": redirect_count,
                    }
                    if not location:
                        return _result(
                            started_at,
                            success=False,
                            data=redirect_data,
                            errors=[
                                ToolError(
                                    code="redirect_missing_location",
                                    message="The redirect response did not include a location.",
                                )
                            ],
                        )
                    if redirect_count >= max_redirects:
                        return _result(
                            started_at,
                            success=False,
                            data=redirect_data,
                            errors=[
                                ToolError(
                                    code="too_many_redirects",
                                    message="The response exceeded the redirect limit.",
                                )
                            ],
                        )

                    redirected_url = urljoin(str(response.url), location)
                    try:
                        current_url = validate_target_url(redirected_url)
                    except ValueError as exc:
                        return _result(
                            started_at,
                            success=False,
                            data=redirect_data,
                            errors=[
                                ToolError(code="unsafe_redirect", message=str(exc))
                            ],
                        )
                    redirect_count += 1
                    continue

                data: dict[str, object] = {
                    "requested_url": requested_url,
                    "final_url": str(response.url),
                    "redirected": redirect_count > 0,
                    "redirect_count": redirect_count,
                    "http_status": response.status_code,
                    **_security_header_evidence(response.headers, str(response.url)),
                }
                if not 200 <= response.status_code < 300:
                    return _result(
                        started_at,
                        success=False,
                        data=data,
                        errors=[
                            ToolError(
                                code="http_status_error",
                                message=(
                                    "The target returned HTTP status "
                                    f"{response.status_code}."
                                ),
                            )
                        ],
                    )

                return _result(started_at, success=True, data=data)
    except httpx.TimeoutException:
        return _result(
            started_at,
            success=False,
            data={"requested_url": requested_url, "final_url": current_url},
            errors=[
                ToolError(
                    code="timeout",
                    message="The security-header request timed out.",
                )
            ],
        )
    except httpx.RequestError as exc:
        return _result(
            started_at,
            success=False,
            data={"requested_url": requested_url, "final_url": current_url},
            errors=[
                ToolError(
                    code="request_error",
                    message=f"The security-header request failed: {exc}",
                )
            ],
        )
    finally:
        if owns_client:
            http_client.close()
