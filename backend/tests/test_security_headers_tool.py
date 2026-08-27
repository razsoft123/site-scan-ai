import httpx

from app.tools.security_headers import inspect_security_headers


def test_all_required_security_headers_are_collected_from_response() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={
                "Content-Security-Policy": (
                    "default-src 'self'; frame-ancestors 'none'; object-src 'none'"
                ),
                "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "strict-origin-when-cross-origin",
                "Permissions-Policy": "camera=(), microphone=()",
                "X-Frame-Options": "SAMEORIGIN",
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = inspect_security_headers("https://example.com", client=client)

    assert result.tool == "inspect_security_headers"
    assert result.success is True
    assert result.errors == []
    assert result.data["http_status"] == 200
    assert result.data["content_security_policy"].startswith("default-src")
    assert result.data["strict_transport_security"] == (
        "max-age=31536000; includeSubDomains"
    )
    assert result.data["x_content_type_options"] == "nosniff"
    assert result.data["referrer_policy"] == "strict-origin-when-cross-origin"
    assert result.data["permissions_policy"] == "camera=(), microphone=()"
    assert result.data["x_frame_options"] == "SAMEORIGIN"
    assert result.data["csp_frame_ancestors"] == "'none'"
    assert result.data["strict_transport_security_effective"] is True
    assert result.data["x_content_type_options_nosniff"] is True
    assert result.data["frame_protection"] == {
        "protected": True,
        "mechanisms": ["x-frame-options", "csp-frame-ancestors"],
        "x_frame_options_valid": True,
        "csp_frame_ancestors_present": True,
    }
    assert result.data["missing_headers"] == []


def test_missing_headers_are_evidence_not_a_tool_failure() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = inspect_security_headers("https://example.com", client=client)

    assert result.success is True
    assert result.data["content_security_policy"] is None
    assert result.data["strict_transport_security"] is None
    assert result.data["x_content_type_options"] is None
    assert result.data["referrer_policy"] is None
    assert result.data["permissions_policy"] is None
    assert result.data["x_frame_options"] is None
    assert result.data["frame_protection"]["protected"] is False
    assert result.data["missing_headers"] == [
        "Content-Security-Policy",
        "Strict-Transport-Security",
        "X-Content-Type-Options",
        "Referrer-Policy",
        "Permissions-Policy",
        "Frame-Protection",
    ]


def test_wildcard_csp_and_invalid_x_frame_options_do_not_claim_protection() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={
                "Content-Security-Policy": "default-src 'self'; frame-ancestors *",
                "X-Frame-Options": "ALLOWALL",
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = inspect_security_headers("https://example.com", client=client)

    frame_protection = result.data["frame_protection"]
    assert result.success is True
    assert result.data["csp_frame_ancestors"] == "*"
    assert frame_protection["csp_frame_ancestors_present"] is True
    assert frame_protection["x_frame_options_valid"] is False
    assert frame_protection["protected"] is False
    assert "Frame-Protection" in result.data["missing_headers"]


def test_csp_frame_ancestors_can_protect_without_x_frame_options() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={
                "Content-Security-Policy": (
                    "frame-ancestors 'self' https://trusted.example"
                )
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = inspect_security_headers("https://example.com", client=client)

    assert result.data["frame_protection"] == {
        "protected": True,
        "mechanisms": ["csp-frame-ancestors"],
        "x_frame_options_valid": False,
        "csp_frame_ancestors_present": True,
    }
    assert "Frame-Protection" not in result.data["missing_headers"]


def test_redirect_is_followed_and_only_final_headers_are_reported() -> None:
    requested_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        if request.url.path == "/start":
            return httpx.Response(
                301,
                headers={
                    "Location": "/final",
                    "X-Content-Type-Options": "incorrect-redirect-value",
                },
            )
        return httpx.Response(
            200,
            headers={"X-Content-Type-Options": "nosniff"},
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = inspect_security_headers(
            "https://example.com/start",
            client=client,
        )

    assert result.success is True
    assert requested_urls == [
        "https://example.com/start",
        "https://example.com/final",
    ]
    assert result.data["redirected"] is True
    assert result.data["redirect_count"] == 1
    assert result.data["final_url"] == "https://example.com/final"
    assert result.data["x_content_type_options"] == "nosniff"


def test_404_preserves_header_evidence_and_returns_http_error() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            404,
            headers={"Referrer-Policy": "no-referrer"},
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = inspect_security_headers(
            "https://example.com/missing",
            client=client,
        )

    assert result.success is False
    assert result.data["http_status"] == 404
    assert result.data["referrer_policy"] == "no-referrer"
    assert result.errors[0].code == "http_status_error"


def test_timeout_returns_structured_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("Timed out", request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = inspect_security_headers("https://example.com", client=client)

    assert result.success is False
    assert result.errors[0].code == "timeout"


def test_redirect_to_private_address_is_rejected_before_following() -> None:
    call_count = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(302, headers={"Location": "http://127.0.0.1"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = inspect_security_headers(
            "https://example.com/start",
            client=client,
        )

    assert result.success is False
    assert result.errors[0].code == "unsafe_redirect"
    assert call_count == 1


def test_hsts_received_over_http_is_not_marked_effective() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Strict-Transport-Security": "max-age=31536000"},
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = inspect_security_headers("http://example.com", client=client)

    assert result.success is True
    assert result.data["strict_transport_security"] == "max-age=31536000"
    assert result.data["strict_transport_security_effective"] is False
