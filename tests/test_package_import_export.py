import io
import json
import zipfile
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
    assert metadata["type"] == "task"
    assert metadata["task"]["title"] == "A + B"
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
    tests = client.get(f"/api/tasks/{imported_task_id}/tests", headers=admin_headers).json()
    assert [test["is_sample"] for test in tests] == [True, False]
    assert [test["points"] for test in tests] == [None, None]
    assert [test["group_name"] for test in tests] == [None, None]
    assert tests[1]["output_data"] == "42\n"


def test_task_package_import_preserves_test_points_and_group_name(client: Any, admin_headers: dict[str, str]) -> None:
    archive = make_zip(
        {
            "metadata.json": json.dumps(
                {
                    "format": "simple-contester-package",
                    "format_version": 1,
                    "type": "task",
                    "task": {"title": "Scored", "points": 100, "partial_scoring": True},
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
    tests = client.get(f"/api/tasks/{response.json()['task_ids'][0]}/tests", headers=admin_headers).json()
    assert [test["points"] for test in tests] == [None, 35.5]
    assert [test["group_name"] for test in tests] == [None, "main"]


def test_contest_package_export_import_roundtrip(
    client: Any,
    admin_headers: dict[str, str],
    demo_contest: dict[str, Any],
    demo_task: dict[str, Any],
) -> None:
    exported = client.get(f"/api/contests/{demo_contest['id']}/package", headers=admin_headers)
    assert exported.status_code == 200, exported.text
    files = zip_files(exported.content)
    assert "metadata.json" in files
    assert "tasks/001/metadata.json" in files
    assert "tasks/001/tests/002.out" in files

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
    imported_tasks = client.get(f"/api/contests/{report['contest_id']}/tasks", headers=admin_headers).json()
    assert len(imported_tasks) == 1
    assert imported_tasks[0]["title"] == demo_task["title"]
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
