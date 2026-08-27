import asyncio
from dataclasses import dataclass
from time import perf_counter
from urllib.parse import urldefrag, urljoin, urlsplit

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


TOOL_NAME = "check_broken_links"
MAX_LINKS = 25
DEFAULT_CONCURRENCY_LIMIT = 5
MAX_CONCURRENCY_LIMIT = 10
DEFAULT_MAX_RESPONSE_BYTES = 2_000_000
HTML_MEDIA_TYPES = {"text/html", "application/xhtml+xml"}


@dataclass(frozen=True)
class _SourcePage:
    requested_url: str
    final_url: str
    http_status: int
    redirect_count: int
    content: bytes


class _SourcePageError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        data: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.data = data or {}


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


async def _fetch_source_page(
    client: httpx.AsyncClient,
    requested_url: str,
    *,
    timeout_seconds: float,
    max_response_bytes: int,
    max_redirects: int,
) -> _SourcePage:
    current_url = requested_url
    redirect_count = 0

    while True:
        async with client.stream(
            "GET",
            current_url,
            follow_redirects=False,
            timeout=timeout_seconds,
            headers={
                "Accept": "text/html,application/xhtml+xml",
                "User-Agent": "SiteScanAI/1.0 broken-link-checker",
            },
        ) as response:
            base_data: dict[str, object] = {
                "source_url": requested_url,
                "final_url": str(response.url),
                "source_http_status": response.status_code,
                "source_redirect_count": redirect_count,
            }
            if response.status_code in REDIRECT_STATUS_CODES:
                location = response.headers.get("location")
                if not location:
                    raise _SourcePageError(
                        "redirect_missing_location",
                        "The source page redirect did not include a location.",
                        base_data,
                    )
                if redirect_count >= max_redirects:
                    raise _SourcePageError(
                        "too_many_redirects",
                        "The source page exceeded the redirect limit.",
                        base_data,
                    )

                redirected_url = urljoin(str(response.url), location)
                try:
                    current_url = validate_target_url(redirected_url)
                except ValueError as exc:
                    raise _SourcePageError(
                        "unsafe_redirect",
                        str(exc),
                        base_data,
                    ) from exc
                redirect_count += 1
                continue

            if not 200 <= response.status_code < 300:
                raise _SourcePageError(
                    "source_page_http_error",
                    f"The source page returned HTTP status {response.status_code}.",
                    base_data,
                )

            content_type = response.headers.get("content-type", "")
            media_type = content_type.split(";", 1)[0].strip().lower()
            base_data["content_type"] = media_type or None
            if media_type not in HTML_MEDIA_TYPES:
                raise _SourcePageError(
                    "non_html_source",
                    "The source page did not return an HTML document.",
                    base_data,
                )

            declared_length = response.headers.get("content-length")
            if declared_length and declared_length.isdigit():
                if int(declared_length) > max_response_bytes:
                    base_data["page_size_bytes"] = int(declared_length)
                    raise _SourcePageError(
                        "source_page_too_large",
                        "The source page exceeded the configured size limit.",
                        base_data,
                    )

            body = bytearray()
            async for chunk in response.aiter_bytes():
                if len(body) + len(chunk) > max_response_bytes:
                    base_data["page_size_bytes"] = len(body) + len(chunk)
                    raise _SourcePageError(
                        "source_page_too_large",
                        "The source page exceeded the configured size limit.",
                        base_data,
                    )
                body.extend(chunk)

            return _SourcePage(
                requested_url=requested_url,
                final_url=str(response.url),
                http_status=response.status_code,
                redirect_count=redirect_count,
                content=bytes(body),
            )


def _extract_links(
    content: bytes,
    base_url: str,
) -> tuple[list[str], list[dict[str, str]], int, int]:
    soup = BeautifulSoup(content, "html.parser")
    valid_links: list[str] = []
    skipped_unsafe: list[dict[str, str]] = []
    seen: set[str] = set()
    ignored_non_http = 0
    extracted_links = 0

    for element in soup.find_all("a"):
        if not isinstance(element, Tag) or not element.has_attr("href"):
            continue
        extracted_links += 1
        href = element.get("href")
        if not isinstance(href, str) or not href.strip():
            ignored_non_http += 1
            continue

        raw_href = href.strip()
        if raw_href.startswith("#"):
            ignored_non_http += 1
            continue

        absolute_url, _ = urldefrag(urljoin(base_url, raw_href))
        try:
            parsed = urlsplit(absolute_url)
        except ValueError:
            ignored_non_http += 1
            continue
        if parsed.scheme.casefold() not in {"http", "https"}:
            ignored_non_http += 1
            continue

        try:
            normalized_url = str(httpx.URL(absolute_url))
        except httpx.InvalidURL:
            ignored_non_http += 1
            continue
        if normalized_url in seen:
            continue
        seen.add(normalized_url)

        try:
            valid_links.append(validate_target_url(normalized_url))
        except ValueError as exc:
            skipped_unsafe.append(
                {"url": normalized_url, "reason": str(exc)}
            )

    return valid_links, skipped_unsafe, ignored_non_http, extracted_links


