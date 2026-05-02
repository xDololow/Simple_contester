import json

import pytest

from conftest import APIClient


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
