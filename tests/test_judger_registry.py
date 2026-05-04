import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import select

from app.database import SessionLocal
from app.models import Language, Judger, JudgerEvent, Submission, SubmissionVerdict, TaskTest, TestResult
from conftest import APIClient


JUDGER_PATH = Path(__file__).resolve().parents[1] / "judger"
if str(JUDGER_PATH) not in sys.path:
    sys.path.insert(0, str(JUDGER_PATH))

import worker  # noqa: E402


def seed_judger(judger_id: str, last_seen_at: datetime, status: str = "idle") -> None:
    with SessionLocal() as db:
        db.add(
            Judger(
                judger_id=judger_id,
                hostname=f"{judger_id}.local",
                version="test",
                supported_languages=json.dumps(["python", "cpp17"]),
                sandbox_mode="subprocess",
                capabilities=json.dumps({"test": True}),
                status=status,
                current_submission_id=None,
                registered_at=last_seen_at,
                last_seen_at=last_seen_at,
                last_state_change_at=last_seen_at,
                enabled=True,
            )
        )
        db.commit()


def seed_judger_event(
    judger_id: str,
    event_type: str,
    submission_id: int | None = None,
    message: str | None = None,
    payload: dict | None = None,
    created_at: datetime | None = None,
) -> None:
    with SessionLocal() as db:
        db.add(
            JudgerEvent(
                judger_id=judger_id,
                event_type=event_type,
                submission_id=submission_id,
                message=message,
                payload=json.dumps(payload) if payload is not None else None,
                created_at=created_at or datetime.utcnow(),
            )
        )
        db.commit()


def test_admin_can_list_judgers(client: APIClient, admin_headers: dict[str, str]) -> None:
    seed_judger("judge-a", datetime.utcnow())

    response = client.get("/api/admin/judgers", headers=admin_headers)

    assert response.status_code == 200, response.text
    data = response.json()
    assert len(data) == 1
    assert data[0]["judger_id"] == "judge-a"
    assert data[0]["health"] == "active"
    assert data[0]["supported_languages"] == ["python", "cpp17"]
    assert data[0]["capabilities"] == {"test": True}


def test_participant_cannot_list_judgers(client: APIClient, participant_headers: dict[str, str]) -> None:
    response = client.get("/api/admin/judgers", headers=participant_headers)

    assert response.status_code == 403
    assert response.json()["detail"] == "Admin role required"


def test_judger_health_classifies_stale_and_offline(client: APIClient, admin_headers: dict[str, str]) -> None:
    now = datetime.utcnow()
    seed_judger("active-judge", now - timedelta(seconds=5))
    seed_judger("stale-judge", now - timedelta(seconds=30))
    seed_judger("offline-judge", now - timedelta(seconds=90))

    response = client.get("/api/admin/judgers", headers=admin_headers)

    assert response.status_code == 200, response.text
    health_by_id = {item["judger_id"]: item["health"] for item in response.json()}
    assert health_by_id == {
        "active-judge": "active",
        "offline-judge": "offline",
        "stale-judge": "stale",
    }


def test_judger_health_records_stale_and_missed_events(client: APIClient, admin_headers: dict[str, str]) -> None:
    now = datetime.utcnow()
    seed_judger("stale-judge", now - timedelta(seconds=30))
    seed_judger("offline-judge", now - timedelta(seconds=90))

    response = client.get("/api/admin/judgers", headers=admin_headers)
    assert response.status_code == 200, response.text
    response = client.get("/api/admin/judgers", headers=admin_headers)
    assert response.status_code == 200, response.text

    events_response = client.get("/api/admin/judger-events?limit=10", headers=admin_headers)

    assert events_response.status_code == 200, events_response.text
    events = {(event["judger_id"], event["event_type"]) for event in events_response.json()}
    assert ("stale-judge", "heartbeat_stale") in events
    assert ("offline-judge", "heartbeat_missed") in events
    assert len(events_response.json()) == 2


