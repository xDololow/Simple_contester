import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import select

from app.database import SessionLocal
from app.models import Judger
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
