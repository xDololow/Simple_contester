import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import select

from app.database import SessionLocal
from app.models import ContestRegistration, ContestRegistrationStatus, ParticipantContest, Submission, SubmissionVerdict, TaskTest, TaskVersion, TestResult
from conftest import APIClient


JUDGER_PATH = Path(__file__).resolve().parents[1] / "judger"
if str(JUDGER_PATH) not in sys.path:
    sys.path.insert(0, str(JUDGER_PATH))

import worker  # noqa: E402


def create_running_contest(client: APIClient, admin_headers: dict[str, str], title: str, is_public: bool = False) -> dict[str, Any]:
    now = datetime.utcnow()
    response = client.post(
        "/api/contests",
        headers=admin_headers,
        json={
            "title": title,
            "description": "",
            "status": "running",
            "is_public": is_public,
            "time_mode": "fixed",
            "starts_at": (now - timedelta(minutes=5)).isoformat(),
            "ends_at": (now + timedelta(hours=1)).isoformat(),
            "individual_duration_minutes": None,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def create_running_individual_time_contest(
    client: APIClient,
    admin_headers: dict[str, str],
    title: str,
    duration_minutes: int = 60,
) -> dict[str, Any]:
    now = datetime.utcnow()
    response = client.post(
        "/api/contests",
        headers=admin_headers,
        json={
            "title": title,
            "description": "",
            "status": "running",
            "is_public": False,
            "time_mode": "individual",
            "starts_at": (now - timedelta(minutes=5)).isoformat(),
            "ends_at": (now + timedelta(hours=2)).isoformat(),
            "individual_duration_minutes": duration_minutes,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def create_running_team_contest(client: APIClient, admin_headers: dict[str, str], title: str, is_public: bool = False) -> dict[str, Any]:
    contest = create_running_contest(client, admin_headers, title, is_public=is_public)
    updated = client.patch(
        f"/api/contests/{contest['id']}",
        headers=admin_headers,
        json={"participation_mode": "team"},
    )
    assert updated.status_code == 200, updated.text
    return updated.json()


def create_contest_task(client: APIClient, admin_headers: dict[str, str], contest_id: int, title: str = "Echo") -> dict[str, Any]:
    response = client.post(
        "/api/tasks",
        headers=admin_headers,
        json={
            "contest_id": contest_id,
            "title": title,
            "statement": "Echo input.",
            "input_format": "",
            "output_format": "",
            "samples": [],
            "time_limit_ms": 1000,
            "memory_limit_mb": 128,
            "points": 100,
            "tests": [{"input_data": "x\n", "output_data": "x\n", "is_sample": True}],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def create_team(client: APIClient, admin_headers: dict[str, str], name: str, user_ids: list[int]) -> dict[str, Any]:
    response = client.post("/api/teams", headers=admin_headers, json={"name": name, "user_ids": user_ids})
    assert response.status_code == 200, response.text
    return response.json()


def assign_teams(client: APIClient, admin_headers: dict[str, str], contest_id: int, team_ids: list[int]) -> list[dict[str, Any]]:
    response = client.put(f"/api/contests/{contest_id}/teams", headers=admin_headers, json={"team_ids": team_ids})
    assert response.status_code == 200, response.text
    return response.json()


def accept_submission_at(submission_id: int, score: float, created_at: datetime) -> None:
    with SessionLocal() as db:
        submission = db.get(Submission, submission_id)
        assert submission is not None
        submission.verdict = SubmissionVerdict.accepted
        submission.score = score
        submission.created_at = created_at
        submission.finished_at = created_at
        db.commit()


def test_participant_does_not_see_or_open_private_contest_without_access(
    client: APIClient,
    admin_headers: dict[str, str],
    create_user: Callable[..., dict[str, Any]],
    auth_headers: Callable[[str, str], dict[str, str]],
) -> None:
    allowed = create_user(username="allowed", password="allowed-pass")
    stranger = create_user(username="outsider", password="outsider-pass")
    allowed_headers = auth_headers(allowed["username"], "allowed-pass")
    stranger_headers = auth_headers(stranger["username"], "outsider-pass")
    contest = create_running_contest(client, admin_headers, "Private")

    assigned = client.put(
        f"/api/contests/{contest['id']}/participants",
        headers=admin_headers,
        json={"user_ids": [allowed["id"]]},
    )
    assert assigned.status_code == 200, assigned.text

    allowed_list = client.get("/api/contests", headers=allowed_headers)
    assert allowed_list.status_code == 200, allowed_list.text
    assert contest["id"] in [item["id"] for item in allowed_list.json()]

    stranger_list = client.get("/api/contests", headers=stranger_headers)
    assert stranger_list.status_code == 200, stranger_list.text
    assert contest["id"] not in [item["id"] for item in stranger_list.json()]

    stranger_open = client.get(f"/api/contests/{contest['id']}", headers=stranger_headers)
    assert stranger_open.status_code == 403
    assert stranger_open.json()["detail"] == "Contest is not available"


def test_participant_with_private_contest_access_can_submit(
    client: APIClient,
    admin_headers: dict[str, str],
    participant: dict,
    participant_headers: dict[str, str],
) -> None:
    contest = create_running_contest(client, admin_headers, "Assigned")
    task = create_contest_task(client, admin_headers, contest["id"])
    assigned = client.put(
        f"/api/contests/{contest['id']}/participants",
        headers=admin_headers,
        json={"user_ids": [participant["id"]]},
    )
    assert assigned.status_code == 200, assigned.text

    created = client.post(
        f"/api/contests/{contest['id']}/tasks/{task['id']}/submissions",
        headers=participant_headers,
        json={"language": "python", "source_code": "print(input())"},
    )

    assert created.status_code == 200, created.text
    assert created.json()["contest_id"] == contest["id"]


def test_admin_can_view_and_adjust_individual_participant_time(
    client: APIClient,
    admin_headers: dict[str, str],
    create_user: Callable[..., dict[str, Any]],
) -> None:
    participant = create_user(username="time_alice", password="time-pass")
    contest = create_running_individual_time_contest(client, admin_headers, "Individual Time", duration_minutes=60)
    assigned = client.put(
        f"/api/contests/{contest['id']}/participants",
        headers=admin_headers,
        json={"user_ids": [participant["id"]]},
    )
    assert assigned.status_code == 200, assigned.text

    listed = client.get(f"/api/admin/contests/{contest['id']}/participant-times", headers=admin_headers)
    assert listed.status_code == 200, listed.text
    assert listed.json()[0]["user_id"] == participant["id"]
    assert listed.json()[0]["started_at"] is None
    assert listed.json()[0]["duration_seconds"] == 3600

    duration_set = client.patch(
        f"/api/admin/contests/{contest['id']}/participant-times/{participant['id']}",
        headers=admin_headers,
        json={"duration_seconds": 1800},
    )
    assert duration_set.status_code == 200, duration_set.text
    payload = duration_set.json()
    assert payload["started_at"] is not None
    assert payload["deadline_at"] is not None
    assert payload["duration_seconds"] == 1800
    first_deadline = datetime.fromisoformat(payload["deadline_at"])

    extended = client.patch(
        f"/api/admin/contests/{contest['id']}/participant-times/{participant['id']}",
        headers=admin_headers,
        json={"delta_seconds": 600},
    )
    assert extended.status_code == 200, extended.text
    assert datetime.fromisoformat(extended.json()["deadline_at"]) == first_deadline + timedelta(seconds=600)

    reset = client.patch(
        f"/api/admin/contests/{contest['id']}/participant-times/{participant['id']}",
        headers=admin_headers,
        json={"reset": True},
    )
    assert reset.status_code == 200, reset.text
    assert reset.json()["started_at"] is None
    assert reset.json()["deadline_at"] is None


def test_participant_creates_clarification_for_available_contest(
    client: APIClient,
    admin_headers: dict[str, str],
    participant: dict,
    participant_headers: dict[str, str],
) -> None:
    contest = create_running_contest(client, admin_headers, "Clarify", is_public=True)
    task = create_contest_task(client, admin_headers, contest["id"])

    created = client.post(
        f"/api/contests/{contest['id']}/clarifications",
        headers=participant_headers,
        json={"task_id": task["id"], "question": "Is input sorted?"},
    )

    assert created.status_code == 200, created.text
    payload = created.json()
    assert payload["contest_id"] == contest["id"]
    assert payload["task_id"] == task["id"]
    assert payload["author_user_id"] == participant["id"]
    assert payload["question"] == "Is input sorted?"
    assert payload["status"] == "open"
    assert payload["visibility"] == "private"


def test_participant_cannot_create_clarification_for_unavailable_contest(
    client: APIClient,
    admin_headers: dict[str, str],
    participant_headers: dict[str, str],
) -> None:
    contest = create_running_contest(client, admin_headers, "Hidden Clarify")

    created = client.post(
        f"/api/contests/{contest['id']}/clarifications",
        headers=participant_headers,
        json={"question": "Can I ask?"},
    )

    assert created.status_code == 403
    assert created.json()["detail"] == "Contest is not available"


def test_participant_cannot_see_another_private_clarification(
    client: APIClient,
    admin_headers: dict[str, str],
    create_user: Callable[..., dict[str, Any]],
    auth_headers: Callable[[str, str], dict[str, str]],
) -> None:
    alice = create_user(username="clar_alice", password="clar-pass")
    bob = create_user(username="clar_bob", password="clar-pass")
    alice_headers = auth_headers(alice["username"], "clar-pass")
    bob_headers = auth_headers(bob["username"], "clar-pass")
    contest = create_running_contest(client, admin_headers, "Private Clarifications")
    assigned = client.put(
        f"/api/contests/{contest['id']}/participants",
        headers=admin_headers,
        json={"user_ids": [alice["id"], bob["id"]]},
    )
    assert assigned.status_code == 200, assigned.text

    created = client.post(
        f"/api/contests/{contest['id']}/clarifications",
        headers=alice_headers,
        json={"question": "Only mine?"},
    )
    assert created.status_code == 200, created.text

    alice_list = client.get(f"/api/contests/{contest['id']}/clarifications", headers=alice_headers)
    bob_list = client.get(f"/api/contests/{contest['id']}/clarifications", headers=bob_headers)

    assert [item["id"] for item in alice_list.json()] == [created.json()["id"]]
    assert bob_list.status_code == 200, bob_list.text
    assert bob_list.json() == []


def test_broadcast_clarification_visible_to_all_contest_participants(
    client: APIClient,
    admin_headers: dict[str, str],
    create_user: Callable[..., dict[str, Any]],
    auth_headers: Callable[[str, str], dict[str, str]],
) -> None:
    alice = create_user(username="broadcast_alice", password="clar-pass")
    bob = create_user(username="broadcast_bob", password="clar-pass")
    alice_headers = auth_headers(alice["username"], "clar-pass")
    bob_headers = auth_headers(bob["username"], "clar-pass")
    contest = create_running_contest(client, admin_headers, "Broadcast Clarifications")
    assigned = client.put(
        f"/api/contests/{contest['id']}/participants",
        headers=admin_headers,
        json={"user_ids": [alice["id"], bob["id"]]},
    )
    assert assigned.status_code == 200, assigned.text
    created = client.post(
        f"/api/contests/{contest['id']}/clarifications",
        headers=alice_headers,
        json={"question": "For everyone?"},
    )
    assert created.status_code == 200, created.text

    answered = client.patch(
        f"/api/admin/clarifications/{created.json()['id']}",
        headers=admin_headers,
        json={"answer": "Yes.", "visibility": "broadcast"},
    )
    assert answered.status_code == 200, answered.text
    assert answered.json()["status"] == "answered"
    assert answered.json()["visibility"] == "broadcast"

    bob_list = client.get(f"/api/contests/{contest['id']}/clarifications", headers=bob_headers)
    assert bob_list.status_code == 200, bob_list.text
    assert [item["id"] for item in bob_list.json()] == [created.json()["id"]]
    assert bob_list.json()[0]["answer"] == "Yes."


def test_admin_can_answer_and_close_clarification(
    client: APIClient,
    admin_headers: dict[str, str],
    participant_headers: dict[str, str],
    demo_contest: dict,
) -> None:
    created = client.post(
        f"/api/contests/{demo_contest['id']}/clarifications",
        headers=participant_headers,
        json={"question": "What happens on ties?"},
    )
    assert created.status_code == 200, created.text

    answered = client.patch(
        f"/api/admin/clarifications/{created.json()['id']}",
        headers=admin_headers,
        json={"answer": "Penalty decides ties."},
    )
    assert answered.status_code == 200, answered.text
    assert answered.json()["answer"] == "Penalty decides ties."
    assert answered.json()["status"] == "answered"
    assert answered.json()["answered_by_user_id"] is not None
    assert answered.json()["answered_at"] is not None

    closed = client.patch(
        f"/api/admin/clarifications/{created.json()['id']}",
        headers=admin_headers,
        json={"status": "closed"},
    )
    assert closed.status_code == 200, closed.text
    assert closed.json()["status"] == "closed"


def test_participant_without_private_contest_access_cannot_submit_or_scoreboard(
    client: APIClient,
    admin_headers: dict[str, str],
    participant_headers: dict[str, str],
) -> None:
    contest = create_running_contest(client, admin_headers, "Locked")
    task = create_contest_task(client, admin_headers, contest["id"])

    created = client.post(
        f"/api/contests/{contest['id']}/tasks/{task['id']}/submissions",
        headers=participant_headers,
        json={"language": "python", "source_code": "print(input())"},
    )
    assert created.status_code == 403
    assert created.json()["detail"] == "Contest is not available"

    scoreboard = client.get(f"/api/contests/{contest['id']}/scoreboard", headers=participant_headers)
    assert scoreboard.status_code == 403
    assert scoreboard.json()["detail"] == "Contest is not available"


def test_participant_can_request_registration_for_private_contest(
    client: APIClient,
    admin_headers: dict[str, str],
    participant: dict,
    participant_headers: dict[str, str],
) -> None:
    contest = create_running_contest(client, admin_headers, "Registration")
    enabled = client.patch(
        f"/api/contests/{contest['id']}",
        headers=admin_headers,
        json={"registration_enabled": True, "registration_requires_approval": True},
    )
    assert enabled.status_code == 200, enabled.text

    listed = client.get("/api/contests", headers=participant_headers)
    assert listed.status_code == 200, listed.text
    assert contest["id"] in [item["id"] for item in listed.json()]

    opened = client.get(f"/api/contests/{contest['id']}", headers=participant_headers)
    assert opened.status_code == 200, opened.text

    requested = client.post(f"/api/contests/{contest['id']}/registration", headers=participant_headers)
    assert requested.status_code == 200, requested.text
    assert requested.json()["contest_id"] == contest["id"]
    assert requested.json()["user_id"] == participant["id"]
    assert requested.json()["team_id"] is None
    assert requested.json()["status"] == "pending"

    scoreboard = client.get(f"/api/contests/{contest['id']}/scoreboard", headers=participant_headers)
    assert scoreboard.status_code == 403
    assert scoreboard.json()["detail"] == "Contest is not available"


def test_registration_auto_approve_grants_individual_access(
    client: APIClient,
    admin_headers: dict[str, str],
    participant: dict,
    participant_headers: dict[str, str],
) -> None:
    contest = create_running_individual_time_contest(client, admin_headers, "Auto Registration")
    task = create_contest_task(client, admin_headers, contest["id"])
    enabled = client.patch(
        f"/api/contests/{contest['id']}",
        headers=admin_headers,
        json={"registration_enabled": True, "registration_requires_approval": False},
    )
    assert enabled.status_code == 200, enabled.text

    requested = client.post(f"/api/contests/{contest['id']}/registration", headers=participant_headers)
    assert requested.status_code == 200, requested.text
    assert requested.json()["status"] == "approved"
    started = client.post(f"/api/contests/{contest['id']}/start", headers=participant_headers)
    assert started.status_code == 200, started.text

    created = client.post(
        f"/api/contests/{contest['id']}/tasks/{task['id']}/submissions",
        headers=participant_headers,
        json={"language": "python", "source_code": "print(input())"},
    )
    assert created.status_code == 200, created.text

    with SessionLocal() as db:
        participant_access = db.scalar(
            select(ParticipantContest).where(
                ParticipantContest.contest_id == contest["id"],
                ParticipantContest.user_id == participant["id"],
            )
        )
        assert participant_access is not None


def test_admin_approval_flow_grants_access(
    client: APIClient,
    admin_headers: dict[str, str],
    participant_headers: dict[str, str],
) -> None:
    contest = create_running_contest(client, admin_headers, "Approval Registration")
    task = create_contest_task(client, admin_headers, contest["id"])
    enabled = client.patch(
        f"/api/contests/{contest['id']}",
        headers=admin_headers,
        json={"registration_enabled": True, "registration_requires_approval": True},
    )
    assert enabled.status_code == 200, enabled.text
    requested = client.post(f"/api/contests/{contest['id']}/registration", headers=participant_headers)
    assert requested.status_code == 200, requested.text

    pending = client.get("/api/admin/contest-registrations?status=pending", headers=admin_headers)
    assert pending.status_code == 200, pending.text
    assert [item["id"] for item in pending.json()] == [requested.json()["id"]]

    approved = client.patch(
        f"/api/admin/contest-registrations/{requested.json()['id']}?decision=approved",
        headers=admin_headers,
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"
    assert approved.json()["decided_by_user_id"] is not None

    created = client.post(
        f"/api/contests/{contest['id']}/tasks/{task['id']}/submissions",
        headers=participant_headers,
        json={"language": "python", "source_code": "print(input())"},
    )
    assert created.status_code == 200, created.text


def test_admin_can_list_all_registration_statuses(
    client: APIClient,
    admin_headers: dict[str, str],
    create_user: Callable[..., dict[str, Any]],
    auth_headers: Callable[[str, str], dict[str, str]],
) -> None:
    pending_user = create_user(username="reg_pending", password="reg-pass")
    rejected_user = create_user(username="reg_rejected", password="reg-pass")
    pending_headers = auth_headers(pending_user["username"], "reg-pass")
    rejected_headers = auth_headers(rejected_user["username"], "reg-pass")
    contest = create_running_contest(client, admin_headers, "All Registration Statuses")
    enabled = client.patch(
        f"/api/contests/{contest['id']}",
        headers=admin_headers,
        json={"registration_enabled": True, "registration_requires_approval": True},
    )
    assert enabled.status_code == 200, enabled.text
    pending = client.post(f"/api/contests/{contest['id']}/registration", headers=pending_headers)
    rejected = client.post(f"/api/contests/{contest['id']}/registration", headers=rejected_headers)
    assert pending.status_code == 200, pending.text
    assert rejected.status_code == 200, rejected.text
    rejected_decision = client.patch(
        f"/api/admin/contest-registrations/{rejected.json()['id']}?decision=rejected",
        headers=admin_headers,
    )
    assert rejected_decision.status_code == 200, rejected_decision.text

    default_list = client.get("/api/admin/contest-registrations", headers=admin_headers)
    all_list = client.get("/api/admin/contest-registrations?status=all", headers=admin_headers)

    assert [item["id"] for item in default_list.json()] == [pending.json()["id"]]
    assert {item["id"] for item in all_list.json()} == {pending.json()["id"], rejected.json()["id"]}


def test_approved_registration_allows_task_detail_but_pending_does_not(
    client: APIClient,
    admin_headers: dict[str, str],
    participant_headers: dict[str, str],
) -> None:
    contest = create_running_contest(client, admin_headers, "Registration Task Detail")
    task = create_contest_task(client, admin_headers, contest["id"])
    enabled = client.patch(
        f"/api/contests/{contest['id']}",
        headers=admin_headers,
        json={"registration_enabled": True, "registration_requires_approval": True},
    )
    assert enabled.status_code == 200, enabled.text

    requested = client.post(f"/api/contests/{contest['id']}/registration", headers=participant_headers)
    assert requested.status_code == 200, requested.text
    pending_detail = client.get(f"/api/tasks/{task['id']}", headers=participant_headers)
    assert pending_detail.status_code == 403

    approved = client.patch(
        f"/api/admin/contest-registrations/{requested.json()['id']}?decision=approved",
        headers=admin_headers,
    )
    assert approved.status_code == 200, approved.text
    approved_detail = client.get(f"/api/tasks/{task['id']}", headers=participant_headers)
    assert approved_detail.status_code == 200, approved_detail.text
    assert approved_detail.json()["id"] == task["id"]


def test_rejected_registration_keeps_private_contest_denied(
    client: APIClient,
    admin_headers: dict[str, str],
    participant_headers: dict[str, str],
) -> None:
    contest = create_running_contest(client, admin_headers, "Rejected Registration")
    task = create_contest_task(client, admin_headers, contest["id"])
    enabled = client.patch(
        f"/api/contests/{contest['id']}",
        headers=admin_headers,
        json={"registration_enabled": True, "registration_requires_approval": True},
    )
    assert enabled.status_code == 200, enabled.text
    requested = client.post(f"/api/contests/{contest['id']}/registration", headers=participant_headers)
    assert requested.status_code == 200, requested.text

    rejected = client.patch(
        f"/api/admin/contest-registrations/{requested.json()['id']}?decision=rejected",
        headers=admin_headers,
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["status"] == "rejected"

    created = client.post(
        f"/api/contests/{contest['id']}/tasks/{task['id']}/submissions",
        headers=participant_headers,
        json={"language": "python", "source_code": "print(input())"},
    )
    assert created.status_code == 403
    assert created.json()["detail"] == "Contest is not available"

    status_response = client.get(f"/api/contests/{contest['id']}/registration", headers=participant_headers)
    assert status_response.status_code == 200, status_response.text
    assert status_response.json()["status"] == "rejected"


def test_team_registration_simple_case_grants_team_access(
    client: APIClient,
    admin_headers: dict[str, str],
    participant: dict,
    participant_headers: dict[str, str],
) -> None:
    contest = create_running_team_contest(client, admin_headers, "Team Registration")
    task = create_contest_task(client, admin_headers, contest["id"])
    team = create_team(client, admin_headers, "Registration Team", [participant["id"]])
    enabled = client.patch(
        f"/api/contests/{contest['id']}",
        headers=admin_headers,
        json={"registration_enabled": True, "registration_requires_approval": False},
    )
    assert enabled.status_code == 200, enabled.text

    requested = client.post(f"/api/contests/{contest['id']}/registration", headers=participant_headers)
    assert requested.status_code == 200, requested.text
    assert requested.json()["status"] == "approved"
    assert requested.json()["user_id"] is None
    assert requested.json()["team_id"] == team["id"]

    created = client.post(
        f"/api/contests/{contest['id']}/tasks/{task['id']}/submissions",
        headers=participant_headers,
        json={"language": "python", "source_code": "print(input())"},
    )
    assert created.status_code == 200, created.text
    assert created.json()["team_id"] == team["id"]

    with SessionLocal() as db:
        registration = db.scalar(select(ContestRegistration).where(ContestRegistration.contest_id == contest["id"]))
        assert registration is not None
        assert registration.status == ContestRegistrationStatus.approved


def test_team_registration_requires_exactly_one_team_membership(
    client: APIClient,
    admin_headers: dict[str, str],
    participant: dict,
    participant_headers: dict[str, str],
) -> None:
    contest = create_running_team_contest(client, admin_headers, "Ambiguous Team Registration")
    first = create_team(client, admin_headers, "First Registration Team", [participant["id"]])
    second = create_team(client, admin_headers, "Second Registration Team", [participant["id"]])
    assert first["id"] != second["id"]
    enabled = client.patch(
        f"/api/contests/{contest['id']}",
        headers=admin_headers,
        json={"registration_enabled": True, "registration_requires_approval": False},
    )
    assert enabled.status_code == 200, enabled.text

    requested = client.post(f"/api/contests/{contest['id']}/registration", headers=participant_headers)

    assert requested.status_code == 403
    assert requested.json()["detail"] == "Team contest registration requires exactly one team membership; multiple teams found"


def test_admin_can_manage_contest_participant_access(
    client: APIClient,
    admin_headers: dict[str, str],
    create_user: Callable[..., dict[str, Any]],
) -> None:
    alice = create_user(username="access_alice", password="alice-pass")
    bob = create_user(username="access_bob", password="bob-pass")
    admin_user = create_user(username="access_admin", password="admin-pass", role="admin")
    contest = create_running_contest(client, admin_headers, "Access")

    rejected = client.put(
        f"/api/contests/{contest['id']}/participants",
        headers=admin_headers,
        json={"user_ids": [admin_user["id"]]},
    )
    assert rejected.status_code == 400
    assert rejected.json()["detail"] == f"Non-participant user ids: [{admin_user['id']}]"

    updated = client.put(
        f"/api/contests/{contest['id']}/participants",
        headers=admin_headers,
        json={"user_ids": [alice["id"], bob["id"]]},
    )
    assert updated.status_code == 200, updated.text
    assert [user["id"] for user in updated.json()] == [alice["id"], bob["id"]]

    listed = client.get(f"/api/contests/{contest['id']}/participants", headers=admin_headers)
    assert listed.status_code == 200, listed.text
    assert [user["id"] for user in listed.json()] == [alice["id"], bob["id"]]


def test_individual_deadline_blocks_submission_without_sleeping(
    client: APIClient,
    admin_headers: dict[str, str],
    participant: dict,
    participant_headers: dict[str, str],
) -> None:
    contest = create_running_individual_time_contest(client, admin_headers, "Deadline")
    task = create_contest_task(client, admin_headers, contest["id"])
    access = client.put(
        f"/api/contests/{contest['id']}/participants",
        headers=admin_headers,
        json={"user_ids": [participant["id"]]},
    )
    assert access.status_code == 200, access.text
    start = client.post(f"/api/contests/{contest['id']}/start", headers=participant_headers)
    assert start.status_code == 200, start.text

    with SessionLocal() as db:
        participant_window = db.scalar(
            select(ParticipantContest).where(
                ParticipantContest.contest_id == contest["id"],
                ParticipantContest.user_id == participant["id"],
            )
        )
        assert participant_window is not None
        participant_window.deadline_at = datetime.utcnow() - timedelta(minutes=1)
        db.commit()

    response = client.post(
        f"/api/contests/{contest['id']}/tasks/{task['id']}/submissions",
        headers=participant_headers,
        json={"language": "python", "source_code": "print(sum(map(int, input().split())))"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Individual contest deadline has passed"


def test_contest_individual_duration_must_fit_available_window(client: APIClient, admin_headers: dict[str, str]) -> None:
    now = datetime.utcnow()
    create_response = client.post(
        "/api/contests",
        headers=admin_headers,
        json={
            "title": "Too Short",
            "description": "",
            "status": "scheduled",
            "time_mode": "individual",
            "starts_at": now.isoformat(),
            "ends_at": (now + timedelta(minutes=30)).isoformat(),
            "individual_duration_minutes": 31,
        },
    )

    assert create_response.status_code == 400
    assert create_response.json()["detail"] == "individual_duration_minutes must fit contest window"

    ok_response = client.post(
        "/api/contests",
        headers=admin_headers,
        json={
            "title": "Window",
            "description": "",
            "status": "scheduled",
            "time_mode": "individual",
            "starts_at": now.isoformat(),
            "ends_at": (now + timedelta(minutes=30)).isoformat(),
            "individual_duration_minutes": 30,
        },
    )
    assert ok_response.status_code == 200, ok_response.text

    update_response = client.patch(
        f"/api/contests/{ok_response.json()['id']}",
        headers=admin_headers,
        json={"individual_duration_minutes": 31},
    )

    assert update_response.status_code == 400
    assert update_response.json()["detail"] == "individual_duration_minutes must fit contest window"


def test_participant_task_detail_hides_test_inputs_and_outputs(
    client: APIClient,
    participant_headers: dict[str, str],
    admin_headers: dict[str, str],
    demo_task: dict,
) -> None:
    participant_response = client.get(f"/api/tasks/{demo_task['id']}", headers=participant_headers)
    assert participant_response.status_code == 200, participant_response.text
    participant_task = participant_response.json()

    assert participant_task["test_count"] == 2
    assert participant_task["tests"] is None
    assert "input_data" not in participant_task
    assert "output_data" not in participant_task

    participant_tests = client.get(f"/api/tasks/{demo_task['id']}/tests", headers=participant_headers)
    assert participant_tests.status_code == 403

    admin_response = client.get(f"/api/tasks/{demo_task['id']}", headers=admin_headers)
    assert admin_response.status_code == 200, admin_response.text
    assert admin_response.json()["tests"] == [
        {"id": admin_response.json()["tests"][0]["id"], "is_sample": True},
        {"id": admin_response.json()["tests"][1]["id"], "is_sample": False},
    ]


def test_admin_can_create_and_edit_test_scoring_metadata(
    client: APIClient,
    admin_headers: dict[str, str],
    demo_task: dict,
) -> None:
    created = client.post(
        f"/api/tasks/{demo_task['id']}/tests",
        headers=admin_headers,
        json={
            "input_data": "5 7\n",
            "output_data": "12\n",
            "is_sample": False,
            "points": 25.5,
            "group_name": "easy",
        },
    )
    assert created.status_code == 200, created.text
    assert created.json()["points"] == 25.5
    assert created.json()["group_name"] == "easy"

    updated = client.patch(
        f"/api/tests/{created.json()['id']}",
        headers=admin_headers,
        json={"points": None, "group_name": "  main  "},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["points"] is None
    assert updated.json()["group_name"] == "main"

    tests = client.get(f"/api/tasks/{demo_task['id']}/tests", headers=admin_headers)
    assert tests.status_code == 200, tests.text
    stored = next(test for test in tests.json() if test["id"] == created.json()["id"])
    assert stored["points"] is None
    assert stored["group_name"] == "main"


def test_task_versions_created_on_task_create_update_and_test_changes(
    client: APIClient,
    admin_headers: dict[str, str],
    demo_task: dict,
) -> None:
    assert demo_task["current_version_number"] == 1

    versions = client.get(f"/api/tasks/{demo_task['id']}/versions", headers=admin_headers)
    assert versions.status_code == 200, versions.text
    assert [version["version_number"] for version in versions.json()] == [1]
    assert len(versions.json()[0]["tests_snapshot"]) == 2

    no_op = client.patch(f"/api/tasks/{demo_task['id']}", headers=admin_headers, json={"title": demo_task["title"]})
    assert no_op.status_code == 200, no_op.text
    assert no_op.json()["current_version_number"] == 1

    updated = client.patch(f"/api/tasks/{demo_task['id']}", headers=admin_headers, json={"points": 75})
    assert updated.status_code == 200, updated.text
    assert updated.json()["current_version_number"] == 2

    created_test = client.post(
        f"/api/tasks/{demo_task['id']}/tests",
        headers=admin_headers,
        json={"input_data": "1 1\n", "output_data": "2\n", "is_sample": False},
    )
    assert created_test.status_code == 200, created_test.text

    versions = client.get(f"/api/tasks/{demo_task['id']}/versions", headers=admin_headers)
    assert [version["version_number"] for version in versions.json()] == [3, 2, 1]
    assert len(versions.json()[0]["tests_snapshot"]) == 3


def test_submission_stores_current_task_version(
    client: APIClient,
    participant_headers: dict[str, str],
    demo_contest: dict,
    demo_task: dict,
) -> None:
    created = client.post(
        f"/api/contests/{demo_contest['id']}/tasks/{demo_task['id']}/submissions",
        headers=participant_headers,
        json={"language": "python", "source_code": "print(sum(map(int, input().split())))"},
    )

    assert created.status_code == 200, created.text
    assert created.json()["task_version_id"] is not None

    with SessionLocal() as db:
        version = db.get(TaskVersion, created.json()["task_version_id"])
        assert version is not None
        assert version.task_id == demo_task["id"]
        assert version.version_number == 1


def test_worker_uses_submission_task_version_snapshot_after_tests_change(
    client: APIClient,
    admin_headers: dict[str, str],
    participant_headers: dict[str, str],
    demo_contest: dict,
    demo_task: dict,
    monkeypatch,
) -> None:
    created = client.post(
        f"/api/contests/{demo_contest['id']}/tasks/{demo_task['id']}/submissions",
        headers=participant_headers,
        json={"language": "python", "source_code": "print(sum(map(int, input().split())))"},
    )
    assert created.status_code == 200, created.text
    submission_id = created.json()["id"]

    tests = client.get(f"/api/tasks/{demo_task['id']}/tests", headers=admin_headers).json()
    changed = client.patch(
        f"/api/tests/{tests[1]['id']}",
        headers=admin_headers,
        json={"output_data": "wrong-now\n"},
    )
    assert changed.status_code == 200, changed.text

    monkeypatch.setattr(worker, "JUDGER_ID", "snapshot-worker")
    worker.engine.dispose()
    claimed = worker.acquire_submission()
    assert claimed is not None
    assert claimed["id"] == submission_id
    assert claimed["task_version_id"] == created.json()["task_version_id"]
    snapshot_tests = worker.fetch_tests(claimed["task_id"], claimed["tests_snapshot"])
    assert [test["output_data"] for test in snapshot_tests] == ["5\n", "42\n"]
    assert worker.fetch_tests(claimed["task_id"])[1]["output_data"] == "wrong-now\n"


def test_worker_falls_back_to_live_task_for_old_submission_without_version(
    client: APIClient,
    participant_headers: dict[str, str],
    demo_contest: dict,
    demo_task: dict,
    monkeypatch,
) -> None:
    created = client.post(
        f"/api/contests/{demo_contest['id']}/tasks/{demo_task['id']}/submissions",
        headers=participant_headers,
        json={"language": "python", "source_code": "print(sum(map(int, input().split())))"},
    )
    assert created.status_code == 200, created.text
    with SessionLocal() as db:
        submission = db.get(Submission, created.json()["id"])
        assert submission is not None
        submission.task_version_id = None
        db.commit()

    monkeypatch.setattr(worker, "JUDGER_ID", "fallback-worker")
    worker.engine.dispose()
    claimed = worker.acquire_submission()
    assert claimed is not None
    assert claimed["task_version_id"] is None
    assert claimed["tests_snapshot"] is None
    assert [test["output_data"] for test in worker.fetch_tests(claimed["task_id"])] == ["5\n", "42\n"]


def test_participant_cannot_see_foreign_submission_or_hidden_results(
    client: APIClient,
    admin_headers: dict[str, str],
    create_user: Callable[..., dict[str, Any]],
    auth_headers: Callable[[str, str], dict[str, str]],
    demo_contest: dict,
    demo_task: dict,
) -> None:
    owner = create_user(username="owner", password="owner-pass")
    stranger = create_user(username="stranger", password="stranger-pass")
    owner_headers = auth_headers(owner["username"], "owner-pass")
    stranger_headers = auth_headers(stranger["username"], "stranger-pass")

    created = client.post(
        f"/api/contests/{demo_contest['id']}/tasks/{demo_task['id']}/submissions",
        headers=owner_headers,
        json={"language": "python", "source_code": "print(42)"},
    )
    assert created.status_code == 200, created.text
    submission_id = created.json()["id"]

    with SessionLocal() as db:
        stored_submission = db.get(Submission, submission_id)
        assert stored_submission is not None
        task_test_id = db.scalar(select(TaskTest.id).where(TaskTest.task_id == demo_task["id"]))
        assert task_test_id is not None
        db.add(
            TestResult(
                submission_id=submission_id,
                task_test_id=task_test_id,
                verdict=SubmissionVerdict.wrong_answer,
                output="hidden output",
                error="hidden error",
            )
        )
        db.commit()

    owner_detail = client.get(f"/api/submissions/{submission_id}", headers=owner_headers)
    assert owner_detail.status_code == 200
    assert "source_code" not in owner_detail.json()
    assert "results" not in owner_detail.json()
    assert "hidden output" not in owner_detail.text

    stranger_detail = client.get(f"/api/submissions/{submission_id}", headers=stranger_headers)
    assert stranger_detail.status_code == 403

    stranger_list = client.get(f"/api/submissions?contest_id={demo_contest['id']}", headers=stranger_headers)
    assert stranger_list.status_code == 200
    assert all(row["user_id"] == stranger["id"] for row in stranger_list.json())
    assert submission_id not in [row["id"] for row in stranger_list.json()]

    admin_detail = client.get(f"/api/admin/submissions/{submission_id}", headers=admin_headers)
    assert admin_detail.status_code == 200, admin_detail.text
    assert admin_detail.json()["source_code"] == "print(42)"
    assert admin_detail.json()["results"][0]["output"] == "hidden output"


def test_admin_can_rejudge_submission_against_current_task_version(
    client: APIClient,
    admin_headers: dict[str, str],
    participant_headers: dict[str, str],
    demo_contest: dict,
    demo_task: dict,
) -> None:
    created = client.post(
        f"/api/contests/{demo_contest['id']}/tasks/{demo_task['id']}/submissions",
        headers=participant_headers,
        json={"language": "python", "source_code": "print(5)"},
    )
    assert created.status_code == 200, created.text
    submission_id = created.json()["id"]
    original_version_id = created.json()["task_version_id"]

    with SessionLocal() as db:
        stored_submission = db.get(Submission, submission_id)
        assert stored_submission is not None
        first_test = db.scalar(select(TaskTest).where(TaskTest.task_id == demo_task["id"]).order_by(TaskTest.id))
        assert first_test is not None
        stored_submission.verdict = SubmissionVerdict.accepted
        stored_submission.score = 100
        stored_submission.compile_output = "old compile output"
        stored_submission.started_at = datetime.utcnow()
        stored_submission.finished_at = datetime.utcnow()
        stored_submission.judger_id = "old-judger"
        stored_submission.claim_token = "old-token"
        stored_submission.attempt_number = 2
        db.add(
            TestResult(
                submission_id=submission_id,
                task_test_id=first_test.id,
                verdict=SubmissionVerdict.accepted,
                time_ms=12,
                output="old output",
                error="",
            )
        )
        db.commit()

    tests = client.get(f"/api/tasks/{demo_task['id']}/tests", headers=admin_headers)
    assert tests.status_code == 200, tests.text

    updated_test = client.patch(
        f"/api/tests/{tests.json()[0]['id']}",
        headers=admin_headers,
        json={"output_data": "changed\n"},
    )
    assert updated_test.status_code == 200, updated_test.text

    with SessionLocal() as db:
        latest_version_id = db.scalar(
            select(TaskVersion.id)
            .where(TaskVersion.task_id == demo_task["id"])
            .order_by(TaskVersion.version_number.desc())
            .limit(1)
        )
    assert latest_version_id is not None
    assert latest_version_id != original_version_id

    denied = client.post(f"/api/admin/submissions/{submission_id}/rejudge", headers=participant_headers)
    assert denied.status_code == 403

    rejudged = client.post(f"/api/admin/submissions/{submission_id}/rejudge", headers=admin_headers)
    assert rejudged.status_code == 200, rejudged.text
    payload = rejudged.json()
    assert payload["verdict"] == "Queued"
    assert payload["score"] == 0
    assert payload["compile_output"] == ""
    assert payload["started_at"] is None
    assert payload["finished_at"] is None
    assert payload["attempt_number"] == 0
    assert payload["task_version_id"] == latest_version_id
    assert payload["results"] == []

    with SessionLocal() as db:
        stored_submission = db.get(Submission, submission_id)
        assert stored_submission is not None
        assert stored_submission.judger_id is None
        assert stored_submission.claim_token is None
        assert db.scalar(select(TestResult).where(TestResult.submission_id == submission_id)) is None


def test_admin_can_assign_teams_to_contest(
    client: APIClient,
    admin_headers: dict[str, str],
    participant: dict,
    demo_contest: dict,
) -> None:
    team = client.post(
        "/api/teams",
        headers=admin_headers,
        json={"name": "Team One", "user_ids": [participant["id"]]},
    )
    assert team.status_code == 200, team.text

    assigned = client.put(
        f"/api/contests/{demo_contest['id']}/teams",
        headers=admin_headers,
        json={"team_ids": [team.json()["id"]]},
    )
    assert assigned.status_code == 200, assigned.text
    assert assigned.json()[0]["id"] == team.json()["id"]
    assert assigned.json()[0]["name"] == "Team One"
    assert assigned.json()[0]["member_ids"] == [participant["id"]]

    listed = client.get(f"/api/contests/{demo_contest['id']}/teams", headers=admin_headers)
    assert listed.status_code == 200, listed.text
    assert listed.json()[0]["id"] == team.json()["id"]
    assert listed.json()[0]["name"] == "Team One"
    assert listed.json()[0]["member_ids"] == [participant["id"]]

    rejected = client.put(
        f"/api/contests/{demo_contest['id']}/teams",
        headers=admin_headers,
        json={"team_ids": [9999]},
    )
    assert rejected.status_code == 400
    assert rejected.json()["detail"] == "Unknown team ids: [9999]"


def test_team_contest_access_by_membership(
    client: APIClient,
    admin_headers: dict[str, str],
    create_user: Callable[..., dict[str, Any]],
    auth_headers: Callable[[str, str], dict[str, str]],
) -> None:
    member = create_user(username="team_member", password="member-pass")
    outsider = create_user(username="team_outsider", password="outsider-pass")
    member_headers = auth_headers(member["username"], "member-pass")
    outsider_headers = auth_headers(outsider["username"], "outsider-pass")
    contest = create_running_team_contest(client, admin_headers, "Private Team Contest")
    team = create_team(client, admin_headers, "Blue Team", [member["id"]])
    assign_teams(client, admin_headers, contest["id"], [team["id"]])

    member_list = client.get("/api/contests", headers=member_headers)
    assert member_list.status_code == 200, member_list.text
    assert contest["id"] in [item["id"] for item in member_list.json()]

    member_open = client.get(f"/api/contests/{contest['id']}", headers=member_headers)
    assert member_open.status_code == 200, member_open.text

    outsider_open = client.get(f"/api/contests/{contest['id']}", headers=outsider_headers)
    assert outsider_open.status_code == 403
    assert outsider_open.json()["detail"] == "Contest is not available"


def test_team_contest_submit_records_team_id(
    client: APIClient,
    admin_headers: dict[str, str],
    participant: dict,
    participant_headers: dict[str, str],
) -> None:
    contest = create_running_team_contest(client, admin_headers, "Submit As Team")
    task = create_contest_task(client, admin_headers, contest["id"])
    team = create_team(client, admin_headers, "Solo Team", [participant["id"]])
    assign_teams(client, admin_headers, contest["id"], [team["id"]])

    created = client.post(
        f"/api/contests/{contest['id']}/tasks/{task['id']}/submissions",
        headers=participant_headers,
        json={"language": "python", "source_code": "print(input())"},
    )

    assert created.status_code == 200, created.text
    assert created.json()["user_id"] == participant["id"]
    assert created.json()["team_id"] == team["id"]

    with SessionLocal() as db:
        stored = db.get(Submission, created.json()["id"])
        assert stored is not None
        assert stored.team_id == team["id"]


def test_team_scoreboard_aggregates_best_accepted_per_problem(
    client: APIClient,
    admin_headers: dict[str, str],
    create_user: Callable[..., dict[str, Any]],
    auth_headers: Callable[[str, str], dict[str, str]],
) -> None:
    alice = create_user(username="score_alice", password="score-pass")
    bob = create_user(username="score_bob", password="score-pass")
    alice_headers = auth_headers(alice["username"], "score-pass")
    bob_headers = auth_headers(bob["username"], "score-pass")
    contest = create_running_team_contest(client, admin_headers, "Team Scoreboard")
    task_a = create_contest_task(client, admin_headers, contest["id"], "A")
    task_b = create_contest_task(client, admin_headers, contest["id"], "B")
    team = create_team(client, admin_headers, "Aggregators", [alice["id"], bob["id"]])
    assign_teams(client, admin_headers, contest["id"], [team["id"]])

    wrong = client.post(
        f"/api/contests/{contest['id']}/tasks/{task_a['id']}/submissions",
        headers=alice_headers,
        json={"language": "python", "source_code": "print('wrong')"},
    )
    accepted_a = client.post(
        f"/api/contests/{contest['id']}/tasks/{task_a['id']}/submissions",
        headers=bob_headers,
        json={"language": "python", "source_code": "print(input())"},
    )
    accepted_b = client.post(
        f"/api/contests/{contest['id']}/tasks/{task_b['id']}/submissions",
        headers=alice_headers,
        json={"language": "python", "source_code": "print(input())"},
    )
    assert wrong.status_code == 200, wrong.text
    assert accepted_a.status_code == 200, accepted_a.text
    assert accepted_b.status_code == 200, accepted_b.text

    with SessionLocal() as db:
        wrong_submission = db.get(Submission, wrong.json()["id"])
        accepted_a_submission = db.get(Submission, accepted_a.json()["id"])
        accepted_b_submission = db.get(Submission, accepted_b.json()["id"])
        assert wrong_submission is not None
        assert accepted_a_submission is not None
        assert accepted_b_submission is not None
        wrong_submission.verdict = SubmissionVerdict.wrong_answer
        wrong_submission.score = 10
        accepted_a_submission.verdict = SubmissionVerdict.accepted
        accepted_a_submission.score = task_a["points"]
        accepted_a_submission.finished_at = datetime.utcnow()
        accepted_b_submission.verdict = SubmissionVerdict.accepted
        accepted_b_submission.score = task_b["points"]
        accepted_b_submission.finished_at = datetime.utcnow()
        db.commit()

    scoreboard = client.get(f"/api/contests/{contest['id']}/scoreboard", headers=alice_headers)
    assert scoreboard.status_code == 200, scoreboard.text
    rows = scoreboard.json()
    assert len(rows) == 1
    row = rows[0]
    assert row["team_id"] == team["id"]
    assert row["team_name"] == "Aggregators"
    assert row["score"] == task_a["points"] + task_b["points"]
    assert row["cells"][0]["attempts"] == 2
    assert row["cells"][0]["solved"] is True
    assert row["cells"][1]["attempts"] == 1
    assert row["cells"][1]["solved"] is True


def test_team_contest_submit_without_assigned_team_denied(
    client: APIClient,
    admin_headers: dict[str, str],
    participant_headers: dict[str, str],
) -> None:
    contest = create_running_team_contest(client, admin_headers, "No Team", is_public=True)
    task = create_contest_task(client, admin_headers, contest["id"])

    created = client.post(
        f"/api/contests/{contest['id']}/tasks/{task['id']}/submissions",
        headers=participant_headers,
        json={"language": "python", "source_code": "print(input())"},
    )

    assert created.status_code == 403
    assert created.json()["detail"] == "Team contest requires exactly one approved team membership"


def test_individual_mode_submissions_remain_user_owned(
    client: APIClient,
    admin_headers: dict[str, str],
    participant: dict,
    participant_headers: dict[str, str],
) -> None:
    contest = create_running_contest(client, admin_headers, "Individual Still Works", is_public=True)
    task = create_contest_task(client, admin_headers, contest["id"])
    create_team(client, admin_headers, "Irrelevant Team", [participant["id"]])

    created = client.post(
        f"/api/contests/{contest['id']}/tasks/{task['id']}/submissions",
        headers=participant_headers,
        json={"language": "python", "source_code": "print(input())"},
    )

    assert created.status_code == 200, created.text
    assert created.json()["team_id"] is None
    scoreboard = client.get(f"/api/contests/{contest['id']}/scoreboard", headers=participant_headers)
    assert scoreboard.status_code == 200, scoreboard.text
    row = next(item for item in scoreboard.json() if item["user_id"] == participant["id"])
    assert row["team_id"] is None
    assert row["display_name"] == participant["display_name"]


def test_submission_lifecycle_and_scoreboard_after_accepted_submission(
    client: APIClient,
    participant: dict,
    participant_headers: dict[str, str],
    demo_contest: dict,
    demo_task: dict,
) -> None:
    created = client.post(
        f"/api/contests/{demo_contest['id']}/tasks/{demo_task['id']}/submissions",
        headers=participant_headers,
        json={"language": "python", "source_code": "print(sum(map(int, input().split())))"},
    )
    assert created.status_code == 200, created.text
    submission = created.json()
    assert submission["verdict"] == "Queued"

    listed = client.get("/api/submissions", headers=participant_headers)
    assert listed.status_code == 200
    assert [row["id"] for row in listed.json()] == [submission["id"]]

    with SessionLocal() as db:
        stored_submission = db.get(Submission, submission["id"])
        assert stored_submission is not None
        stored_submission.verdict = SubmissionVerdict.accepted
        stored_submission.score = demo_task["points"]
        stored_submission.finished_at = datetime.utcnow()
        db.commit()

    scoreboard = client.get(f"/api/contests/{demo_contest['id']}/scoreboard", headers=participant_headers)
    assert scoreboard.status_code == 200, scoreboard.text
    row = next(item for item in scoreboard.json() if item["user_id"] == participant["id"])

    assert row["username"] == participant["username"]
    assert row["score"] == demo_task["points"]
    assert row["penalty"] >= 0
    assert row["cells"] == [
        {
            "task_id": demo_task["id"],
            "attempts": 1,
            "solved": True,
            "solved_at_minutes": row["cells"][0]["solved_at_minutes"],
        }
    ]


def test_scoreboard_freeze_hides_post_freeze_results_until_unfrozen(
    client: APIClient,
    admin_headers: dict[str, str],
    participant: dict,
    participant_headers: dict[str, str],
) -> None:
    contest = create_running_contest(client, admin_headers, "Frozen", is_public=True)
    task_a = create_contest_task(client, admin_headers, contest["id"], "A")
    task_b = create_contest_task(client, admin_headers, contest["id"], "B")
    freeze_at = datetime.utcnow() - timedelta(minutes=1)
    frozen = client.patch(
        f"/api/contests/{contest['id']}",
        headers=admin_headers,
        json={"scoreboard_freeze_at": freeze_at.isoformat(), "scoreboard_unfrozen": False},
    )
    assert frozen.status_code == 200, frozen.text

    before = client.post(
        f"/api/contests/{contest['id']}/tasks/{task_a['id']}/submissions",
        headers=participant_headers,
        json={"language": "python", "source_code": "print(input())"},
    )
    after = client.post(
        f"/api/contests/{contest['id']}/tasks/{task_b['id']}/submissions",
        headers=participant_headers,
        json={"language": "python", "source_code": "print(input())"},
    )
    assert before.status_code == 200, before.text
    assert after.status_code == 200, after.text
    accept_submission_at(before.json()["id"], task_a["points"], freeze_at - timedelta(seconds=1))
    accept_submission_at(after.json()["id"], task_b["points"], freeze_at + timedelta(seconds=1))

    participant_scoreboard = client.get(f"/api/contests/{contest['id']}/scoreboard", headers=participant_headers)
    assert participant_scoreboard.status_code == 200, participant_scoreboard.text
    participant_row = next(item for item in participant_scoreboard.json() if item["user_id"] == participant["id"])
    assert participant_row["score"] == task_a["points"]
    assert participant_row["cells"][0]["solved"] is True
    assert participant_row["cells"][1]["solved"] is False

    snapshot = client.get(f"/api/contests/{contest['id']}/live-snapshot", headers=participant_headers)
    assert snapshot.status_code == 200, snapshot.text
    assert snapshot.json()["scoreboard_frozen"] is True
    snapshot_row = next(item for item in snapshot.json()["scoreboard"] if item["user_id"] == participant["id"])
    assert snapshot_row["score"] == task_a["points"]

    admin_scoreboard = client.get(f"/api/contests/{contest['id']}/scoreboard", headers=admin_headers)
    assert admin_scoreboard.status_code == 200, admin_scoreboard.text
    admin_row = next(item for item in admin_scoreboard.json() if item["user_id"] == participant["id"])
    assert admin_row["score"] == task_a["points"] + task_b["points"]
    assert admin_row["cells"][1]["solved"] is True

    unfrozen = client.patch(
        f"/api/contests/{contest['id']}",
        headers=admin_headers,
        json={"scoreboard_unfrozen": True},
    )
    assert unfrozen.status_code == 200, unfrozen.text
    revealed = client.get(f"/api/contests/{contest['id']}/scoreboard", headers=participant_headers)
    assert revealed.status_code == 200, revealed.text
    revealed_row = next(item for item in revealed.json() if item["user_id"] == participant["id"])
    assert revealed_row["score"] == task_a["points"] + task_b["points"]
    assert revealed_row["cells"][1]["solved"] is True


def test_team_scoreboard_freeze_hides_post_freeze_results_until_unfrozen(
    client: APIClient,
    admin_headers: dict[str, str],
    participant: dict,
    participant_headers: dict[str, str],
) -> None:
    contest = create_running_team_contest(client, admin_headers, "Frozen Team")
    task_a = create_contest_task(client, admin_headers, contest["id"], "A")
    task_b = create_contest_task(client, admin_headers, contest["id"], "B")
    team = create_team(client, admin_headers, "Frozen Team One", [participant["id"]])
    assign_teams(client, admin_headers, contest["id"], [team["id"]])
    freeze_at = datetime.utcnow() - timedelta(minutes=1)
    frozen = client.patch(
        f"/api/contests/{contest['id']}",
        headers=admin_headers,
        json={"scoreboard_freeze_at": freeze_at.isoformat(), "scoreboard_unfrozen": False},
    )
    assert frozen.status_code == 200, frozen.text

    before = client.post(
        f"/api/contests/{contest['id']}/tasks/{task_a['id']}/submissions",
        headers=participant_headers,
        json={"language": "python", "source_code": "print(input())"},
    )
    after = client.post(
        f"/api/contests/{contest['id']}/tasks/{task_b['id']}/submissions",
        headers=participant_headers,
        json={"language": "python", "source_code": "print(input())"},
    )
    assert before.status_code == 200, before.text
    assert after.status_code == 200, after.text
    accept_submission_at(before.json()["id"], task_a["points"], freeze_at - timedelta(seconds=1))
    accept_submission_at(after.json()["id"], task_b["points"], freeze_at + timedelta(seconds=1))

    participant_scoreboard = client.get(f"/api/contests/{contest['id']}/scoreboard", headers=participant_headers)
    assert participant_scoreboard.status_code == 200, participant_scoreboard.text
    row = participant_scoreboard.json()[0]
    assert row["team_id"] == team["id"]
    assert row["score"] == task_a["points"]
    assert row["cells"][1]["solved"] is False

    admin_scoreboard = client.get(f"/api/contests/{contest['id']}/scoreboard", headers=admin_headers)
    assert admin_scoreboard.status_code == 200, admin_scoreboard.text
    admin_row = admin_scoreboard.json()[0]
    assert admin_row["score"] == task_a["points"] + task_b["points"]
    assert admin_row["cells"][1]["solved"] is True

    unfrozen = client.patch(
        f"/api/contests/{contest['id']}",
        headers=admin_headers,
        json={"scoreboard_unfrozen": True},
    )
    assert unfrozen.status_code == 200, unfrozen.text
    revealed = client.get(f"/api/contests/{contest['id']}/scoreboard", headers=participant_headers)
    assert revealed.status_code == 200, revealed.text
    assert revealed.json()[0]["score"] == task_a["points"] + task_b["points"]


def test_contest_events_requires_token(
    client: APIClient,
    demo_contest: dict,
) -> None:
    missing = client.get(f"/api/contests/{demo_contest['id']}/events")
    assert missing.status_code == 401

    invalid = client.get(f"/api/contests/{demo_contest['id']}/events?token=not-a-token")
    assert invalid.status_code == 401


def test_live_snapshot_matches_submission_and_scoreboard_payloads(
    client: APIClient,
    participant: dict,
    participant_headers: dict[str, str],
    demo_contest: dict,
    demo_task: dict,
) -> None:
    created = client.post(
        f"/api/contests/{demo_contest['id']}/tasks/{demo_task['id']}/submissions",
        headers=participant_headers,
        json={"language": "python", "source_code": "print(42)"},
    )
    assert created.status_code == 200, created.text

    snapshot = client.get(f"/api/contests/{demo_contest['id']}/live-snapshot", headers=participant_headers)
    assert snapshot.status_code == 200, snapshot.text
    payload = snapshot.json()

    assert payload["submissions"][0]["id"] == created.json()["id"]
    assert payload["submissions"][0]["verdict"] == "Queued"
    row = next(item for item in payload["scoreboard"] if item["user_id"] == participant["id"])
    assert row["score"] == 0
    assert row["cells"][0]["attempts"] == 1


def test_scoreboard_uses_best_partial_submission_score(
    client: APIClient,
    participant: dict,
    participant_headers: dict[str, str],
    demo_contest: dict,
    demo_task: dict,
) -> None:
    first = client.post(
        f"/api/contests/{demo_contest['id']}/tasks/{demo_task['id']}/submissions",
        headers=participant_headers,
        json={"language": "python", "source_code": "print(1)"},
    )
    second = client.post(
        f"/api/contests/{demo_contest['id']}/tasks/{demo_task['id']}/submissions",
        headers=participant_headers,
        json={"language": "python", "source_code": "print(2)"},
    )
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text

    with SessionLocal() as db:
        first_submission = db.get(Submission, first.json()["id"])
        second_submission = db.get(Submission, second.json()["id"])
        assert first_submission is not None
        assert second_submission is not None
        first_submission.verdict = SubmissionVerdict.wrong_answer
        first_submission.score = 25.0
        first_submission.finished_at = datetime.utcnow()
        second_submission.verdict = SubmissionVerdict.wrong_answer
        second_submission.score = 50.0
        second_submission.finished_at = datetime.utcnow()
        db.commit()

    scoreboard = client.get(f"/api/contests/{demo_contest['id']}/scoreboard", headers=participant_headers)
    assert scoreboard.status_code == 200, scoreboard.text
    row = next(item for item in scoreboard.json() if item["user_id"] == participant["id"])

    assert row["score"] == 50.0
    assert row["cells"][0]["attempts"] == 2
    assert row["cells"][0]["solved"] is False
