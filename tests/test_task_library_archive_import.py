import io
import zipfile
from datetime import datetime, timedelta
from typing import Any


def create_contest(client: Any, admin_headers: dict[str, str], title: str) -> dict[str, Any]:
    now = datetime.utcnow()
    response = client.post(
        "/api/contests",
        headers=admin_headers,
        json={
            "title": title,
            "description": "",
            "status": "running",
            "time_mode": "fixed",
            "starts_at": (now - timedelta(minutes=5)).isoformat(),
            "ends_at": (now + timedelta(hours=1)).isoformat(),
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def make_zip(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def test_create_standalone_task(client: Any, admin_headers: dict[str, str]) -> None:
    response = client.post(
        "/api/tasks",
        headers=admin_headers,
        json={
            "title": "Standalone",
            "statement": "# Statement",
            "input_format": "",
            "output_format": "",
            "samples": [],
            "time_limit_ms": 1000,
            "memory_limit_mb": 128,
            "points": 50,
        },
    )

    assert response.status_code == 200, response.text
    task = response.json()
    assert task["contest_id"] is None
    assert task["contest_ids"] == []
    assert task["partial_scoring"] is False


def test_attach_task_to_two_contests(client: Any, admin_headers: dict[str, str]) -> None:
    first = create_contest(client, admin_headers, "First")
    second = create_contest(client, admin_headers, "Second")
    task_response = client.post(
        "/api/tasks",
        headers=admin_headers,
        json={"title": "Shared", "statement": "Shared task", "contest_ids": [first["id"], second["id"]]},
    )
    assert task_response.status_code == 200, task_response.text
    task_id = task_response.json()["id"]

    first_tasks = client.get(f"/api/contests/{first['id']}/tasks", headers=admin_headers)
    second_tasks = client.get(f"/api/contests/{second['id']}/tasks", headers=admin_headers)

    assert first_tasks.status_code == 200, first_tasks.text
    assert second_tasks.status_code == 200, second_tasks.text
    assert [task["id"] for task in first_tasks.json()] == [task_id]
    assert [task["id"] for task in second_tasks.json()] == [task_id]


def test_archive_import_creates_pairs_and_reports_unmatched(client: Any, admin_headers: dict[str, str]) -> None:
    task_response = client.post("/api/tasks", headers=admin_headers, json={"title": "Zip", "statement": "Zip task"})
    assert task_response.status_code == 200, task_response.text
    task_id = task_response.json()["id"]
    archive = make_zip({"001.in": "1 2\n", "001.out": "3\n", "a.in": "x\n", "notes.txt": "skip"})

    response = client.post(
        f"/api/tasks/{task_id}/tests/import-archive",
        headers=admin_headers,
        files={"file": ("tests.zip", archive, "application/zip")},
    )

    assert response.status_code == 200, response.text
    report = response.json()
    assert report["created"] == 1
    assert "a.in: missing matching .out" in report["skipped"]
    assert "notes.txt: unsupported file name" in report["skipped"]
    tests = client.get(f"/api/tasks/{task_id}/tests", headers=admin_headers).json()
    assert len(tests) == 1
    assert tests[0]["input_data"] == "1 2\n"
    assert tests[0]["output_data"] == "3\n"
    assert tests[0]["is_sample"] is False


def test_archive_import_ignores_traversal_names(client: Any, admin_headers: dict[str, str]) -> None:
    task_response = client.post("/api/tasks", headers=admin_headers, json={"title": "Traversal", "statement": "Safe"})
    assert task_response.status_code == 200, task_response.text
    task_id = task_response.json()["id"]
    archive = make_zip({"../evil.in": "bad", "../evil.out": "bad", "safe.in": "ok\n", "safe.out": "ok\n"})

    response = client.post(
        f"/api/tasks/{task_id}/tests/import-archive",
        headers=admin_headers,
        files={"file": ("tests.zip", archive, "application/zip")},
    )

    assert response.status_code == 200, response.text
    report = response.json()
    assert report["created"] == 1
    assert any("unsafe path" in item for item in report["skipped"])
    tests = client.get(f"/api/tasks/{task_id}/tests", headers=admin_headers).json()
    assert len(tests) == 1
    assert tests[0]["input_data"] == "ok\n"
