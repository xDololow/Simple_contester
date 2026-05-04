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
    assert data["submissions"]["recent_1h"] == 2
    assert data["submissions"]["recent_24h"] == 2
    assert data["submissions"]["accepted_rate"] == 50
    assert data["submissions"]["average_score"] == 62.5
    assert data["judgers"]["running_by_judger_id"] == {"judge-b": 1}
    assert data["judgers"]["recent_finished_by_judger_id"] == {"judge-a": 1}
    assert data["system"]["database_ok"] is True
    assert data["system"]["app_version"] == "unknown"
