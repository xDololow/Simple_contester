from datetime import datetime, timedelta

from sqlalchemy import select

from app.database import SessionLocal
from app.models import Language, Submission, SubmissionVerdict
from conftest import APIClient


def test_participant_cannot_fetch_admin_stats(client: APIClient, participant_headers: dict[str, str]) -> None:
    response = client.get("/api/admin/stats", headers=participant_headers)

    assert response.status_code == 403
    assert response.json()["detail"] == "Admin role required"


def test_admin_stats_contains_expected_counters(
    client: APIClient,
    admin_headers: dict[str, str],
    participant_headers: dict[str, str],
    participant: dict,
    demo_contest: dict,
    demo_task: dict,
) -> None:
    team_response = client.post("/api/teams", headers=admin_headers, json={"name": "Stats Team", "user_ids": [participant["id"]]})
    assert team_response.status_code == 200, team_response.text

    first_submission = client.post(
        f"/api/contests/{demo_contest['id']}/tasks/{demo_task['id']}/submissions",
        headers=participant_headers,
        json={"language": Language.python.value, "source_code": "print(sum(map(int, input().split())))"},
    )
    assert first_submission.status_code == 200, first_submission.text
    second_submission = client.post(
        f"/api/contests/{demo_contest['id']}/tasks/{demo_task['id']}/submissions",
        headers=participant_headers,
        json={"language": Language.cpp17.value, "source_code": "#include <iostream>\nint main(){}"},
    )
    assert second_submission.status_code == 200, second_submission.text

    now = datetime.utcnow()
    with SessionLocal() as db:
        accepted = db.scalar(select(Submission).where(Submission.id == first_submission.json()["id"]))
        running = db.scalar(select(Submission).where(Submission.id == second_submission.json()["id"]))
        assert accepted is not None
        assert running is not None
        accepted.verdict = SubmissionVerdict.accepted
        accepted.score = 100
        accepted.started_at = now - timedelta(minutes=5)
        accepted.finished_at = now - timedelta(minutes=4)
        accepted.judger_id = "judge-a"
        running.verdict = SubmissionVerdict.running
        running.score = 25
        running.started_at = now - timedelta(minutes=1)
        running.judger_id = "judge-b"
        db.commit()

    response = client.get("/api/admin/stats", headers=admin_headers)

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["users"]["total"] == 2
    assert data["users"]["active"] == 2
    assert data["users"]["admin"] == 1
    assert data["users"]["participant"] == 1
    assert data["teams_total"] == 1
    assert data["contests"]["total"] == 1
    assert data["contests"]["by_status"]["running"] == 1
    assert data["contests"]["public"] == 1
    assert data["contests"]["individual"] == 1
    assert data["tasks_total"] == 1
    assert data["tests_total"] == 2
    assert data["submissions"]["total"] == 2
    assert data["submissions"]["by_verdict"]["Accepted"] == 1
    assert data["submissions"]["by_verdict"]["Running"] == 1
    assert data["submissions"]["by_language"]["python"] == 1
    assert data["submissions"]["by_language"]["cpp17"] == 1
    assert data["submissions"]["running"] == 1
    assert data["submissions"]["queue_depth"] == 0
    assert data["submissions"]["running_count"] == 1
    assert data["submissions"]["stale_running_count"] == 0
    assert data["submissions"]["finished_1h"] == 1
    assert data["submissions"]["finished_24h"] == 1
    assert data["submissions"]["average_judging_time_seconds"] == 60
    assert data["submissions"]["p95_judging_time_seconds"] == 60
    assert data["submissions"]["internal_error_count"] == 0
    assert data["submissions"]["internal_error_rate"] == 0
    assert data["submissions"]["recent_1h"] == 2
    assert data["submissions"]["recent_24h"] == 2
    assert data["submissions"]["accepted_rate"] == 50
    assert data["submissions"]["average_score"] == 62.5
    assert data["judgers"]["running_by_judger_id"] == {"judge-b": 1}
    assert data["judgers"]["recent_finished_by_judger_id"] == {"judge-a": 1}
    assert data["system"]["database_ok"] is True
    assert data["system"]["app_version"] == "unknown"


