import io
import json
import zipfile
from datetime import datetime, timedelta
from typing import Any


def zip_files(content: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        return {info.filename: archive.read(info) for info in archive.infolist() if not info.is_dir()}


def make_zip(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def test_task_package_export_contains_metadata_statement_and_tests(
    client: Any,
    admin_headers: dict[str, str],
    demo_task: dict[str, Any],
) -> None:
    tests = client.get(f"/api/tasks/{demo_task['id']}/tests", headers=admin_headers).json()
    patched = client.patch(
        f"/api/tests/{tests[1]['id']}",
        headers=admin_headers,
        json={"points": 40, "group_name": "hidden"},
    )
    assert patched.status_code == 200, patched.text

    response = client.get(f"/api/tasks/{demo_task['id']}/package", headers=admin_headers)

    assert response.status_code == 200, response.text
    files = zip_files(response.content)
    assert set(files) == {"metadata.json", "statement.md", "tests/001.in", "tests/001.out", "tests/002.in", "tests/002.out"}
    metadata = json.loads(files["metadata.json"].decode("utf-8"))
    assert metadata["format_version"] == 2
    assert metadata["type"] == "task"
    assert metadata["task"]["title"] == "A + B"
    assert metadata["task"]["partial_scoring"] is False
    assert metadata["task"]["scoring_policy"] == "all_or_nothing"
    assert metadata["task"]["language_templates"] == {}
    assert metadata["task"]["checker"]["enabled"] is False
    assert metadata["task"]["validator"]["enabled"] is False
    assert metadata["task"]["interactor"]["enabled"] is False
    assert metadata["tests"] == [
        {"name": "001", "is_sample": True, "points": None, "group_name": None},
        {"name": "002", "is_sample": False, "points": 40.0, "group_name": "hidden"},
    ]
    assert files["statement.md"].decode("utf-8") == "Read two integers and print their sum."
    assert files["tests/001.in"].decode("utf-8") == "2 3\n"


def test_task_package_import_creates_standalone_task_and_tests(
    client: Any,
    admin_headers: dict[str, str],
    demo_task: dict[str, Any],
) -> None:
    exported = client.get(f"/api/tasks/{demo_task['id']}/package", headers=admin_headers)
    assert exported.status_code == 200, exported.text

    response = client.post(
        "/api/tasks/import-package",
        headers=admin_headers,
        files={"file": ("task.zip", exported.content, "application/zip")},
    )

    assert response.status_code == 200, response.text
    report = response.json()
    assert report["created_tasks"] == 1
    assert report["created_tests"] == 2
    imported_task_id = report["task_ids"][0]
    task = client.get(f"/api/tasks/{imported_task_id}", headers=admin_headers).json()
    assert task["title"] == "A + B"
    assert task["contest_id"] is None
    assert task["contest_ids"] == []
    assert task["current_version_number"] == 1
    tests = client.get(f"/api/tasks/{imported_task_id}/tests", headers=admin_headers).json()
    assert [test["is_sample"] for test in tests] == [True, False]
    assert [test["points"] for test in tests] == [None, None]
    assert [test["group_name"] for test in tests] == [None, None]
    assert tests[1]["output_data"] == "42\n"


def test_v2_task_package_import_preserves_scoring_metadata(client: Any, admin_headers: dict[str, str]) -> None:
    archive = make_zip(
        {
            "metadata.json": json.dumps(
                {
                    "format": "simple-contester-package",
                    "format_version": 2,
                    "type": "task",
                    "task": {
                        "title": "Scored",
                        "statement_file": "statement.md",
                        "input_format": "stdin",
                        "output_format": "stdout",
                        "samples": [],
                        "time_limit_ms": 1500,
                        "memory_limit_mb": 128,
                        "points": 100,
                        "partial_scoring": True,
                        "scoring_policy": "partial",
                        "language_templates": {},
                        "checker": {"enabled": False, "type": None},
                        "validator": {"enabled": False, "type": None},
                        "interactor": {"enabled": False, "type": None},
                    },
                    "tests": [
                        {"name": "001", "is_sample": True, "points": None, "group_name": None},
                        {"name": "002", "is_sample": False, "points": 35.5, "group_name": "main"},
                    ],
                }
            ),
            "statement.md": "Scored statement",
            "tests/001.in": "1\n",
            "tests/001.out": "1\n",
            "tests/002.in": "2\n",
            "tests/002.out": "2\n",
        }
    )

    response = client.post(
        "/api/tasks/import-package",
        headers=admin_headers,
        files={"file": ("scored.zip", archive, "application/zip")},
    )

    assert response.status_code == 200, response.text
    task = client.get(f"/api/tasks/{response.json()['task_ids'][0]}", headers=admin_headers).json()
    assert task["points"] == 100
    assert task["partial_scoring"] is True
    assert task["time_limit_ms"] == 1500
    tests = client.get(f"/api/tasks/{response.json()['task_ids'][0]}/tests", headers=admin_headers).json()
    assert [test["points"] for test in tests] == [None, 35.5]
    assert [test["group_name"] for test in tests] == [None, "main"]


def test_v1_task_package_import_still_works(client: Any, admin_headers: dict[str, str]) -> None:
    archive = make_zip(
        {
            "metadata.json": json.dumps(
                {
                    "format": "simple-contester-package",
                    "format_version": 1,
                    "type": "task",
                    "task": {"title": "Legacy", "points": 50, "partial_scoring": False},
                    "tests": [{"name": "001", "is_sample": False, "points": 12.5, "group_name": "legacy"}],
                }
            ),
            "statement.txt": "Legacy statement",
            "tests/001.in": "in\n",
            "tests/001.out": "out\n",
        }
    )

    response = client.post(
        "/api/tasks/import-package",
        headers=admin_headers,
        files={"file": ("legacy.zip", archive, "application/zip")},
    )

    assert response.status_code == 200, response.text
    task = client.get(f"/api/tasks/{response.json()['task_ids'][0]}", headers=admin_headers).json()
    assert task["title"] == "Legacy"
    tests = client.get(f"/api/tasks/{task['id']}/tests", headers=admin_headers).json()
    assert tests[0]["points"] == 12.5
    assert tests[0]["group_name"] == "legacy"


def test_contest_package_export_import_roundtrip(
    client: Any,
    admin_headers: dict[str, str],
    demo_contest: dict[str, Any],
    demo_task: dict[str, Any],
) -> None:
    starts_at = datetime.fromisoformat(demo_contest["starts_at"])
    updated = client.patch(
        f"/api/contests/{demo_contest['id']}",
        headers=admin_headers,
        json={
            "registration_enabled": True,
            "registration_requires_approval": False,
            "scoreboard_freeze_at": (starts_at + timedelta(minutes=20)).isoformat(),
            "scoreboard_unfrozen": True,
        },
    )
    assert updated.status_code == 200, updated.text
    exported = client.get(f"/api/contests/{demo_contest['id']}/package", headers=admin_headers)
    assert exported.status_code == 200, exported.text
    files = zip_files(exported.content)
    assert "metadata.json" in files
    assert "tasks/001/metadata.json" in files
    assert "tasks/001/tests/002.out" in files
    metadata = json.loads(files["metadata.json"].decode("utf-8"))
    assert metadata["format_version"] == 2
    assert "users" not in metadata
    assert "submissions" not in metadata
    assert "registrations" not in metadata
    assert "results" not in metadata
    assert metadata["contest"]["time_mode"] == demo_contest["time_mode"]
    assert metadata["contest"]["participation_mode"] == demo_contest["participation_mode"]
    assert metadata["contest"]["registration_enabled"] is True
    assert metadata["contest"]["registration_requires_approval"] is False
    assert metadata["contest"]["scoreboard_freeze_at"] is not None
    assert metadata["contest"]["scoreboard_unfrozen"] is True
    assert metadata["tasks"] == [{"dir": "tasks/001", "position": 0, "title": demo_task["title"]}]

    response = client.post(
        "/api/contests/import-package",
        headers=admin_headers,
        files={"file": ("contest.zip", exported.content, "application/zip")},
    )

    assert response.status_code == 200, response.text
    report = response.json()
    assert report["created_tasks"] == 1
    assert report["created_tests"] == 2
    imported_contest = client.get(f"/api/contests/{report['contest_id']}", headers=admin_headers).json()
    assert imported_contest["title"] == demo_contest["title"]
    assert imported_contest["status"] == "draft"
    assert imported_contest["is_public"] is False
    assert imported_contest["registration_enabled"] is True
    assert imported_contest["registration_requires_approval"] is False
    assert imported_contest["scoreboard_freeze_at"] is not None
    assert imported_contest["scoreboard_unfrozen"] is True
    imported_tasks = client.get(f"/api/contests/{report['contest_id']}/tasks", headers=admin_headers).json()
    assert len(imported_tasks) == 1
    assert imported_tasks[0]["title"] == demo_task["title"]
    assert imported_tasks[0]["current_version_number"] == 1
    tests = client.get(f"/api/tasks/{imported_tasks[0]['id']}/tests", headers=admin_headers).json()
    assert [test["input_data"] for test in tests] == ["2 3\n", "40 2\n"]


def test_task_package_import_rejects_malicious_zip_path(client: Any, admin_headers: dict[str, str]) -> None:
    archive = make_zip(
        {
            "metadata.json": json.dumps(
                {
                    "format": "simple-contester-package",
                    "format_version": 1,
                    "type": "task",
                    "task": {"title": "Unsafe"},
                    "tests": [],
                }
            ),
            "statement.md": "Safe statement",
            "../evil.txt": "bad",
        }
    )

    response = client.post(
        "/api/tasks/import-package",
        headers=admin_headers,
        files={"file": ("unsafe.zip", archive, "application/zip")},
    )

    assert response.status_code == 400
    assert "Unsafe package path" in response.text


def test_task_package_import_rejects_unsupported_format_version(client: Any, admin_headers: dict[str, str]) -> None:
    archive = make_zip(
        {
            "metadata.json": json.dumps(
                {
                    "format": "simple-contester-package",
                    "format_version": 999,
                    "type": "task",
                    "task": {"title": "Future"},
                    "tests": [],
                }
            ),
            "statement.md": "Future statement",
        }
    )

    response = client.post(
        "/api/tasks/import-package",
        headers=admin_headers,
        files={"file": ("future.zip", archive, "application/zip")},
    )

    assert response.status_code == 400
    assert "Unsupported package format_version" in response.text
