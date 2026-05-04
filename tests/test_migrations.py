from __future__ import annotations

from alembic import command
from sqlalchemy import create_engine, inspect

from app import migrate


def test_alembic_upgrade_creates_current_schema(tmp_path, monkeypatch) -> None:
    db_url = f"sqlite:///{tmp_path / 'migration_smoke.db'}"
    monkeypatch.setattr(migrate.settings, "database_url", db_url)

    command.upgrade(migrate.alembic_config(), "head")

    engine = create_engine(db_url)
    try:
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        contest_columns = {column["name"]: column for column in inspector.get_columns("contests")}
        participant_columns = {column["name"]: column for column in inspector.get_columns("participant_contests")}
        submission_columns = {column["name"]: column for column in inspector.get_columns("submissions")}
    finally:
        engine.dispose()

    assert {
        "alembic_version",
        "users",
        "teams",
        "team_members",
        "contests",
        "contest_teams",
        "participant_contests",
        "contest_tasks",
        "tasks",
        "task_tests",
        "submissions",
        "test_results",
        "judgers",
        "judger_events",
    }.issubset(tables)
    assert "is_public" in contest_columns
    assert participant_columns["started_at"]["nullable"] is True
    assert participant_columns["deadline_at"]["nullable"] is True
    assert "claimed_at" in submission_columns
    assert "claim_expires_at" in submission_columns
    assert "claim_token" in submission_columns
    assert "attempt_number" in submission_columns
