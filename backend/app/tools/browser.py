import asyncio
from collections.abc import Callable
from pathlib import Path
from time import perf_counter
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

from playwright.async_api import (
    Error as PlaywrightError,
    TimeoutError as PlaywrightTimeoutError,
    async_playwright,
)

from app.schemas.tool import ToolError, ToolResult
from app.tools.http_safety import (
    DEFAULT_MAX_REDIRECTS,
    HostResolver,
    validate_public_url_async,
)


TOOL_NAME = "inspect_browser"
DEFAULT_TIMEOUT_MS = 30_000
DEFAULT_MAX_RESPONSE_BYTES = 10_000_000
DEFAULT_MAX_EVIDENCE_ITEMS = 100
DEFAULT_SCREENSHOT_DIRECTORY = (
    Path(__file__).resolve().parents[2] / "artifacts" / "screenshots"
)
NON_NETWORK_SCHEMES = {"about", "blob", "data"}

# FastAPI normally runs this module on one event loop. The semaphore deliberately
# serializes Chromium work so that a single application process cannot run two
# resource-intensive browser inspections at once.
_BROWSER_SCAN_SEMAPHORE = asyncio.Semaphore(1)


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


def _redirect_count(request: Any) -> int:
    count = 0
    previous = getattr(request, "redirected_from", None)
    seen_requests: set[int] = set()
    while previous is not None and id(previous) not in seen_requests:
        seen_requests.add(id(previous))
        count += 1
        previous = getattr(previous, "redirected_from", None)
    return count


def _request_evidence(request: Any, *, reason: str) -> dict[str, object]:
    return {
        "url": getattr(request, "url", ""),
        "method": getattr(request, "method", "GET"),
        "resource_type": getattr(request, "resource_type", "other"),
        "is_navigation": bool(request.is_navigation_request()),
        "reason": reason,
    }


async def _capture_screenshot(
    page: Any,
    screenshot_directory: Path,
    timeout_ms: int,
) -> str:
    screenshot_directory.mkdir(parents=True, exist_ok=True)
    screenshot_path = (
        screenshot_directory / f"inspect-browser-{uuid4().hex}.png"
    ).resolve()
    await page.screenshot(
        path=str(screenshot_path),
        full_page=True,
        animations="disabled",
        timeout=timeout_ms,
    )
    return str(screenshot_path)


