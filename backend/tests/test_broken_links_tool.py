import asyncio
from collections.abc import Awaitable, Callable

import httpx

from app.tools.broken_links import check_broken_links


AsyncHandler = Callable[[httpx.Request], Awaitable[httpx.Response]]


def run_checker(
    handler: AsyncHandler,
    **kwargs: object,
):
    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as client:
            return await check_broken_links(
                "https://example.com/page",
                client=client,
                **kwargs,
            )

    return asyncio.run(run())


def test_links_are_normalized_deduplicated_and_classified() -> None:
    html = b"""
    <html><body>
      <a href="/ok">Working</a>
      <a href="https://example.com/ok#details">Duplicate</a>
      <a href="/redirect">Redirect</a>
      <a href="/broken">Broken</a>
      <a href="/timeout">Timeout</a>
      <a href="mailto:hello@example.com">Email</a>
      <a href="#section">Page section</a>
      <a href="http://127.0.0.1/private">Unsafe</a>
    </body></html>
    """
    requested_paths: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requested_paths.append(request.url.path)
        if request.url.path == "/page":
            return httpx.Response(
                200,
                headers={"Content-Type": "text/html"},
                content=html,
            )
        if request.url.path == "/ok":
            return httpx.Response(200)
        if request.url.path == "/redirect":
            return httpx.Response(302, headers={"Location": "/final"})
        if request.url.path == "/final":
            return httpx.Response(204)
        if request.url.path == "/broken":
            return httpx.Response(404)
        if request.url.path == "/timeout":
            raise httpx.ReadTimeout("Timed out", request=request)
        raise AssertionError(f"Unexpected request: {request.url}")

    result = run_checker(handler)

    assert result.tool == "check_broken_links"
    assert result.success is True
    assert result.errors == []
    assert result.data["extracted_links"] == 8
    assert result.data["unique_links"] == 5
    assert result.data["checked"] == 4
    assert result.data["working"] == 1
    assert result.data["redirected"] == 1
    assert result.data["broken"] == 1
    assert result.data["timed_out"] == 1
    assert result.data["skipped_unsafe"] == 1
    assert result.data["ignored_non_http"] == 2
    assert result.data["unchecked_due_to_limit"] == 0
    assert "/ok" in requested_paths
    assert requested_paths.count("/ok") == 1
    assert "/private" not in requested_paths
    assert [link["classification"] for link in result.data["links"]] == [
        "working",
        "redirected",
        "broken",
        "timed_out",
    ]


def test_only_25_links_are_checked_with_safe_concurrency() -> None:
    html = (
        "<html><body>"
        + "".join(f'<a href="/link/{index}">Link</a>' for index in range(30))
        + "</body></html>"
    ).encode()
    active_requests = 0
    maximum_active_requests = 0
    checked_paths: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal active_requests, maximum_active_requests
        if request.url.path == "/page":
            return httpx.Response(
                200,
                headers={"Content-Type": "text/html"},
                content=html,
            )

        active_requests += 1
        maximum_active_requests = max(maximum_active_requests, active_requests)
        checked_paths.append(request.url.path)
        await asyncio.sleep(0.01)
        active_requests -= 1
        return httpx.Response(200)

    result = run_checker(handler, concurrency_limit=3)

    assert result.success is True
    assert result.data["unique_links"] == 30
    assert result.data["checked"] == 25
    assert result.data["working"] == 25
    assert result.data["unchecked_due_to_limit"] == 5
    assert len(checked_paths) == 25
    assert 1 < maximum_active_requests <= 3


def test_link_redirect_to_private_address_is_broken_and_not_followed() -> None:
    requested_paths: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requested_paths.append(request.url.path)
        if request.url.path == "/page":
            return httpx.Response(
                200,
                headers={"Content-Type": "text/html"},
                content=b'<a href="/redirect">Redirect</a>',
            )
        return httpx.Response(302, headers={"Location": "http://10.0.0.1"})

    result = run_checker(handler)

    assert result.success is True
    assert result.data["checked"] == 1
    assert result.data["broken"] == 1
    assert result.data["links"][0]["error_code"] == "unsafe_redirect"
    assert requested_paths == ["/page", "/redirect"]


def test_source_page_redirect_changes_relative_link_base() -> None:
    requested_urls: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        if request.url.path == "/page":
            return httpx.Response(
                301,
                headers={"Location": "https://www.example.com/docs/start"},
            )
        if request.url.path == "/docs/start":
            return httpx.Response(
                200,
                headers={"Content-Type": "text/html"},
                content=b'<a href="next">Next</a>',
            )
        return httpx.Response(200)

    result = run_checker(handler)

    assert result.success is True
    assert result.data["source_redirect_count"] == 1
    assert result.data["final_url"] == "https://www.example.com/docs/start"
    assert result.data["links"][0]["url"] == "https://www.example.com/docs/next"
    assert requested_urls[-1] == "https://www.example.com/docs/next"


def test_empty_page_returns_success_with_zero_checked_links() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Type": "text/html"},
            content=b"<html><body>No links</body></html>",
        )

    result = run_checker(handler)

    assert result.success is True
    assert result.data["checked"] == 0
    assert result.data["links"] == []


def test_source_page_http_error_fails_the_tool() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(404, headers={"Content-Type": "text/html"})

    result = run_checker(handler)

    assert result.success is False
    assert result.data["source_http_status"] == 404
    assert result.errors[0].code == "source_page_http_error"


def test_non_html_source_page_fails_the_tool() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Type": "application/json"},
            json={"links": []},
        )

    result = run_checker(handler)

    assert result.success is False
    assert result.data["content_type"] == "application/json"
    assert result.errors[0].code == "non_html_source"


def test_source_page_timeout_returns_structured_error() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("Timed out", request=request)

    result = run_checker(handler)

    assert result.success is False
    assert result.errors[0].code == "source_page_timeout"


def test_source_page_size_limit_is_enforced() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Type": "text/html"},
            content=b"<html>This source page is too large</html>",
        )

    result = run_checker(handler, max_response_bytes=10)

    assert result.success is False
    assert result.errors[0].code == "source_page_too_large"
    assert result.data["page_size_bytes"] > 10


def test_invalid_limits_are_rejected_without_requesting() -> None:
    call_count = 0

    async def handler(_: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(200)

    result = run_checker(handler, max_links=26, concurrency_limit=11)

    assert result.success is False
    assert result.errors[0].code == "invalid_configuration"
    assert call_count == 0