def test_worker_heartbeat_upserts_judger(monkeypatch) -> None:
    monkeypatch.setattr(worker, "JUDGER_ID", "worker-helper")
    monkeypatch.setattr(worker, "JUDGER_VERSION", "test-version")

    worker.register_or_update_judger("starting")
    worker.register_or_update_judger("running", current_submission_id=42, last_error="boom")

    with SessionLocal() as db:
        judgers = db.scalars(select(Judger).where(Judger.judger_id == "worker-helper")).all()

    assert len(judgers) == 1
    assert judgers[0].version == "test-version"
    assert judgers[0].status == "running"
    assert judgers[0].current_submission_id == 42
    assert judgers[0].last_error == "boom"
    assert "python" in json.loads(judgers[0].supported_languages)


def test_admin_can_fetch_latest_judger_events(client: APIClient, admin_headers: dict[str, str]) -> None:
    now = datetime.utcnow()
    seed_judger_event("judge-a", "started", created_at=now - timedelta(seconds=10))
    seed_judger_event("judge-b", "claimed_submission", submission_id=42, payload={"attempt_number": 2}, created_at=now)

    response = client.get("/api/admin/judger-events?limit=10", headers=admin_headers)

    assert response.status_code == 200, response.text
    data = response.json()
    assert [event["event_type"] for event in data] == ["claimed_submission", "started"]
    assert data[0]["judger_id"] == "judge-b"
    assert data[0]["submission_id"] == 42
    assert data[0]["payload"] == {"attempt_number": 2}


def test_participant_cannot_fetch_judger_events(client: APIClient, participant_headers: dict[str, str]) -> None:
    response = client.get("/api/admin/judger-events", headers=participant_headers)

    assert response.status_code == 403
    assert response.json()["detail"] == "Admin role required"


def test_judger_event_filter_by_judger_id(client: APIClient, admin_headers: dict[str, str]) -> None:
    seed_judger_event("judge-a", "started")
    seed_judger_event("judge-b", "started")
    seed_judger_event("judge-a", "finished_submission", submission_id=7)

    response = client.get("/api/admin/judgers/judge-a/events", headers=admin_headers)

    assert response.status_code == 200, response.text
    data = response.json()
    assert [event["judger_id"] for event in data] == ["judge-a", "judge-a"]
    assert {event["event_type"] for event in data} == {"started", "finished_submission"}


def test_worker_helper_writes_judger_event(monkeypatch) -> None:
    monkeypatch.setattr(worker, "JUDGER_ID", "event-helper")

    assert worker.write_judger_event(
        "claimed_submission",
        submission_id=99,
        message="claimed",
        payload={"claim_token": "token", "attempt_number": 1},
    )

    with SessionLocal() as db:
        events = db.scalars(select(JudgerEvent).where(JudgerEvent.judger_id == "event-helper")).all()

    assert len(events) == 1
    assert events[0].event_type == "claimed_submission"
    assert events[0].submission_id == 99
    assert events[0].message == "claimed"
    assert json.loads(events[0].payload or "{}") == {"claim_token": "token", "attempt_number": 1}


def create_submission(
    client: APIClient,
    participant_headers: dict[str, str],
    demo_contest: dict,
    demo_task: dict,
    source_code: str = "print(sum(map(int, input().split())))",
) -> int:
    response = client.post(
        f"/api/contests/{demo_contest['id']}/tasks/{demo_task['id']}/submissions",
        headers=participant_headers,
        json={"language": Language.python.value, "source_code": source_code},
    )
    assert response.status_code == 200, response.text
    return int(response.json()["id"])


def first_test_id(task_id: int) -> int:
    with SessionLocal() as db:
        test_id = db.scalar(select(TaskTest.id).where(TaskTest.task_id == task_id).order_by(TaskTest.id))
        assert test_id is not None
        return test_id


