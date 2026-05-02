import os

import httpx
import pytest


@pytest.mark.smoke
def test_running_api_login_smoke() -> None:
    api_base = os.environ.get("SIMPLE_CONTESTER_API_BASE")
    if not api_base:
        pytest.skip("Set SIMPLE_CONTESTER_API_BASE, for example http://localhost:8001")

    response = httpx.post(
        f"{api_base.rstrip('/')}/api/auth/login",
        json={
            "username": os.environ.get("SIMPLE_CONTESTER_ADMIN_USERNAME", "admin"),
            "password": os.environ.get("SIMPLE_CONTESTER_ADMIN_PASSWORD", "admin"),
        },
        timeout=5,
    )

    assert response.status_code == 200, response.text
    assert response.json()["token_type"] == "bearer"
