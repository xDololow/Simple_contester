import os
import asyncio
from contextlib import asynccontextmanager
from collections.abc import Callable, Generator
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import httpx
import fastapi.dependencies.utils
import fastapi.routing
from sqlalchemy import select


TEST_DB_PATH = Path(__file__).with_name(".simple_contester_pytest.db")

os.environ.setdefault("DATABASE_URL", f"sqlite:///{TEST_DB_PATH}")
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ.setdefault("ADMIN_PASSWORD", "admin")

from app.auth import hash_password  # noqa: E402
from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import LOGIN_ATTEMPTS, LOGIN_LOCKED_UNTIL, app, ensure_admin  # noqa: E402
from app.models import Contest, Task, User, UserRole  # noqa: E402


async def _run_sync_directly(func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    return func(*args, **kwargs)


@asynccontextmanager
async def _contextmanager_directly(cm: Any) -> Any:
    value = cm.__enter__()
    try:
        yield value
    except Exception as exc:
        if not cm.__exit__(type(exc), exc, exc.__traceback__):
            raise
    else:
        cm.__exit__(None, None, None)


fastapi.routing.run_in_threadpool = _run_sync_directly
fastapi.dependencies.utils.run_in_threadpool = _run_sync_directly
fastapi.dependencies.utils.contextmanager_in_threadpool = _contextmanager_directly


class APIClient:
    def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        async def _request() -> httpx.Response:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                return await client.request(method, url, **kwargs)

        return asyncio.run(_request())

    def get(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("POST", url, **kwargs)

    def put(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("PUT", url, **kwargs)

    def patch(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("PATCH", url, **kwargs)


@pytest.fixture(autouse=True)
def clean_database() -> Generator[None, None, None]:
    engine.dispose()
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        ensure_admin(db)
    LOGIN_ATTEMPTS.clear()
    LOGIN_LOCKED_UNTIL.clear()
    yield
    Base.metadata.drop_all(bind=engine)
    engine.dispose()
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()


@pytest.fixture
def client() -> APIClient:
    return APIClient()


@pytest.fixture
def auth_headers(client: APIClient) -> Callable[[str, str], dict[str, str]]:
    def _auth_headers(username: str, password: str) -> dict[str, str]:
        response = client.post("/api/auth/login", json={"username": username, "password": password})
        assert response.status_code == 200, response.text
        token = response.json()["access_token"]
        return {"Authorization": f"Bearer {token}"}

    return _auth_headers


@pytest.fixture
def admin_headers(auth_headers: Callable[[str, str], dict[str, str]]) -> dict[str, str]:
    return auth_headers("admin", "admin")


@pytest.fixture
def create_user(client: APIClient, admin_headers: dict[str, str]) -> Callable[..., dict[str, Any]]:
    def _create_user(
        username: str = "participant",
        password: str = "secret",
        display_name: str | None = None,
        role: str = "participant",
    ) -> dict[str, Any]:
        response = client.post(
            "/api/users",
            headers=admin_headers,
            json={
                "username": username,
                "password": password,
                "display_name": display_name or username.title(),
                "role": role,
            },
        )
        assert response.status_code == 200, response.text
        return response.json()

    return _create_user


@pytest.fixture
def participant(create_user: Callable[..., dict[str, Any]]) -> dict[str, Any]:
    user = create_user(username="alice", password="alice-pass", display_name="Alice")
    user["password"] = "alice-pass"
    return user


@pytest.fixture
def participant_headers(
    participant: dict[str, Any],
    auth_headers: Callable[[str, str], dict[str, str]],
) -> dict[str, str]:
    return auth_headers(participant["username"], participant["password"])


@pytest.fixture
def demo_contest(client: APIClient, admin_headers: dict[str, str]) -> dict[str, Any]:
    now = datetime.utcnow()
    response = client.post(
        "/api/contests",
        headers=admin_headers,
        json={
            "title": "Demo Contest",
            "description": "Integration fixture contest",
            "status": "running",
            "is_public": True,
            "time_mode": "individual",
            "starts_at": (now - timedelta(minutes=5)).isoformat(),
            "ends_at": (now + timedelta(hours=1)).isoformat(),
            "individual_duration_minutes": 30,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture
def demo_task(client: APIClient, admin_headers: dict[str, str], demo_contest: dict[str, Any]) -> dict[str, Any]:
    response = client.post(
        "/api/tasks",
        headers=admin_headers,
        json={
            "contest_id": demo_contest["id"],
            "title": "A + B",
            "statement": "Read two integers and print their sum.",
            "input_format": "Two integers.",
            "output_format": "Their sum.",
            "samples": [{"input": "2 3\n", "output": "5\n"}],
            "time_limit_ms": 1000,
            "memory_limit_mb": 128,
            "points": 100,
            "tests": [
                {"input_data": "2 3\n", "output_data": "5\n", "is_sample": True},
                {"input_data": "40 2\n", "output_data": "42\n", "is_sample": False},
            ],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture
def demo_users() -> list[dict[str, str]]:
    return [
        {"username": "demo_alice", "password": "demo-pass", "display_name": "Demo Alice", "role": "participant"},
        {"username": "demo_bob", "password": "demo-pass", "display_name": "Demo Bob", "role": "participant"},
    ]


def seed_user(username: str, password: str, role: UserRole = UserRole.participant) -> User:
    with SessionLocal() as db:
        user = User(
            username=username,
            password_hash=hash_password(password),
            display_name=username,
            role=role,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user


def get_contest(contest_id: int) -> Contest:
    with SessionLocal() as db:
        contest = db.get(Contest, contest_id)
        assert contest is not None
        return contest


def get_task(task_id: int) -> Task:
    with SessionLocal() as db:
        task = db.scalar(select(Task).where(Task.id == task_id))
        assert task is not None
        return task
