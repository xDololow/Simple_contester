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
        tables = set(inspect(engine).get_table_names())
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
    }.issubset(tables)