async def _check_link(
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    url: str,
    *,
    timeout_seconds: float,
    max_redirects: int,
) -> dict[str, object]:
    async with semaphore:
        current_url = url
        redirect_count = 0

        try:
            while True:
                async with client.stream(
                    "GET",
                    current_url,
                    follow_redirects=False,
                    timeout=timeout_seconds,
                    headers={
                        "Accept": "*/*",
                        "User-Agent": "SiteScanAI/1.0 broken-link-checker",
                    },
                ) as response:
                    if response.status_code in REDIRECT_STATUS_CODES:
                        location = response.headers.get("location")
                        if not location:
                            return {
                                "url": url,
                                "final_url": str(response.url),
                                "status_code": response.status_code,
                                "classification": "broken",
                                "redirect_count": redirect_count,
                                "error_code": "redirect_missing_location",
                                "error_message": (
                                    "The redirect response did not include a location."
                                ),
                            }
                        if redirect_count >= max_redirects:
                            return {
                                "url": url,
                                "final_url": str(response.url),
                                "status_code": response.status_code,
                                "classification": "broken",
                                "redirect_count": redirect_count,
                                "error_code": "too_many_redirects",
                                "error_message": "The link exceeded the redirect limit.",
                            }

                        redirected_url = urljoin(str(response.url), location)
                        try:
                            current_url = validate_target_url(redirected_url)
                        except ValueError as exc:
                            return {
                                "url": url,
                                "final_url": str(response.url),
                                "status_code": response.status_code,
                                "classification": "broken",
                                "redirect_count": redirect_count,
                                "error_code": "unsafe_redirect",
                                "error_message": str(exc),
                            }
                        redirect_count += 1
                        continue

                    classification = (
                        "redirected"
                        if 200 <= response.status_code < 300 and redirect_count > 0
                        else "working"
                        if 200 <= response.status_code < 300
                        else "broken"
                    )
                    return {
                        "url": url,
                        "final_url": str(response.url),
                        "status_code": response.status_code,
                        "classification": classification,
                        "redirect_count": redirect_count,
                        "error_code": (
                            None
                            if classification != "broken"
                            else "http_status_error"
                        ),
                        "error_message": (
                            None
                            if classification != "broken"
                            else f"The link returned HTTP status {response.status_code}."
                        ),
                    }
        except httpx.TimeoutException:
            return {
                "url": url,
                "final_url": current_url,
                "status_code": None,
                "classification": "timed_out",
                "redirect_count": redirect_count,
                "error_code": "timeout",
                "error_message": "The link request timed out.",
            }
        except httpx.RequestError as exc:
            return {
                "url": url,
                "final_url": current_url,
                "status_code": None,
                "classification": "broken",
                "redirect_count": redirect_count,
                "error_code": "request_error",
                "error_message": f"The link request failed: {exc}",
            }


async def check_broken_links(
    url: str,
    *,
    client: httpx.AsyncClient | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
    max_links: int = MAX_LINKS,
    concurrency_limit: int = DEFAULT_CONCURRENCY_LIMIT,
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

    if (
        timeout_seconds <= 0
        or max_response_bytes <= 0
        or not 1 <= max_links <= MAX_LINKS
        or not 1 <= concurrency_limit <= MAX_CONCURRENCY_LIMIT
        or max_redirects < 0
    ):
        return _result(
            started_at,
            success=False,
            errors=[
                ToolError(
                    code="invalid_configuration",
                    message=(
                        "Use positive timeout/size values, 1-25 links, "
                        "1-10 concurrent requests, and non-negative redirects."
                    ),
                )
            ],
        )

    owns_client = client is None
    http_client = client or httpx.AsyncClient()

    try:
        try:
            source_page = await _fetch_source_page(
                http_client,
                requested_url,
                timeout_seconds=timeout_seconds,
                max_response_bytes=max_response_bytes,
                max_redirects=max_redirects,
            )
        except _SourcePageError as exc:
            return _result(
                started_at,
                success=False,
                data=exc.data,
                errors=[ToolError(code=exc.code, message=str(exc))],
            )
        except httpx.TimeoutException:
            return _result(
                started_at,
                success=False,
                data={"source_url": requested_url},
                errors=[
                    ToolError(
                        code="source_page_timeout",
                        message="The source page request timed out.",
                    )
                ],
            )
        except httpx.RequestError as exc:
            return _result(
                started_at,
                success=False,
                data={"source_url": requested_url},
                errors=[
                    ToolError(
                        code="source_page_request_error",
                        message=f"The source page request failed: {exc}",
                    )
                ],
            )

        try:
            (
                valid_links,
                skipped_links,
                ignored_non_http,
                extracted_links,
            ) = _extract_links(source_page.content, source_page.final_url)
        except Exception as exc:
            return _result(
                started_at,
                success=False,
                data={
                    "source_url": source_page.requested_url,
                    "final_url": source_page.final_url,
                    "source_http_status": source_page.http_status,
                },
                errors=[
                    ToolError(
                        code="link_extraction_error",
                        message=f"Links could not be extracted from the page: {exc}",
                    )
                ],
            )

        selected_links = valid_links[:max_links]
        semaphore = asyncio.Semaphore(concurrency_limit)
        link_results = await asyncio.gather(
            *(
                _check_link(
                    http_client,
                    semaphore,
                    link,
                    timeout_seconds=timeout_seconds,
                    max_redirects=max_redirects,
                )
                for link in selected_links
            )
        )
        classifications = [str(result["classification"]) for result in link_results]
        data: dict[str, object] = {
            "source_url": source_page.requested_url,
            "final_url": source_page.final_url,
            "source_http_status": source_page.http_status,
            "source_redirect_count": source_page.redirect_count,
            "extracted_links": extracted_links,
            "unique_links": len(valid_links) + len(skipped_links),
            "checked": len(link_results),
            "working": classifications.count("working"),
            "redirected": classifications.count("redirected"),
            "broken": classifications.count("broken"),
            "timed_out": classifications.count("timed_out"),
            "skipped_unsafe": len(skipped_links),
            "ignored_non_http": ignored_non_http,
            "unchecked_due_to_limit": max(0, len(valid_links) - max_links),
            "links": link_results,
            "skipped_links": skipped_links,
        }
        return _result(started_at, success=True, data=data)
    finally:
        if owns_client:
            await http_client.aclose()
