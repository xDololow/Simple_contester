from __future__ import annotations

import sys
import time
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import OperationalError

from .config import settings
from .database import Base
from . import models  # noqa: F401


REVISION_HEAD = "20260502_0001"
CORE_PRE_ALEMBIC_TABLES = {"users", "contests", "tasks", "submissions"}


def alembic_config() -> Config:
    root = next(path for path in Path(__file__).resolve().parents if (path / "alembic.ini").exists())
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    config.set_main_option("sqlalchemy.url", settings.database_url)
    return config


def wait_for_database(timeout_seconds: int = 60) -> None:
    engine = create_engine(settings.database_url, pool_pre_ping=True)
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            engine.dispose()
            return
        except OperationalError as exc:
            last_error = exc
            time.sleep(2)
    engine.dispose()
    raise RuntimeError(f"Database did not become ready within {timeout_seconds} seconds") from last_error


def stamp_existing_schema(config: Config) -> None:
    engine = create_engine(settings.database_url, pool_pre_ping=True)
    try:
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        if "alembic_version" in tables or not tables:
            return
        if CORE_PRE_ALEMBIC_TABLES.issubset(tables):
            Base.metadata.create_all(bind=engine)
            command.stamp(config, REVISION_HEAD)
    finally:
        engine.dispose()


def upgrade() -> None:
    wait_for_database()
    config = alembic_config()
    stamp_existing_schema(config)
    command.upgrade(config, "head")


def main() -> None:
    command_name = sys.argv[1] if len(sys.argv) > 1 else "upgrade"
    if command_name != "upgrade":
        raise SystemExit(f"Unsupported migration command: {command_name}")
    upgrade()


if __name__ == "__main__":
    main()
