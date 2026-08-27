import pytest

from app.tools import http_safety


@pytest.fixture(autouse=True)
def resolve_test_hosts_to_public_ip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        http_safety,
        "resolve_hostname",
        lambda _hostname, _port: ["93.184.216.34"],
    )
