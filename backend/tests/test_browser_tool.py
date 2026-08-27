import asyncio
import inspect
from pathlib import Path
from typing import Any

from playwright.async_api import Error as PlaywrightError

from app.tools.browser import inspect_browser


class FakeConsoleMessage:
    type = "error"
    text = "Uncaught ReferenceError: missing is not defined"
    location = {"url": "https://example.com/app.js", "lineNumber": 7}


class FakeRequest:
    def __init__(
        self,
        url: str,
        *,
        redirected_from: "FakeRequest | None" = None,
        navigation: bool = False,
        response_size: int = 100,
        failure: str | None = None,
    ) -> None:
        self.url = url
        self.method = "GET"
        self.resource_type = "document" if navigation else "script"
        self.redirected_from = redirected_from
        self._navigation = navigation
        self._response_size = response_size
        self.failure = failure

    def is_navigation_request(self) -> bool:
        return self._navigation

    async def sizes(self) -> dict[str, int]:
        return {
            "requestBodySize": 0,
            "requestHeadersSize": 50,
            "responseBodySize": self._response_size,
            "responseHeadersSize": 50,
        }


class FakeRoute:
    def __init__(self, request: FakeRequest) -> None:
        self.request = request
        self.aborted = False

    async def continue_(self) -> None:
        return None

    async def abort(self, *, error_code: str) -> None:
        assert error_code == "blockedbyclient"
        self.aborted = True


class FakeResponse:
    def __init__(self, status: int, request: FakeRequest) -> None:
        self.status = status
        self.request = request
        self.headers: dict[str, str] = {}


class FakePage:
    def __init__(self, context: "FakeContext", scenario: dict[str, Any]) -> None:
        self.context = context
        self.scenario = scenario
        self.url = scenario.get("final_url", "https://example.com/final")
        self.handlers: dict[str, Any] = {}
        self.screenshot_options: dict[str, Any] = {}

    def on(self, event: str, handler: Any) -> None:
        self.handlers[event] = handler

    async def _emit(self, event: str, value: Any) -> None:
        handler = self.handlers.get(event)
        if handler is None:
            return
        result = handler(value)
        if inspect.isawaitable(result):
            await result

    async def _route(self, request: FakeRequest) -> FakeRoute:
        route = FakeRoute(request)
        await self.context.route_handler(route)
        if route.aborted:
            request.failure = "net::ERR_BLOCKED_BY_CLIENT"
            await self._emit("requestfailed", request)
        return route

    async def goto(
        self,
        url: str,
        *,
        wait_until: str,
        timeout: int,
    ) -> FakeResponse:
        assert wait_until == "load"
        assert timeout > 0
        on_enter = self.scenario.get("on_enter")
        if on_enter is not None:
            await on_enter()

        navigation = FakeRequest(
            url,
            navigation=True,
            response_size=self.scenario.get("response_size", 100),
        )
        route = await self._route(navigation)
        if route.aborted:
            raise PlaywrightError("navigation blocked")

        previous = navigation
        for redirect_url in self.scenario.get("redirects", []):
            redirected = FakeRequest(
                redirect_url,
                redirected_from=previous,
                navigation=True,
            )
            route = await self._route(redirected)
            if route.aborted:
                self.url = previous.url
                raise PlaywrightError("redirect blocked")
            previous = redirected
            self.url = redirect_url

        for subresource_url in self.scenario.get("subresources", []):
            subresource = FakeRequest(subresource_url)
            route = await self._route(subresource)
            if not route.aborted:
                await self._emit("requestfinished", subresource)

        failed_url = self.scenario.get("failed_url")
        if failed_url:
            await self._emit(
                "requestfailed",
                FakeRequest(failed_url, failure="net::ERR_CONNECTION_REFUSED"),
            )
        if self.scenario.get("console_error", False):
            await self._emit("console", FakeConsoleMessage())
        if self.scenario.get("page_error", False):
            await self._emit("pageerror", RuntimeError("page crashed"))

        response = FakeResponse(self.scenario.get("status", 200), previous)
        await self._emit("response", response)
        await self._emit("requestfinished", previous)
        return response

    async def title(self) -> str:
        return self.scenario.get("title", "Example Domain")

    async def screenshot(self, **kwargs: Any) -> bytes:
        self.screenshot_options = kwargs
        Path(kwargs["path"]).write_bytes(b"fake png")
        return b"fake png"


class FakeContext:
    def __init__(self, scenario: dict[str, Any]) -> None:
        self.scenario = scenario
        self.route_handler: Any = None
        self.service_workers: str | None = None
        self.page: FakePage | None = None

    async def route(self, pattern: str, handler: Any) -> None:
        assert pattern == "**/*"
        self.route_handler = handler

    async def route_web_socket(self, pattern: str, handler: Any) -> None:
        assert pattern == "**/*"
        self.web_socket_handler = handler

    async def new_page(self) -> FakePage:
        self.page = FakePage(self, self.scenario)
        return self.page

    async def close(self) -> None:
        return None


class FakeBrowser:
    def __init__(self, scenario: dict[str, Any]) -> None:
        self.scenario = scenario
        self.context: FakeContext | None = None

    async def new_context(self, *, service_workers: str) -> FakeContext:
        self.context = FakeContext(self.scenario)
        self.context.service_workers = service_workers
        return self.context

    async def close(self) -> None:
        return None


class FakeChromium:
    def __init__(self, scenario: dict[str, Any]) -> None:
        self.scenario = scenario
        self.browser: FakeBrowser | None = None

    async def launch(self, *, headless: bool) -> FakeBrowser:
        assert headless is True
        self.browser = FakeBrowser(self.scenario)
        return self.browser


