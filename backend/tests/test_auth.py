import os
from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

os.environ.setdefault(
    "JWT_SECRET_KEY",
    "test-only-secret-key-with-at-least-32-characters",
)

from app.core.config import get_settings
from app.core.register_handlers import register_exception_handlers
from app.core.security import verify_password
from app.db.database import get_db
from app.models.user import User
from app.routes.auth import router as auth_router


@pytest.fixture
def db_session() -> Iterator[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    User.__table__.create(bind=engine)
    testing_session = sessionmaker(bind=engine, expire_on_commit=False)

    with testing_session() as db:
        yield db

    engine.dispose()


@pytest.fixture
def client(db_session: Session) -> Iterator[TestClient]:
    get_settings.cache_clear()
    test_app = FastAPI()
    register_exception_handlers(test_app)
    test_app.include_router(auth_router)

    def override_get_db() -> Iterator[Session]:
        yield db_session

    test_app.dependency_overrides[get_db] = override_get_db

    with TestClient(test_app) as test_client:
        yield test_client


def register_test_user(client: TestClient) -> dict[str, object]:
    response = client.post(
        "/auth/register",
        json={
            "name": "Alice Example",
            "email": "Alice@Example.com",
            "password": "correct-horse-battery-staple",
        },
    )
    assert response.status_code == 201
    return response.json()


def test_register_hashes_password_and_normalizes_email(
    client: TestClient,
    db_session: Session,
) -> None:
    response_data = register_test_user(client)

    assert response_data["email"] == "alice@example.com"
    assert "password" not in response_data
    assert "password_hash" not in response_data

    user = db_session.scalar(select(User).where(User.email == "alice@example.com"))
    assert user is not None
    assert user.password_hash != "correct-horse-battery-staple"
    assert verify_password("correct-horse-battery-staple", user.password_hash)


def test_duplicate_registration_is_rejected(client: TestClient) -> None:
    register_test_user(client)
    response = client.post(
        "/auth/register",
        json={
            "name": "Another Alice",
            "email": "ALICE@example.com",
            "password": "another-secure-password",
        },
    )

    assert response.status_code == 409
    assert response.json() == {
        "detail": "An account with this email already exists."
    }


def test_login_and_get_current_user(client: TestClient) -> None:
    registered_user = register_test_user(client)
    login_response = client.post(
        "/auth/login",
        json={
            "email": "alice@example.com",
            "password": "correct-horse-battery-staple",
        },
    )

    assert login_response.status_code == 200
    token_data = login_response.json()
    assert token_data["token_type"] == "bearer"
    assert token_data["expires_in"] == 1800

    me_response = client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {token_data['access_token']}"},
    )

    assert me_response.status_code == 200
    assert me_response.json()["id"] == registered_user["id"]
    assert me_response.json()["email"] == "alice@example.com"


def test_invalid_login_and_token_are_rejected(client: TestClient) -> None:
    register_test_user(client)

    login_response = client.post(
        "/auth/login",
        json={
            "email": "alice@example.com",
            "password": "incorrect-password",
        },
    )
    me_response = client.get(
        "/auth/me",
        headers={"Authorization": "Bearer invalid-token"},
    )

    assert login_response.status_code == 401
    assert me_response.status_code == 401


def test_inactive_user_cannot_login(
    client: TestClient,
    db_session: Session,
) -> None:
    register_test_user(client)
    user = db_session.scalar(select(User).where(User.email == "alice@example.com"))
    assert user is not None
    user.is_active = False
    db_session.commit()

    response = client.post(
        "/auth/login",
        json={
            "email": "alice@example.com",
            "password": "correct-horse-battery-staple",
        },
    )

    assert response.status_code == 403