async def inspect_browser(
    url: str,
    *,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
    max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
    max_redirects: int = DEFAULT_MAX_REDIRECTS,
    max_evidence_items: int = DEFAULT_MAX_EVIDENCE_ITEMS,
    screenshot_directory: str | Path = DEFAULT_SCREENSHOT_DIRECTORY,
    resolver: HostResolver | None = None,
    playwright_factory: Callable[[], Any] = async_playwright,
    scan_semaphore: asyncio.Semaphore | None = None,
) -> ToolResult:
    """Inspect a public web page in Chromium and return deterministic evidence."""

    started_at = perf_counter()
    try:
        requested_url = await validate_public_url_async(url, resolver)
    except ValueError as exc:
        return _result(
            started_at,
            success=False,
            errors=[ToolError(code="invalid_url", message=str(exc))],
        )

    if (
        timeout_ms <= 0
        or max_response_bytes <= 0
        or max_redirects < 0
        or max_evidence_items <= 0
    ):
        return _result(
            started_at,
            success=False,
            errors=[
                ToolError(
                    code="invalid_configuration",
                    message=(
                        "Timeout, response size, and evidence limits must be "
                        "positive; the redirect limit cannot be negative."
                    ),
                )
            ],
        )

    console_errors: list[dict[str, object]] = []
    page_errors: list[dict[str, str]] = []
    failed_requests: list[dict[str, object]] = []
    blocked_requests: list[dict[str, object]] = []
    total_failed_requests = 0
    total_blocked_requests = 0
    total_response_bytes = 0
    response_size_exceeded = False
    redirect_limit_exceeded = False
    blocked_main_navigation = False
    screenshot_reference: str | None = None
    screenshot_error: str | None = None
    page: Any = None
    pending_size_tasks: set[asyncio.Task[None]] = set()

    data: dict[str, object] = {
        "requested_url": requested_url,
        "final_url": requested_url,
        "page_load_status": "not_started",
        "http_status": None,
        "redirect_count": 0,
        "title": None,
        "console_errors": console_errors,
        "page_errors": page_errors,
        "failed_network_requests": failed_requests,
        "blocked_requests": blocked_requests,
        "load_duration_ms": 0,
        "total_response_bytes": 0,
        "response_size_limit_bytes": max_response_bytes,
        "screenshot_reference": None,
    }

    async def route_request(route: Any) -> None:
        nonlocal blocked_main_navigation
        nonlocal redirect_limit_exceeded
        nonlocal total_blocked_requests

        request = route.request
        request_url = getattr(request, "url", "")
        scheme = urlsplit(request_url).scheme.casefold()
        reason: str | None = None

        if scheme in NON_NETWORK_SCHEMES:
            await route.continue_()
            return
        if scheme not in {"http", "https"}:
            reason = "non_http_protocol"
        elif _redirect_count(request) > max_redirects:
            reason = "redirect_limit_exceeded"
            redirect_limit_exceeded = True
        else:
            try:
                await validate_public_url_async(request_url, resolver)
            except ValueError:
                reason = "unsafe_network_target"

        if reason is None and not response_size_exceeded:
            await route.continue_()
            return
        if reason is None:
            reason = "response_size_limit_exceeded"

        total_blocked_requests += 1
        if len(blocked_requests) < max_evidence_items:
            blocked_requests.append(_request_evidence(request, reason=reason))
        if request.is_navigation_request():
            blocked_main_navigation = True
        await route.abort(error_code="blockedbyclient")

    async def route_web_socket(web_socket_route: Any) -> None:
        nonlocal total_blocked_requests
        total_blocked_requests += 1
        if len(blocked_requests) < max_evidence_items:
            blocked_requests.append(
                {
                    "url": getattr(web_socket_route, "url", ""),
                    "method": "GET",
                    "resource_type": "websocket",
                    "is_navigation": False,
                    "reason": "websocket_blocked",
                }
            )
        await web_socket_route.close(code=1008, reason="Blocked during inspection")

    def record_console_error(message: Any) -> None:
        if getattr(message, "type", "") != "error":
            return
        if len(console_errors) < max_evidence_items:
            console_errors.append(
                {
                    "text": getattr(message, "text", ""),
                    "location": getattr(message, "location", None),
                }
            )

    def record_page_error(error: Exception) -> None:
        if len(page_errors) < max_evidence_items:
            page_errors.append({"message": str(error)})

    def record_failed_request(request: Any) -> None:
        nonlocal total_failed_requests
        total_failed_requests += 1
        if len(failed_requests) >= max_evidence_items:
            return
        failed_requests.append(
            {
                "url": getattr(request, "url", ""),
                "method": getattr(request, "method", "GET"),
                "resource_type": getattr(request, "resource_type", "other"),
                "error_text": getattr(request, "failure", None),
            }
        )

    async def record_finished_request(request: Any) -> None:
        nonlocal response_size_exceeded
        nonlocal total_response_bytes
        try:
            sizes = await request.sizes()
        except PlaywrightError:
            return
        response_bytes = max(0, int(sizes.get("responseBodySize", 0)))
        response_bytes += max(0, int(sizes.get("responseHeadersSize", 0)))
        total_response_bytes += response_bytes
        if total_response_bytes > max_response_bytes:
            response_size_exceeded = True

    def schedule_finished_request(request: Any) -> None:
        task = asyncio.create_task(record_finished_request(request))
        pending_size_tasks.add(task)
        task.add_done_callback(pending_size_tasks.discard)

    def inspect_response_headers(response: Any) -> None:
        nonlocal response_size_exceeded
        headers = getattr(response, "headers", {})
        declared_length = headers.get("content-length") if headers else None
        if declared_length and declared_length.isdigit():
            if int(declared_length) > max_response_bytes:
                response_size_exceeded = True

    semaphore = scan_semaphore or _BROWSER_SCAN_SEMAPHORE
    async with semaphore:
        browser: Any = None
        context: Any = None
        navigation_error: Exception | None = None
        load_started_at = perf_counter()

        try:
            async with playwright_factory() as playwright:
                browser = await playwright.chromium.launch(headless=True)
                context = await browser.new_context(service_workers="block")
                await context.route("**/*", route_request)
                if hasattr(context, "route_web_socket"):
                    await context.route_web_socket("**/*", route_web_socket)

                page = await context.new_page()
                page.on("console", record_console_error)
                page.on("pageerror", record_page_error)
                page.on("requestfailed", record_failed_request)
                page.on("requestfinished", schedule_finished_request)
                page.on("response", inspect_response_headers)

                data["page_load_status"] = "loading"
                load_started_at = perf_counter()
                try:
                    response = await page.goto(
                        requested_url,
                        wait_until="load",
                        timeout=timeout_ms,
                    )
                except (PlaywrightTimeoutError, PlaywrightError) as exc:
                    navigation_error = exc
                    response = None
                if pending_size_tasks:
                    await asyncio.gather(
                        *tuple(pending_size_tasks),
                        return_exceptions=True,
                    )
                data["load_duration_ms"] = _duration_ms(load_started_at)
                data["final_url"] = getattr(page, "url", requested_url)

                if response is not None:
                    status = int(response.status)
                    data["http_status"] = status
                    data["redirect_count"] = _redirect_count(response.request)
                    data["page_load_status"] = (
                        "loaded" if 200 <= status < 400 else "http_error"
                    )

                try:
                    data["title"] = await page.title()
                except PlaywrightError:
                    data["title"] = None

                if not response_size_exceeded:
                    try:
                        screenshot_reference = await _capture_screenshot(
                            page,
                            Path(screenshot_directory),
                            timeout_ms,
                        )
                    except (OSError, PlaywrightError) as exc:
                        screenshot_error = str(exc)
        except PlaywrightTimeoutError as exc:
            navigation_error = exc
        except PlaywrightError as exc:
            navigation_error = exc
        finally:
            if context is not None:
                try:
                    await context.close()
                except PlaywrightError:
                    pass
            if pending_size_tasks:
                await asyncio.gather(
                    *tuple(pending_size_tasks),
                    return_exceptions=True,
                )
            if browser is not None:
                try:
                    await browser.close()
                except PlaywrightError:
                    pass

    data.update(
        {
            "screenshot_reference": screenshot_reference,
            "total_response_bytes": total_response_bytes,
            "failed_network_request_count": total_failed_requests,
            "blocked_request_count": total_blocked_requests,
            "console_error_count": len(console_errors),
            "page_error_count": len(page_errors),
            "evidence_truncated": any(
                (
                    total_failed_requests > len(failed_requests),
                    total_blocked_requests > len(blocked_requests),
                )
            ),
        }
    )

    if response_size_exceeded:
        data["page_load_status"] = "response_too_large"
        return _result(
            started_at,
            success=False,
            data=data,
            errors=[
                ToolError(
                    code="response_too_large",
                    message="Browser responses exceeded the configured size limit.",
                )
            ],
        )
    if redirect_limit_exceeded:
        data["page_load_status"] = "blocked"
        return _result(
            started_at,
            success=False,
            data=data,
            errors=[
                ToolError(
                    code="too_many_redirects",
                    message="A browser request exceeded the redirect limit.",
                )
            ],
        )
    if blocked_main_navigation:
        data["page_load_status"] = "blocked"
        return _result(
            started_at,
            success=False,
            data=data,
            errors=[
                ToolError(
                    code="unsafe_navigation",
                    message="The page tried to navigate to a non-public address.",
                )
            ],
        )
    if navigation_error is not None:
        if isinstance(navigation_error, PlaywrightTimeoutError):
            data["page_load_status"] = "timed_out"
            code = "navigation_timeout"
            message = "The browser navigation timed out."
        else:
            data["page_load_status"] = "failed"
            code = "browser_error"
            message = "The browser could not load the target page."
        return _result(
            started_at,
            success=False,
            data=data,
            errors=[ToolError(code=code, message=message)],
        )
    if screenshot_error is not None:
        return _result(
            started_at,
            success=False,
            data=data,
            errors=[
                ToolError(
                    code="screenshot_error",
                    message="The full-page screenshot could not be saved.",
                )
            ],
        )

    http_status = data["http_status"]
    if not isinstance(http_status, int):
        data["page_load_status"] = "failed"
        return _result(
            started_at,
            success=False,
            data=data,
            errors=[
                ToolError(
                    code="missing_navigation_response",
                    message="The browser navigation did not return an HTTP response.",
                )
            ],
        )
    if not 200 <= http_status < 300:
        return _result(
            started_at,
            success=False,
            data=data,
            errors=[
                ToolError(
                    code="http_status_error",
                    message=f"The target returned HTTP status {http_status}.",
                )
            ],
        )

    return _result(started_at, success=True, data=data)