class FakePlaywright:
    def __init__(self, scenario: dict[str, Any]) -> None:
        self.chromium = FakeChromium(scenario)


class FakePlaywrightManager:
    def __init__(self, scenario: dict[str, Any]) -> None:
        self.playwright = FakePlaywright(scenario)

    async def __aenter__(self) -> FakePlaywright:
        return self.playwright

    async def __aexit__(self, *_args: object) -> None:
        return None


class FakePlaywrightFactory:
    def __init__(self, scenario: dict[str, Any] | None = None) -> None:
        self.scenario = scenario or {}
        self.manager: FakePlaywrightManager | None = None
        self.called = False

    def __call__(self) -> FakePlaywrightManager:
        self.called = True
        self.manager = FakePlaywrightManager(self.scenario)
        return self.manager


def run_browser(factory: FakePlaywrightFactory, tmp_path: Path, **kwargs: Any):
    return asyncio.run(
        inspect_browser(
            "https://example.com/start",
            playwright_factory=factory,
            screenshot_directory=tmp_path,
            **kwargs,
        )
    )


def test_collects_browser_evidence_and_full_page_screenshot(tmp_path: Path) -> None:
    factory = FakePlaywrightFactory(
        {
            "final_url": "https://example.com/final",
            "redirects": ["https://example.com/final"],
            "title": "Rendered title",
            "console_error": True,
            "page_error": True,
            "failed_url": "https://cdn.example.com/missing.js",
        }
    )

    result = run_browser(factory, tmp_path)

    assert result.success is True
    assert result.tool == "inspect_browser"
    assert result.data["page_load_status"] == "loaded"
    assert result.data["http_status"] == 200
    assert result.data["final_url"] == "https://example.com/final"
    assert result.data["redirect_count"] == 1
    assert result.data["title"] == "Rendered title"
    assert result.data["console_error_count"] == 1
    assert result.data["page_error_count"] == 1
    assert result.data["failed_network_request_count"] == 1
    screenshot_path = Path(result.data["screenshot_reference"])
    assert screenshot_path.is_file()

    browser = factory.manager.playwright.chromium.browser
    assert browser.context.service_workers == "block"
    assert browser.context.page.screenshot_options["full_page"] is True


def test_private_hostname_is_rejected_before_browser_launch(tmp_path: Path) -> None:
    factory = FakePlaywrightFactory()

    result = asyncio.run(
        inspect_browser(
            "https://public.example",
            resolver=lambda _host, _port: ["10.0.0.4"],
            playwright_factory=factory,
            screenshot_directory=tmp_path,
        )
    )

    assert result.success is False
    assert result.errors[0].code == "invalid_url"
    assert factory.called is False


def test_non_http_protocol_is_rejected_before_browser_launch(tmp_path: Path) -> None:
    factory = FakePlaywrightFactory()

    result = asyncio.run(
        inspect_browser(
            "file:///etc/passwd",
            playwright_factory=factory,
            screenshot_directory=tmp_path,
        )
    )

    assert result.success is False
    assert result.errors[0].code == "invalid_url"
    assert factory.called is False


def test_private_subresource_is_blocked_without_failing_page(tmp_path: Path) -> None:
    factory = FakePlaywrightFactory(
        {"subresources": ["http://169.254.169.254/latest/meta-data/"]}
    )

    result = run_browser(factory, tmp_path)

    assert result.success is True
    assert result.data["blocked_request_count"] == 1
    assert result.data["blocked_requests"][0]["reason"] == "unsafe_network_target"
    assert result.data["blocked_requests"][0]["is_navigation"] is False


def test_redirect_to_private_address_fails_navigation(tmp_path: Path) -> None:
    factory = FakePlaywrightFactory({"redirects": ["http://127.0.0.1/admin"]})

    result = run_browser(factory, tmp_path)

    assert result.success is False
    assert result.errors[0].code == "unsafe_navigation"
    assert result.data["page_load_status"] == "blocked"


def test_redirect_limit_is_enforced(tmp_path: Path) -> None:
    factory = FakePlaywrightFactory(
        {
            "redirects": [
                "https://one.example.com",
                "https://two.example.com",
            ]
        }
    )

    result = run_browser(factory, tmp_path, max_redirects=1)

    assert result.success is False
    assert result.errors[0].code == "too_many_redirects"


def test_cumulative_response_size_limit_is_enforced(tmp_path: Path) -> None:
    factory = FakePlaywrightFactory({"response_size": 500})

    result = run_browser(factory, tmp_path, max_response_bytes=100)

    assert result.success is False
    assert result.errors[0].code == "response_too_large"
    assert result.data["total_response_bytes"] == 550
    assert result.data["screenshot_reference"] is None


def test_browser_scans_are_serialized(tmp_path: Path) -> None:
    active_scans = 0
    maximum_active_scans = 0

    async def on_enter() -> None:
        nonlocal active_scans, maximum_active_scans
        active_scans += 1
        maximum_active_scans = max(maximum_active_scans, active_scans)
        await asyncio.sleep(0.02)
        active_scans -= 1

    async def run() -> None:
        semaphore = asyncio.Semaphore(1)
        factories = [
            FakePlaywrightFactory({"on_enter": on_enter}),
            FakePlaywrightFactory({"on_enter": on_enter}),
        ]
        results = await asyncio.gather(
            *(
                inspect_browser(
                    "https://example.com",
                    playwright_factory=factory,
                    screenshot_directory=tmp_path,
                    scan_semaphore=semaphore,
                )
                for factory in factories
            )
        )
        assert all(result.success for result in results)

    asyncio.run(run())

    assert maximum_active_scans == 1
