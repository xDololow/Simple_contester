from datetime import datetime, timedelta
from typing import Any, Callable

from app.database import SessionLocal
from app.models import Submission, SubmissionVerdict
from conftest import APIClient


SCORING_MODES = ("ioi", "ecoo", "icpc", "atcoder")


def create_running_contest(client: APIClient, admin_headers: dict[str, str], title: str) -> dict[str, Any]:
    now = datetime.utcnow()
    response = client.post(
        "/api/contests",
        headers=admin_headers,
        json={
            "title": title,
            "description": "Scoring comparison fixture",
            "status": "running",
            "is_public": False,
            "time_mode": "fixed",
            "starts_at": (now - timedelta(minutes=5)).isoformat(),
            "ends_at": (now + timedelta(hours=1)).isoformat(),
            "individual_duration_minutes": None,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def create_task(client: APIClient, admin_headers: dict[str, str], contest_id: int, title: str, points: float) -> dict[str, Any]:
    response = client.post(
        "/api/tasks",
        headers=admin_headers,
        json={
            "contest_id": contest_id,
            "title": title,
            "statement": f"{title} statement.",
            "input_format": "",
            "output_format": "",
            "samples": [],
            "time_limit_ms": 1000,
            "memory_limit_mb": 128,
            "points": points,
            "partial_scoring": True,
            "tests": [{"input_data": "1\n", "output_data": "1\n", "is_sample": False}],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def submit_and_mark(
    client: APIClient,
    contest_id: int,
    task_id: int,
    headers: dict[str, str],
    verdict: SubmissionVerdict,
    score: float,
    created_at: datetime,
) -> dict[str, Any]:
    response = client.post(
        f"/api/contests/{contest_id}/tasks/{task_id}/submissions",
        headers=headers,
        json={"language": "python", "source_code": "print(input())"},
    )
    assert response.status_code == 200, response.text
    with SessionLocal() as db:
        submission = db.get(Submission, response.json()["id"])
        assert submission is not None
        submission.verdict = verdict
        submission.score = score
        submission.created_at = created_at
        submission.finished_at = created_at
        db.commit()
    return response.json()


def rows_by_name(client: APIClient, headers: dict[str, str], contest_id: int) -> dict[str, dict[str, Any]]:
    response = client.get(f"/api/contests/{contest_id}/scoreboard", headers=headers)
    assert response.status_code == 200, response.text
    return {row["username"]: row for row in response.json()}


def ordered_names(client: APIClient, headers: dict[str, str], contest_id: int) -> list[str]:
    response = client.get(f"/api/contests/{contest_id}/scoreboard", headers=headers)
    assert response.status_code == 200, response.text
    return [row["username"] for row in response.json()]


def seed_individual_comparison(
    client: APIClient,
    admin_headers: dict[str, str],
    create_user: Callable[..., dict[str, Any]],
    auth_headers: Callable[[str, str], dict[str, str]],
) -> tuple[dict[str, Any], dict[str, str]]:
    alice = create_user(username="compare_alice", password="score-pass", display_name="Compare Alice")
    bob = create_user(username="compare_bob", password="score-pass", display_name="Compare Bob")
    alice_headers = auth_headers(alice["username"], "score-pass")
    bob_headers = auth_headers(bob["username"], "score-pass")
    contest = create_running_contest(client, admin_headers, "Scoring Comparison")
    task_a = create_task(client, admin_headers, contest["id"], "A", 100)
    task_b = create_task(client, admin_headers, contest["id"], "B", 200)
    assigned = client.put(
        f"/api/contests/{contest['id']}/participants",
        headers=admin_headers,
        json={"user_ids": [alice["id"], bob["id"]]},
    )
    assert assigned.status_code == 200, assigned.text
    start = datetime.fromisoformat(contest["starts_at"].replace("Z", "+00:00")).replace(tzinfo=None)

    submit_and_mark(client, contest["id"], task_a["id"], alice_headers, SubmissionVerdict.wrong_answer, 70, start + timedelta(minutes=10))
    submit_and_mark(client, contest["id"], task_b["id"], alice_headers, SubmissionVerdict.wrong_answer, 0, start + timedelta(minutes=20))
    submit_and_mark(client, contest["id"], task_b["id"], alice_headers, SubmissionVerdict.accepted, 200, start + timedelta(minutes=50))
    submit_and_mark(client, contest["id"], task_a["id"], bob_headers, SubmissionVerdict.accepted, 40, start + timedelta(minutes=15))
    submit_and_mark(client, contest["id"], task_b["id"], bob_headers, SubmissionVerdict.accepted, 200, start + timedelta(minutes=80))
    return contest, alice_headers


def test_individual_scoreboard_modes_are_comparable_on_same_submissions(
    client: APIClient,
    admin_headers: dict[str, str],
    create_user: Callable[..., dict[str, Any]],
    auth_headers: Callable[[str, str], dict[str, str]],
) -> None:
    contest, headers = seed_individual_comparison(client, admin_headers, create_user, auth_headers)

    expected = {
        "ioi": {
            "order": ["compare_alice", "compare_bob"],
            "compare_alice": {"score": 270, "penalty": 0},
            "compare_bob": {"score": 240, "penalty": 0},
        },
        "ecoo": {
            "order": ["compare_alice", "compare_bob"],
            "compare_alice": {"score": 270, "penalty": 50},
            "compare_bob": {"score": 240, "penalty": 95},
        },
        "icpc": {
            "order": ["compare_bob", "compare_alice"],
            "compare_alice": {"score": 1, "penalty": 70},
            "compare_bob": {"score": 2, "penalty": 95},
        },
        "atcoder": {
            "order": ["compare_bob", "compare_alice"],
            "compare_alice": {"score": 200, "penalty": 70},
            "compare_bob": {"score": 240, "penalty": 95},
        },
    }

    for mode in SCORING_MODES:
        updated = client.patch(f"/api/contests/{contest['id']}", headers=admin_headers, json={"scoring_mode": mode})
        assert updated.status_code == 200, updated.text
        assert ordered_names(client, headers, contest["id"]) == expected[mode]["order"]
        rows = rows_by_name(client, headers, contest["id"])
        for username in ("compare_alice", "compare_bob"):
            assert rows[username]["score"] == expected[mode][username]["score"]
            assert rows[username]["penalty"] == expected[mode][username]["penalty"]


def test_team_scoreboard_modes_are_comparable_on_same_submissions(
    client: APIClient,
    admin_headers: dict[str, str],
    create_user: Callable[..., dict[str, Any]],
    auth_headers: Callable[[str, str], dict[str, str]],
) -> None:
    alice = create_user(username="team_compare_alice", password="score-pass")
    bob = create_user(username="team_compare_bob", password="score-pass")
    alice_headers = auth_headers(alice["username"], "score-pass")
    bob_headers = auth_headers(bob["username"], "score-pass")
    contest = create_running_contest(client, admin_headers, "Team Scoring Comparison")
    updated = client.patch(f"/api/contests/{contest['id']}", headers=admin_headers, json={"participation_mode": "team"})
    assert updated.status_code == 200, updated.text
    task_a = create_task(client, admin_headers, contest["id"], "A", 100)
    task_b = create_task(client, admin_headers, contest["id"], "B", 200)
    alpha = client.post("/api/teams", headers=admin_headers, json={"name": "Alpha", "user_ids": [alice["id"]]})
    beta = client.post("/api/teams", headers=admin_headers, json={"name": "Beta", "user_ids": [bob["id"]]})
    assert alpha.status_code == 200, alpha.text
    assert beta.status_code == 200, beta.text
    assigned = client.put(
        f"/api/contests/{contest['id']}/teams",
        headers=admin_headers,
        json={"team_ids": [alpha.json()["id"], beta.json()["id"]]},
    )
    assert assigned.status_code == 200, assigned.text
    start = datetime.fromisoformat(contest["starts_at"].replace("Z", "+00:00")).replace(tzinfo=None)

    submit_and_mark(client, contest["id"], task_a["id"], alice_headers, SubmissionVerdict.wrong_answer, 70, start + timedelta(minutes=10))
    submit_and_mark(client, contest["id"], task_b["id"], alice_headers, SubmissionVerdict.wrong_answer, 0, start + timedelta(minutes=20))
    submit_and_mark(client, contest["id"], task_b["id"], alice_headers, SubmissionVerdict.accepted, 200, start + timedelta(minutes=50))
    submit_and_mark(client, contest["id"], task_a["id"], bob_headers, SubmissionVerdict.accepted, 40, start + timedelta(minutes=15))
    submit_and_mark(client, contest["id"], task_b["id"], bob_headers, SubmissionVerdict.accepted, 200, start + timedelta(minutes=80))

    for mode, expected_order in {
        "ioi": ["Alpha", "Beta"],
        "ecoo": ["Alpha", "Beta"],
        "icpc": ["Beta", "Alpha"],
        "atcoder": ["Beta", "Alpha"],
    }.items():
        updated = client.patch(f"/api/contests/{contest['id']}", headers=admin_headers, json={"scoring_mode": mode})
        assert updated.status_code == 200, updated.text
        assert ordered_names(client, alice_headers, contest["id"]) == expected_order
