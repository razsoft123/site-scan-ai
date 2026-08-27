from time import perf_counter
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup
from bs4.element import Tag

from app.schemas.tool import ToolError, ToolResult
from app.tools.http_safety import (
    DEFAULT_MAX_REDIRECTS,
    DEFAULT_TIMEOUT_SECONDS,
    REDIRECT_STATUS_CODES,
    validate_target_url,
)


TOOL_NAME = "inspect_metadata"
DEFAULT_MAX_RESPONSE_BYTES = 2_000_000
HTML_MEDIA_TYPES = {"text/html", "application/xhtml+xml"}


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


def _meta_content(soup: BeautifulSoup, attribute: str, expected: str) -> str | None:
    for element in soup.find_all("meta"):
        if not isinstance(element, Tag):
            continue
        attribute_value = element.get(attribute)
        if not isinstance(attribute_value, str):
            continue
        if attribute_value.casefold() != expected.casefold():
            continue
        content = element.get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()
    return None


def _robots_content(soup: BeautifulSoup) -> str | None:
    values: list[str] = []
    for element in soup.find_all("meta"):
        if not isinstance(element, Tag):
            continue
        name = element.get("name")
        content = element.get("content")
        if (
            isinstance(name, str)
            and name.casefold() == "robots"
            and isinstance(content, str)
            and content.strip()
        ):
            value = content.strip()
            if value not in values:
                values.append(value)
    return ", ".join(values) if values else None


def _canonical_url(soup: BeautifulSoup, final_url: str) -> str | None:
    for element in soup.find_all("link"):
        if not isinstance(element, Tag):
            continue
        relationship = element.get("rel", [])
        relationship_values = (
            relationship.split() if isinstance(relationship, str) else relationship
        )
        if not any(str(value).casefold() == "canonical" for value in relationship_values):
            continue
        href = element.get("href")
        if isinstance(href, str) and href.strip():
            return urljoin(final_url, href.strip())
    return None


def _extract_metadata(content: bytes, final_url: str) -> dict[str, object]:
    soup = BeautifulSoup(content, "html.parser")
    title = None
    if soup.title is not None:
        title_text = soup.title.get_text(" ", strip=True)
        title = title_text or None

    heading_counts = {
        f"h{level}_count": len(soup.find_all(f"h{level}"))
        for level in range(1, 7)
    }
    images = soup.find_all("img")
    images_without_alt = sum(
        1
        for image in images
        if isinstance(image, Tag) and not image.has_attr("alt")
    )
    html_language = None
    if soup.html is not None:
        language = soup.html.get("lang")
        if isinstance(language, str) and language.strip():
            html_language = language.strip()

    return {
        "title": title,
        "meta_description": _meta_content(soup, "name", "description"),
        "canonical_url": _canonical_url(soup, final_url),
        "robots": _robots_content(soup),
        "viewport": _meta_content(soup, "name", "viewport"),
        "open_graph_title": _meta_content(soup, "property", "og:title"),
        "open_graph_description": _meta_content(
            soup,
            "property",
            "og:description",
        ),
        **heading_counts,
        "image_count": len(images),
        "images_without_alt": images_without_alt,
        "html_language": html_language,
    }


def inspect_metadata(
    url: str,
    *,
    client: httpx.Client | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
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

    if timeout_seconds <= 0 or max_response_bytes <= 0 or max_redirects < 0:
        return _result(
            started_at,
            success=False,
            errors=[
                ToolError(
                    code="invalid_configuration",
                    message="Timeout and response limits must be positive.",
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
                    "Accept": "text/html,application/xhtml+xml",
                    "User-Agent": "SiteScanAI/1.0 metadata-inspector",
                },
            ) as response:
                if response.status_code in REDIRECT_STATUS_CODES:
                    location = response.headers.get("location")
                    if not location:
                        return _result(
                            started_at,
                            success=False,
                            data={
                                "requested_url": requested_url,
                                "final_url": str(response.url),
                                "http_status": response.status_code,
                                "redirect_count": redirect_count,
                            },
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
                            data={
                                "requested_url": requested_url,
                                "final_url": str(response.url),
                                "http_status": response.status_code,
                                "redirect_count": redirect_count,
                            },
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
                            data={
                                "requested_url": requested_url,
                                "final_url": str(response.url),
                                "http_status": response.status_code,
                                "redirect_count": redirect_count,
                            },
                            errors=[
                                ToolError(
                                    code="unsafe_redirect",
                                    message=str(exc),
                                )
                            ],
                        )
                    redirect_count += 1
                    continue

                content_type = response.headers.get("content-type", "")
                media_type = content_type.split(";", 1)[0].strip().lower()
                base_data: dict[str, object] = {
                    "requested_url": requested_url,
                    "final_url": str(response.url),
                    "redirected": redirect_count > 0,
                    "redirect_count": redirect_count,
                    "http_status": response.status_code,
                    "content_type": media_type or None,
                }

                declared_length = response.headers.get("content-length")
                if declared_length and declared_length.isdigit():
                    if int(declared_length) > max_response_bytes:
                        base_data["page_size_bytes"] = int(declared_length)
                        return _result(
                            started_at,
                            success=False,
                            data=base_data,
                            errors=[
                                ToolError(
                                    code="response_too_large",
                                    message="The response exceeded the configured size limit.",
                                )
                            ],
                        )

                body = bytearray()
                for chunk in response.iter_bytes():
                    if len(body) + len(chunk) > max_response_bytes:
                        base_data["page_size_bytes"] = len(body) + len(chunk)
                        return _result(
                            started_at,
                            success=False,
                            data=base_data,
                            errors=[
                                ToolError(
                                    code="response_too_large",
                                    message="The response exceeded the configured size limit.",
                                )
                            ],
                        )
                    body.extend(chunk)

                base_data["page_size_bytes"] = len(body)
                if media_type not in HTML_MEDIA_TYPES:
                    return _result(
                        started_at,
                        success=False,
                        data=base_data,
                        errors=[
                            ToolError(
                                code="non_html_response",
                                message="The target did not return an HTML document.",
                            )
                        ],
                    )

                try:
                    metadata = _extract_metadata(bytes(body), str(response.url))
                except Exception as exc:
                    return _result(
                        started_at,
                        success=False,
                        data=base_data,
                        errors=[
                            ToolError(
                                code="parse_error",
                                message=f"The HTML document could not be parsed: {exc}",
                            )
                        ],
                    )

                data = {**base_data, **metadata}
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
                    message="The metadata request timed out.",
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
                    message=f"The metadata request failed: {exc}",
                )
            ],
        )
    finally:
        if owns_client:
            http_client.close()