def test_worker_claim_sets_lease_metadata(
    client: APIClient,
    participant_headers: dict[str, str],
    demo_contest: dict,
    demo_task: dict,
    monkeypatch,
) -> None:
    submission_id = create_submission(client, participant_headers, demo_contest, demo_task)
    monkeypatch.setattr(worker, "JUDGER_ID", "lease-worker")
    monkeypatch.setattr(worker, "SUBMISSION_LEASE_SECONDS", 30)

    claimed = worker.acquire_submission()

    assert claimed is not None
    assert claimed["id"] == submission_id
    assert claimed["claim_token"]
    with SessionLocal() as db:
        submission = db.get(Submission, submission_id)
        assert submission is not None
        assert submission.verdict == SubmissionVerdict.running
        assert submission.judger_id == "lease-worker"
        assert submission.claim_token == claimed["claim_token"]
        assert submission.claimed_at is not None
        assert submission.claim_expires_at is not None
        assert submission.claim_expires_at > submission.claimed_at
        assert submission.attempt_number == 1


def test_worker_reclaims_expired_running_submission_until_max_attempts(
    client: APIClient,
    participant_headers: dict[str, str],
    demo_contest: dict,
    demo_task: dict,
    monkeypatch,
) -> None:
    requeued_id = create_submission(client, participant_headers, demo_contest, demo_task)
    failed_id = create_submission(client, participant_headers, demo_contest, demo_task)
    expired_at = datetime.utcnow() - timedelta(seconds=1)
    monkeypatch.setattr(worker, "SUBMISSION_MAX_ATTEMPTS", 3)
    with SessionLocal() as db:
        requeued = db.get(Submission, requeued_id)
        failed = db.get(Submission, failed_id)
        assert requeued is not None
        assert failed is not None
        requeued.verdict = SubmissionVerdict.running
        requeued.judger_id = "dead-worker"
        requeued.claim_token = "expired-requeue"
        requeued.claimed_at = expired_at - timedelta(minutes=1)
        requeued.claim_expires_at = expired_at
        requeued.attempt_number = 2
        db.add(
            TestResult(
                submission_id=requeued_id,
                task_test_id=first_test_id(demo_task["id"]),
                verdict=SubmissionVerdict.accepted,
                time_ms=1,
                output="",
                error="",
            )
        )
        failed.verdict = SubmissionVerdict.running
        failed.judger_id = "dead-worker"
        failed.claim_token = "expired-fail"
        failed.claimed_at = expired_at - timedelta(minutes=1)
        failed.claim_expires_at = expired_at
        failed.attempt_number = 3
        db.commit()

    assert worker.reclaim_expired_submissions() == 2

    with SessionLocal() as db:
        requeued = db.get(Submission, requeued_id)
        failed = db.get(Submission, failed_id)
        assert requeued is not None
        assert failed is not None
        assert requeued.verdict == SubmissionVerdict.queued
        assert requeued.claim_token is None
        assert requeued.claim_expires_at is None
        assert requeued.attempt_number == 2
        assert db.scalars(select(TestResult).where(TestResult.submission_id == requeued_id)).all() == []
        assert failed.verdict == SubmissionVerdict.internal_error
        assert failed.finished_at is not None
        assert failed.claim_token is None


def test_stale_claim_cannot_overwrite_newer_claim_result(
    client: APIClient,
    participant_headers: dict[str, str],
    demo_contest: dict,
    demo_task: dict,
) -> None:
    submission_id = create_submission(client, participant_headers, demo_contest, demo_task)
    with SessionLocal() as db:
        submission = db.get(Submission, submission_id)
        assert submission is not None
        submission.verdict = SubmissionVerdict.running
        submission.claim_token = "new-token"
        submission.claim_expires_at = datetime.utcnow() + timedelta(minutes=1)
        submission.attempt_number = 2
        db.commit()

    assert worker.finish_submission(submission_id, worker.VERDICT_ACCEPTED, 100, claim_token="new-token") is True
    assert worker.finish_submission(submission_id, worker.VERDICT_WRONG_ANSWER, 0, claim_token="old-token") is False
    assert worker.insert_result(
        submission_id,
        first_test_id(demo_task["id"]),
        worker.VERDICT_WRONG_ANSWER,
        1,
        "bad",
        "",
        claim_token="old-token",
    ) is False

    with SessionLocal() as db:
        submission = db.get(Submission, submission_id)
        assert submission is not None
        assert submission.verdict == SubmissionVerdict.accepted
        assert submission.score == 100
        assert db.scalars(select(TestResult).where(TestResult.submission_id == submission_id)).all() == []
