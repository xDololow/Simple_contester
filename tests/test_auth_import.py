import json
import time

import pytest
from jose import jwt

from conftest import APIClient
from app.config import settings
from app.main import LOGIN_ATTEMPTS, LOGIN_LOCKED_UNTIL


def test_login_and_participant_cannot_access_admin_endpoints(
    client: APIClient,
    admin_headers: dict[str, str],
    participant_headers: dict[str, str],
) -> None:
    me = client.get("/api/me", headers=participant_headers)
    assert me.status_code == 200
    assert me.json()["role"] == "participant"

    users = client.get("/api/users", headers=participant_headers)
    assert users.status_code == 403
    assert users.json()["detail"] == "Admin role required"

    admin_users = client.get("/api/users", headers=admin_headers)
    assert admin_users.status_code == 200


def test_current_user_can_change_password_and_old_password_stops_working(
    client: APIClient,
    participant: dict[str, str],
    participant_headers: dict[str, str],
) -> None:
    response = client.post(
        "/api/me/password",
        headers=participant_headers,
        json={"old_password": participant["password"], "new_password": "alice-new-pass"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["username"] == participant["username"]

    old_login = client.post(
        "/api/auth/login",
        json={"username": participant["username"], "password": participant["password"]},
    )
    assert old_login.status_code == 401

    new_login = client.post(
        "/api/auth/login",
        json={"username": participant["username"], "password": "alice-new-pass"},
    )
    assert new_login.status_code == 200, new_login.text


def test_current_user_password_change_rejects_wrong_old_password(
    client: APIClient,
    participant_headers: dict[str, str],
) -> None:
    response = client.post(
        "/api/me/password",
        headers=participant_headers,
        json={"old_password": "wrong-pass", "new_password": "alice-new-pass"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Current password is incorrect"


def test_admin_password_reset_still_works_through_user_patch(
    client: APIClient,
    admin_headers: dict[str, str],
    participant: dict[str, str],
) -> None:
    reset = client.patch(
        f"/api/users/{participant['id']}",
        headers=admin_headers,
        json={"password": "admin-reset-pass"},
    )
    assert reset.status_code == 200, reset.text

    old_login = client.post(
        "/api/auth/login",
        json={"username": participant["username"], "password": participant["password"]},
    )
    assert old_login.status_code == 401

    new_login = client.post(
        "/api/auth/login",
        json={"username": participant["username"], "password": "admin-reset-pass"},
    )
    assert new_login.status_code == 200, new_login.text


def test_access_token_expiration_uses_configured_minutes(client: APIClient, participant: dict[str, str]) -> None:
    original_minutes = settings.access_token_minutes
    try:
        settings.access_token_minutes = 7
        before = int(time.time())
        response = client.post(
            "/api/auth/login",
            json={"username": participant["username"], "password": participant["password"]},
        )
        after = int(time.time())
        assert response.status_code == 200, response.text
    finally:
        settings.access_token_minutes = original_minutes

    payload = jwt.decode(response.json()["access_token"], settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    assert payload["username"] == participant["username"]
    assert before + 7 * 60 <= payload["exp"] <= after + 7 * 60 + 1


def test_login_rate_limit_can_lock_repeated_failures(client: APIClient, participant: dict[str, str]) -> None:
    original_enabled = settings.login_rate_limit_enabled
    original_attempts = settings.login_rate_limit_attempts
    original_window = settings.login_rate_limit_window_seconds
    original_lockout = settings.login_rate_limit_lockout_seconds
    try:
        settings.login_rate_limit_enabled = True
        settings.login_rate_limit_attempts = 2
        settings.login_rate_limit_window_seconds = 60
        settings.login_rate_limit_lockout_seconds = 60
        LOGIN_ATTEMPTS.clear()
        LOGIN_LOCKED_UNTIL.clear()

        for _ in range(2):
            response = client.post(
                "/api/auth/login",
                json={"username": participant["username"], "password": "bad-pass"},
            )
            assert response.status_code == 401

        locked = client.post(
            "/api/auth/login",
            json={"username": participant["username"], "password": participant["password"]},
        )
        assert locked.status_code == 429
        assert locked.json()["detail"] == "Too many login attempts"
    finally:
        settings.login_rate_limit_enabled = original_enabled
        settings.login_rate_limit_attempts = original_attempts
        settings.login_rate_limit_window_seconds = original_window
        settings.login_rate_limit_lockout_seconds = original_lockout
        LOGIN_ATTEMPTS.clear()
        LOGIN_LOCKED_UNTIL.clear()


@pytest.mark.parametrize(
    ("filename", "content", "content_type"),
    [
        (
            "users.csv",
            "username,password,display_name,role\ncsv_user,csv-pass,CSV User,participant\n",
            "text/csv",
        ),
        (
            "users.json",
            json.dumps(
                [
                    {
                        "username": "json_user",
                        "password": "json-pass",
                        "display_name": "JSON User",
                        "role": "participant",
                    }
                ]
            ),
            "application/json",
        ),
        (
            "users.yaml",
            "- username: yaml_user\n  password: yaml-pass\n  display_name: YAML User\n  role: participant\n",
            "application/x-yaml",
        ),
    ],
)
def test_import_users_from_csv_json_and_yaml(
    client: APIClient,
    admin_headers: dict[str, str],
    filename: str,
    content: str,
    content_type: str,
) -> None:
    response = client.post(
        "/api/users/import",
        headers=admin_headers,
        files={"file": (filename, content, content_type)},
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"created": 1, "skipped": 0, "errors": []}


def test_import_skips_existing_username_duplicates(client: APIClient, admin_headers: dict[str, str]) -> None:
    first = client.post(
        "/api/users/import",
        headers=admin_headers,
        files={
            "file": (
                "users.json",
                json.dumps([{"username": "repeat_user", "password": "first-pass"}]),
                "application/json",
            )
        },
    )
    assert first.status_code == 200, first.text
    assert first.json()["created"] == 1

    duplicate = client.post(
        "/api/users/import",
        headers=admin_headers,
        files={
            "file": (
                "users.yaml",
                "- username: repeat_user\n  password: second-pass\n",
                "application/x-yaml",
            )
        },
    )

    assert duplicate.status_code == 200, duplicate.text
    assert duplicate.json()["created"] == 0
    assert duplicate.json()["skipped"] == 1
    assert "already exists" in duplicate.json()["errors"][0]
