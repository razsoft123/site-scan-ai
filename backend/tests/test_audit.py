import os
from collections.abc import Iterator
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

os.environ.setdefault(
    "JWT_SECRET_KEY",
    "test-only-secret-key-with-at-least-32-characters",
)

from app.core.config import get_settings
from app.core.register_handlers import register_exception_handlers
from app.core.security import create_access_token, hash_password
from app.db.base import Base
from app.db.database import get_db
from app.models.audit import Audit
from app.models.tool_execution import ToolExecution
from app.models.user import User
from app.routes.audit import router as audit_router


@compiles(JSONB, "sqlite")
def compile_jsonb_for_sqlite(_: JSONB, __: object, **___: object) -> str:
    return "JSON"


@pytest.fixture
def db_session() -> Iterator[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    testing_session = sessionmaker(bind=engine, expire_on_commit=False)

    with testing_session() as db:
        yield db

    engine.dispose()


@pytest.fixture
def client(db_session: Session) -> Iterator[TestClient]:
    get_settings.cache_clear()
    test_app = FastAPI()
    register_exception_handlers(test_app)
    test_app.include_router(audit_router)

    def override_get_db() -> Iterator[Session]:
        yield db_session

    test_app.dependency_overrides[get_db] = override_get_db

    with TestClient(test_app) as test_client:
        yield test_client


def create_test_user(db: Session, email: str) -> User:
    user = User(
        name="Audit Tester",
        email=email,
        password_hash=hash_password("correct-horse-battery-staple"),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def auth_headers(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


def create_test_audit(
    client: TestClient,
    user: User,
    *,
    target_url: str = "https://example.com",
) -> dict[str, object]:
    response = client.post(
        "/audits",
        headers=auth_headers(user),
        json={
            "target_url": target_url,
            "instruction": "Run a full release audit.",
        },
    )
    assert response.status_code == 201
    return response.json()


def test_create_audit_returns_mock_report_and_ordered_lifecycle_events(
    client: TestClient,
    db_session: Session,
) -> None:
    user = create_test_user(db_session, "owner@example.com")
    audit = create_test_audit(client, user)

    assert audit["status"] == "completed"
    assert audit["overall_score"] is None
    assert audit["release_status"] == "unknown"
    assert audit["tools_executed"] == []
    assert audit["tool_executions"] == []
    assert audit["report"]["is_mock"] is True
    assert audit["report"]["findings"] == []

    events_response = client.get(
        f"/audits/{audit['id']}/events",
        headers=auth_headers(user),
    )
    assert events_response.status_code == 200
    events = events_response.json()
    assert [event["sequence_number"] for event in events] == [1, 2, 3, 4, 5]
    assert [event["event_type"] for event in events] == [
        "audit_created",
        "status_changed",
        "status_changed",
        "report_started",
        "audit_completed",
    ]
    assert [event["to_status"] for event in events] == [
        "queued",
        "planning",
        "running_tools",
        "generating_report",
        "completed",
    ]


def test_audit_history_and_details_are_private_per_user(
    client: TestClient,
    db_session: Session,
) -> None:
    owner = create_test_user(db_session, "owner@example.com")
    other_user = create_test_user(db_session, "other@example.com")
    audit = create_test_audit(client, owner)

    owner_history = client.get("/audits", headers=auth_headers(owner))
    other_history = client.get("/audits", headers=auth_headers(other_user))
    hidden_detail = client.get(
        f"/audits/{audit['id']}",
        headers=auth_headers(other_user),
    )
    hidden_events = client.get(
        f"/audits/{audit['id']}/events",
        headers=auth_headers(other_user),
    )

    assert owner_history.status_code == 200
    assert [item["id"] for item in owner_history.json()] == [audit["id"]]
    assert other_history.status_code == 200
    assert other_history.json() == []
    assert hidden_detail.status_code == 404
    assert hidden_events.status_code == 404


def test_detail_and_history_include_tool_execution_information(
    client: TestClient,
    db_session: Session,
) -> None:
    user = create_test_user(db_session, "owner@example.com")
    audit_data = create_test_audit(client, user)
    now = datetime.now(timezone.utc)
    execution = ToolExecution(
        audit_id=int(audit_data["id"]),
        tool_name="inspect_metadata",
        arguments={"url": "https://example.com/"},
        status="completed",
        success=True,
        data={"title": "Example"},
        errors=[],
        started_at=now,
        completed_at=now,
        duration_ms=12,
        sequence_number=1,
    )
    db_session.add(execution)
    db_session.commit()

    detail_response = client.get(
        f"/audits/{audit_data['id']}",
        headers=auth_headers(user),
    )
    history_response = client.get("/audits", headers=auth_headers(user))

    assert detail_response.status_code == 200
    assert detail_response.json()["tools_executed"] == ["inspect_metadata"]
    assert detail_response.json()["tool_executions"][0]["duration_ms"] == 12
    assert history_response.status_code == 200
    assert history_response.json()[0]["tools_executed"] == ["inspect_metadata"]


@pytest.mark.parametrize(
    "target_url",
    [
        "http://localhost",
        "http://127.0.0.1",
        "http://10.0.0.1",
        "http://169.254.169.254",
        "http://[::1]",
        "http://service.internal",
    ],
)
def test_private_and_internal_targets_are_rejected(
    client: TestClient,
    db_session: Session,
    target_url: str,
) -> None:
    user = create_test_user(db_session, "owner@example.com")
    response = client.post(
        "/audits",
        headers=auth_headers(user),
        json={
            "target_url": target_url,
            "instruction": "Check this website.",
        },
    )

    assert response.status_code == 422


def test_audit_routes_require_authentication_and_validate_pagination(
    client: TestClient,
) -> None:
    unauthorized_response = client.get("/audits")
    invalid_pagination_response = client.get(
        "/audits?limit=101&offset=-1",
        headers={"Authorization": "Bearer invalid-token"},
    )

    assert unauthorized_response.status_code == 401
    assert invalid_pagination_response.status_code in {401, 422}


def test_missing_owned_audit_returns_not_found(
    client: TestClient,
    db_session: Session,
) -> None:
    user = create_test_user(db_session, "owner@example.com")
    response = client.get("/audits/999", headers=auth_headers(user))

    assert response.status_code == 404
    assert response.json() == {"detail": "Audit not found."}


def test_history_pagination_is_applied(
    client: TestClient,
    db_session: Session,
) -> None:
    user = create_test_user(db_session, "owner@example.com")
    first = create_test_audit(client, user, target_url="https://example.com")
    second = create_test_audit(client, user, target_url="https://openai.com")

    response = client.get(
        "/audits?limit=1&offset=1",
        headers=auth_headers(user),
    )

    assert response.status_code == 200
    assert [audit["id"] for audit in response.json()] == [first["id"]]
    assert second["id"] != first["id"]
