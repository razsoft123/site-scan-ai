import httpx

from app.tools.metadata import inspect_metadata


def test_inspect_metadata_collects_structured_evidence() -> None:
    html = b"""
    <!doctype html>
    <html lang="en">
      <head>
        <title> Example Site </title>
        <meta name="description" content="A deterministic test page">
        <meta name="robots" content="index, follow">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <meta property="og:title" content="Example OG Title">
        <meta property="og:description" content="Example OG Description">
        <link rel="canonical" href="/canonical-page">
      </head>
      <body>
        <h1>First</h1><h1>Second</h1><h2>Details</h2>
        <img src="missing.png">
        <img src="decorative.png" alt="">
        <img src="described.png" alt="A description">
      </body>
    </html>
    """

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Type": "text/html; charset=utf-8"},
            content=html,
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = inspect_metadata("https://example.com/page", client=client)

    assert result.success is True
    assert result.tool == "inspect_metadata"
    assert result.errors == []
    assert result.data["http_status"] == 200
    assert result.data["title"] == "Example Site"
    assert result.data["meta_description"] == "A deterministic test page"
    assert result.data["canonical_url"] == "https://example.com/canonical-page"
    assert result.data["robots"] == "index, follow"
    assert result.data["viewport"] == "width=device-width, initial-scale=1"
    assert result.data["open_graph_title"] == "Example OG Title"
    assert result.data["open_graph_description"] == "Example OG Description"
    assert result.data["h1_count"] == 2
    assert result.data["h2_count"] == 1
    assert result.data["h6_count"] == 0
    assert result.data["image_count"] == 3
    assert result.data["images_without_alt"] == 1
    assert result.data["html_language"] == "en"
    assert result.data["page_size_bytes"] == len(html)


def test_missing_title_and_metadata_are_reported_as_none() -> None:
    html = b"<html><head></head><body><h3>Content</h3></body></html>"

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Type": "text/html"},
            content=html,
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = inspect_metadata("https://example.com", client=client)

    assert result.success is True
    assert result.data["title"] is None
    assert result.data["meta_description"] is None
    assert result.data["canonical_url"] is None
    assert result.data["robots"] is None
    assert result.data["viewport"] is None
    assert result.data["open_graph_title"] is None
    assert result.data["open_graph_description"] is None
    assert result.data["html_language"] is None
    assert result.data["h3_count"] == 1


def test_redirect_is_followed_and_recorded() -> None:
    requested_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        if request.url.path == "/start":
            return httpx.Response(302, headers={"Location": "/final"})
        return httpx.Response(
            200,
            headers={"Content-Type": "text/html"},
            content=b"<html><head><title>Final</title></head></html>",
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = inspect_metadata("https://example.com/start", client=client)

    assert result.success is True
    assert requested_urls == [
        "https://example.com/start",
        "https://example.com/final",
    ]
    assert result.data["redirected"] is True
    assert result.data["redirect_count"] == 1
    assert result.data["final_url"] == "https://example.com/final"
    assert result.data["title"] == "Final"


def test_redirect_to_private_address_is_rejected_before_following() -> None:
    call_count = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(302, headers={"Location": "http://127.0.0.1/admin"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = inspect_metadata("https://example.com/start", client=client)

    assert result.success is False
    assert result.errors[0].code == "unsafe_redirect"
    assert call_count == 1


def test_404_returns_metadata_evidence_with_http_error() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            404,
            headers={"Content-Type": "text/html"},
            content=b"<html><head><title>Not Found</title></head></html>",
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = inspect_metadata("https://example.com/missing", client=client)

    assert result.success is False
    assert result.data["http_status"] == 404
    assert result.data["title"] == "Not Found"
    assert result.errors[0].code == "http_status_error"


def test_timeout_returns_structured_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("Timed out", request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = inspect_metadata("https://example.com", client=client)

    assert result.success is False
    assert result.data["requested_url"] == "https://example.com"
    assert result.errors[0].code == "timeout"


def test_non_html_response_is_rejected_without_parsing() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Type": "application/json"},
            json={"title": "Not HTML"},
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = inspect_metadata("https://example.com/data", client=client)

    assert result.success is False
    assert result.data["content_type"] == "application/json"
    assert "title" not in result.data
    assert result.errors[0].code == "non_html_response"


def test_response_size_limit_is_enforced_while_streaming() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Type": "text/html"},
            content=b"<html>this response is too large</html>",
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = inspect_metadata(
            "https://example.com",
            client=client,
            max_response_bytes=10,
        )

    assert result.success is False
    assert result.errors[0].code == "response_too_large"
    assert result.data["page_size_bytes"] > 10


def test_private_url_is_rejected_without_making_a_request() -> None:
    call_count = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(200)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = inspect_metadata("http://10.0.0.1", client=client)

    assert result.success is False
    assert result.errors[0].code == "invalid_url"
    assert call_count == 0