def test_admin_stats_returns_queue_depth_and_oldest_queued_age(
    client: APIClient,
    admin_headers: dict[str, str],
    participant_headers: dict[str, str],
    demo_contest: dict,
    demo_task: dict,
) -> None:
    submission = client.post(
        f"/api/contests/{demo_contest['id']}/tasks/{demo_task['id']}/submissions",
        headers=participant_headers,
        json={"language": Language.python.value, "source_code": "print(42)"},
    )
    assert submission.status_code == 200, submission.text

    with SessionLocal() as db:
        queued = db.scalar(select(Submission).where(Submission.id == submission.json()["id"]))
        assert queued is not None
        queued.created_at = datetime.utcnow() - timedelta(minutes=7)
        db.commit()

    response = client.get("/api/admin/stats", headers=admin_headers)

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["submissions"]["queue_depth"] == 1
    assert data["submissions"]["oldest_queued_age_seconds"] >= 7 * 60


def test_admin_stats_returns_throughput_and_latency_for_finished_submissions(
    client: APIClient,
    admin_headers: dict[str, str],
    participant_headers: dict[str, str],
    demo_contest: dict,
    demo_task: dict,
) -> None:
    first = client.post(
        f"/api/contests/{demo_contest['id']}/tasks/{demo_task['id']}/submissions",
        headers=participant_headers,
        json={"language": Language.python.value, "source_code": "print(1)"},
    )
    second = client.post(
        f"/api/contests/{demo_contest['id']}/tasks/{demo_task['id']}/submissions",
        headers=participant_headers,
        json={"language": Language.cpp17.value, "source_code": "int main(){}"},
    )
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text

    now = datetime.utcnow()
    with SessionLocal() as db:
        first_submission = db.scalar(select(Submission).where(Submission.id == first.json()["id"]))
        second_submission = db.scalar(select(Submission).where(Submission.id == second.json()["id"]))
        assert first_submission is not None
        assert second_submission is not None
        first_submission.verdict = SubmissionVerdict.accepted
        first_submission.started_at = now - timedelta(minutes=20)
        first_submission.finished_at = now - timedelta(minutes=19, seconds=30)
        second_submission.verdict = SubmissionVerdict.internal_error
        second_submission.started_at = now - timedelta(minutes=10)
        second_submission.finished_at = now - timedelta(minutes=8)
        db.commit()

    response = client.get("/api/admin/stats", headers=admin_headers)

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["submissions"]["finished_1h"] == 2
    assert data["submissions"]["finished_24h"] == 2
    assert data["submissions"]["average_judging_time_seconds"] == 75
    assert data["submissions"]["p95_judging_time_seconds"] == 120
    assert data["submissions"]["internal_error_count"] == 1
    assert data["submissions"]["internal_error_rate"] == 50


def test_admin_stats_counts_stale_running_submissions(
    client: APIClient,
    admin_headers: dict[str, str],
    participant_headers: dict[str, str],
    demo_contest: dict,
    demo_task: dict,
) -> None:
    stale = client.post(
        f"/api/contests/{demo_contest['id']}/tasks/{demo_task['id']}/submissions",
        headers=participant_headers,
        json={"language": Language.python.value, "source_code": "print(1)"},
    )
    fresh = client.post(
        f"/api/contests/{demo_contest['id']}/tasks/{demo_task['id']}/submissions",
        headers=participant_headers,
        json={"language": Language.python.value, "source_code": "print(2)"},
    )
    assert stale.status_code == 200, stale.text
    assert fresh.status_code == 200, fresh.text

    now = datetime.utcnow()
    with SessionLocal() as db:
        stale_submission = db.scalar(select(Submission).where(Submission.id == stale.json()["id"]))
        fresh_submission = db.scalar(select(Submission).where(Submission.id == fresh.json()["id"]))
        assert stale_submission is not None
        assert fresh_submission is not None
        stale_submission.verdict = SubmissionVerdict.running
        stale_submission.started_at = now - timedelta(minutes=11)
        fresh_submission.verdict = SubmissionVerdict.running
        fresh_submission.started_at = now - timedelta(minutes=3)
        db.commit()

    response = client.get("/api/admin/stats", headers=admin_headers)

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["submissions"]["running_count"] == 2
    assert data["submissions"]["stale_running_count"] == 1
