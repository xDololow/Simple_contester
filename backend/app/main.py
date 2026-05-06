import asyncio
import csv
import io
import json
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import PurePosixPath

import yaml
from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, Response, UploadFile, status
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from .auth import create_access_token, get_current_user, get_user_from_token, hash_password, require_admin, verify_password
from .config import settings
from .database import SessionLocal, engine, get_db
from .models import (
    Contest,
    Clarification,
    ClarificationStatus,
    ClarificationVisibility,
    ContestParticipationMode,
    ContestRegistration,
    ContestRegistrationStatus,
    ContestStatus,
    ContestTeam,
    ContestTask,
    ContestTimeMode,
    Judger,
    JudgerEvent,
    Language,
    ParticipantContest,
    Submission,
    SubmissionVerdict,
    Task,
    TaskTest,
    TaskVersion,
    Team,
    TeamMember,
    User,
    UserRole,
)
from .schemas import (
    AdminContestsStats,
    AdminJudgerEventOut,
    AdminJudgerOut,
    AdminJudgerStats,
    AdminStatsOut,
    AdminSubmissionsStats,
    AdminSystemStats,
    AdminUsersStats,
    ClarificationAdminUpdate,
    ClarificationCreate,
    ClarificationOut,
    ContestCreate,
    ContestParticipantsUpdate,
    ContestRegistrationDetailOut,
    ContestRegistrationOut,
    ContestOut,
    ContestTeamsUpdate,
    ContestTasksUpdate,
    ContestUpdate,
    ImportReport,
    LoginIn,
    ParticipantContestOut,
    PackageImportReport,
    ScoreboardCell,
    ScoreboardRow,
    SubmissionAdminDetailOut,
    SubmissionCreate,
    SubmissionOut,
    TaskCreate,
    TaskDetailOut,
    TaskOut,
    TaskTestCreate,
    TaskTestOut,
    TaskTestPublicOut,
    TaskTestUpdate,
    TaskUpdate,
    TaskVersionOut,
    TestArchiveImportReport,
    TestResultOut,
    TeamCreate,
    TeamOut,
    TeamUpdate,
    TokenOut,
    UserCreate,
    UserOut,
    UserUpdate,
)


PACKAGE_FORMAT_VERSION = 1
PACKAGE_MAX_FILES = 500
PACKAGE_MAX_TOTAL_BYTES = 20 * 1024 * 1024
PACKAGE_MAX_FILE_BYTES = 5 * 1024 * 1024
STALE_RUNNING_SECONDS = 10 * 60
JUDGER_ACTIVE_SECONDS = 15
JUDGER_OFFLINE_SECONDS = 60

app = FastAPI(title="Simple Contester")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def now_utc() -> datetime:
    return datetime.utcnow()


def normalize_dt(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def is_scoreboard_frozen_for_user(contest: Contest, user: User, current: datetime | None = None) -> bool:
    if user.role == UserRole.admin or contest.scoreboard_unfrozen or contest.scoreboard_freeze_at is None:
        return False
    return normalize_dt(current or now_utc()) >= normalize_dt(contest.scoreboard_freeze_at)


def validate_contest_time_window(
    starts_at: datetime,
    ends_at: datetime,
    time_mode: ContestTimeMode,
    individual_duration_minutes: int | None,
    scoreboard_freeze_at: datetime | None = None,
) -> None:
    if ends_at <= starts_at:
        raise HTTPException(status_code=400, detail="ends_at must be after starts_at")
    if scoreboard_freeze_at is not None:
        if scoreboard_freeze_at < starts_at:
            raise HTTPException(status_code=400, detail="scoreboard_freeze_at must be within contest window")
        if scoreboard_freeze_at >= ends_at:
            raise HTTPException(status_code=400, detail="scoreboard_freeze_at must be before ends_at")
    if time_mode == ContestTimeMode.individual:
        if individual_duration_minutes is None:
            raise HTTPException(status_code=400, detail="individual_duration_minutes is required")
        if individual_duration_minutes <= 0:
            raise HTTPException(status_code=400, detail="individual_duration_minutes must be positive")
        available_minutes = int((ends_at - starts_at).total_seconds() // 60)
        if individual_duration_minutes > available_minutes:
            raise HTTPException(status_code=400, detail="individual_duration_minutes must fit contest window")


def ensure_admin(db: Session) -> None:
    admin = db.scalar(select(User).where(User.username == settings.admin_username))
    if admin is None:
        db.add(
            User(
                username=settings.admin_username,
                display_name=settings.admin_username,
                password_hash=hash_password(settings.admin_password),
                role=UserRole.admin,
            )
        )
        db.commit()


def ensure_language_enum_values() -> None:
    if engine.dialect.name not in {"mysql", "mariadb"}:
        return
    enum_values = ", ".join(f"'{language.value}'" for language in Language)
    with engine.begin() as conn:
        column = conn.execute(text("SHOW COLUMNS FROM submissions LIKE 'language'")).mappings().first()
        if column is None:
            return
        current_type = str(column.get("Type", ""))
        if all(f"'{language.value}'" in current_type for language in Language):
            return
        conn.execute(text(f"ALTER TABLE submissions MODIFY language ENUM({enum_values}) NOT NULL"))


def ensure_float_score_columns() -> None:
    if engine.dialect.name not in {"mysql", "mariadb"}:
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE tasks MODIFY points DOUBLE NOT NULL DEFAULT 100"))
        conn.execute(text("ALTER TABLE submissions MODIFY score DOUBLE NOT NULL DEFAULT 0"))


def ensure_partial_scoring_column() -> None:
    if engine.dialect.name not in {"mysql", "mariadb"}:
        return
    with engine.begin() as conn:
        column = conn.execute(text("SHOW COLUMNS FROM tasks LIKE 'partial_scoring'")).mappings().first()
        if column is None:
            conn.execute(text("ALTER TABLE tasks ADD COLUMN partial_scoring BOOL NOT NULL DEFAULT 0"))


def ensure_task_test_scoring_columns() -> None:
    if engine.dialect.name not in {"mysql", "mariadb"}:
        return
    with engine.begin() as conn:
        points_column = conn.execute(text("SHOW COLUMNS FROM task_tests LIKE 'points'")).mappings().first()
        if points_column is None:
            conn.execute(text("ALTER TABLE task_tests ADD COLUMN points DOUBLE NULL"))
        group_column = conn.execute(text("SHOW COLUMNS FROM task_tests LIKE 'group_name'")).mappings().first()
        if group_column is None:
            conn.execute(text("ALTER TABLE task_tests ADD COLUMN group_name VARCHAR(120) NULL"))


def ensure_task_versioning_schema() -> None:
    if engine.dialect.name not in {"mysql", "mariadb"}:
        return
    with engine.begin() as conn:
        table_exists = conn.execute(text("SHOW TABLES LIKE 'task_versions'")).first() is not None
        if not table_exists:
            conn.execute(
                text(
                    """
                    CREATE TABLE task_versions (
                        id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                        task_id INT NOT NULL,
                        version_number INT NOT NULL,
                        title VARCHAR(200) NOT NULL,
                        statement TEXT NOT NULL,
                        input_format TEXT NOT NULL,
                        output_format TEXT NOT NULL,
                        samples TEXT NOT NULL,
                        time_limit_ms INT NOT NULL,
                        memory_limit_mb INT NOT NULL,
                        points DOUBLE NOT NULL DEFAULT 100,
                        partial_scoring BOOL NOT NULL DEFAULT 0,
                        tests_snapshot TEXT NOT NULL,
                        created_at DATETIME NOT NULL,
                        created_by_user_id INT NULL,
                        UNIQUE KEY uq_task_version_number (task_id, version_number),
                        INDEX ix_task_versions_task_id (task_id),
                        INDEX ix_task_versions_created_at (created_at),
                        CONSTRAINT fk_task_versions_task_id FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE,
                        CONSTRAINT fk_task_versions_created_by_user_id FOREIGN KEY (created_by_user_id) REFERENCES users(id) ON DELETE SET NULL
                    )
                    """
                )
            )
        column = conn.execute(text("SHOW COLUMNS FROM submissions LIKE 'task_version_id'")).mappings().first()
        if column is None:
            conn.execute(text("ALTER TABLE submissions ADD COLUMN task_version_id INT NULL"))
            conn.execute(text("CREATE INDEX ix_submissions_task_version_id ON submissions (task_version_id)"))


def ensure_contest_access_columns() -> None:
    if engine.dialect.name not in {"mysql", "mariadb"}:
        return
    with engine.begin() as conn:
        column = conn.execute(text("SHOW COLUMNS FROM contests LIKE 'is_public'")).mappings().first()
        if column is None:
            conn.execute(text("ALTER TABLE contests ADD COLUMN is_public BOOL NOT NULL DEFAULT 0"))
        column = conn.execute(text("SHOW COLUMNS FROM contests LIKE 'registration_enabled'")).mappings().first()
        if column is None:
            conn.execute(text("ALTER TABLE contests ADD COLUMN registration_enabled BOOL NOT NULL DEFAULT 0"))
        column = conn.execute(text("SHOW COLUMNS FROM contests LIKE 'registration_requires_approval'")).mappings().first()
        if column is None:
            conn.execute(text("ALTER TABLE contests ADD COLUMN registration_requires_approval BOOL NOT NULL DEFAULT 1"))
        column = conn.execute(text("SHOW COLUMNS FROM contests LIKE 'participation_mode'")).mappings().first()
        if column is None:
            conn.execute(text("ALTER TABLE contests ADD COLUMN participation_mode VARCHAR(20) NOT NULL DEFAULT 'individual'"))
        column = conn.execute(text("SHOW COLUMNS FROM contests LIKE 'scoreboard_freeze_at'")).mappings().first()
        if column is None:
            conn.execute(text("ALTER TABLE contests ADD COLUMN scoreboard_freeze_at DATETIME NULL"))
        column = conn.execute(text("SHOW COLUMNS FROM contests LIKE 'scoreboard_unfrozen'")).mappings().first()
        if column is None:
            conn.execute(text("ALTER TABLE contests ADD COLUMN scoreboard_unfrozen BOOL NOT NULL DEFAULT 0"))
        column = conn.execute(text("SHOW COLUMNS FROM submissions LIKE 'team_id'")).mappings().first()
        if column is None:
            conn.execute(text("ALTER TABLE submissions ADD COLUMN team_id INT NULL"))
            conn.execute(text("CREATE INDEX ix_submissions_team_id ON submissions (team_id)"))
        conn.execute(text("ALTER TABLE participant_contests MODIFY started_at DATETIME NULL"))
        conn.execute(text("ALTER TABLE participant_contests MODIFY deadline_at DATETIME NULL"))


def ensure_contest_registrations_table() -> None:
    if engine.dialect.name not in {"mysql", "mariadb"}:
        return
    with engine.begin() as conn:
        table_exists = conn.execute(text("SHOW TABLES LIKE 'contest_registrations'")).first() is not None
        if table_exists:
            return
        conn.execute(
            text(
                """
                CREATE TABLE contest_registrations (
                    id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                    contest_id INT NOT NULL,
                    user_id INT NULL,
                    team_id INT NULL,
                    status ENUM('pending', 'approved', 'rejected') NOT NULL DEFAULT 'pending',
                    requested_at DATETIME NOT NULL,
                    decided_at DATETIME NULL,
                    decided_by_user_id INT NULL,
                    UNIQUE KEY uq_contest_registration_user (contest_id, user_id),
                    UNIQUE KEY uq_contest_registration_team (contest_id, team_id),
                    INDEX ix_contest_registrations_contest_id (contest_id),
                    INDEX ix_contest_registrations_user_id (user_id),
                    INDEX ix_contest_registrations_team_id (team_id),
                    INDEX ix_contest_registrations_status (status),
                    INDEX ix_contest_registrations_requested_at (requested_at),
                    CONSTRAINT fk_contest_registrations_contest_id FOREIGN KEY (contest_id) REFERENCES contests(id) ON DELETE CASCADE,
                    CONSTRAINT fk_contest_registrations_user_id FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                    CONSTRAINT fk_contest_registrations_team_id FOREIGN KEY (team_id) REFERENCES teams(id) ON DELETE CASCADE,
                    CONSTRAINT fk_contest_registrations_decided_by_user_id FOREIGN KEY (decided_by_user_id) REFERENCES users(id) ON DELETE SET NULL
                )
                """
            )
        )


def ensure_clarifications_table() -> None:
    if engine.dialect.name not in {"mysql", "mariadb"}:
        return
    with engine.begin() as conn:
        table_exists = conn.execute(text("SHOW TABLES LIKE 'clarifications'")).first() is not None
        if table_exists:
            return
        conn.execute(
            text(
                """
                CREATE TABLE clarifications (
                    id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                    contest_id INT NOT NULL,
                    task_id INT NULL,
                    author_user_id INT NOT NULL,
                    question TEXT NOT NULL,
                    answer TEXT NULL,
                    status ENUM('open', 'answered', 'closed') NOT NULL DEFAULT 'open',
                    visibility ENUM('private', 'broadcast') NOT NULL DEFAULT 'private',
                    answered_by_user_id INT NULL,
                    created_at DATETIME NOT NULL,
                    answered_at DATETIME NULL,
                    INDEX ix_clarifications_contest_id (contest_id),
                    INDEX ix_clarifications_task_id (task_id),
                    INDEX ix_clarifications_author_user_id (author_user_id),
                    INDEX ix_clarifications_status (status),
                    INDEX ix_clarifications_visibility (visibility),
                    INDEX ix_clarifications_created_at (created_at),
                    CONSTRAINT fk_clarifications_contest_id FOREIGN KEY (contest_id) REFERENCES contests(id) ON DELETE CASCADE,
                    CONSTRAINT fk_clarifications_task_id FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE SET NULL,
                    CONSTRAINT fk_clarifications_author_user_id FOREIGN KEY (author_user_id) REFERENCES users(id) ON DELETE CASCADE,
                    CONSTRAINT fk_clarifications_answered_by_user_id FOREIGN KEY (answered_by_user_id) REFERENCES users(id) ON DELETE SET NULL
                )
                """
            )
        )


def ensure_legacy_task_links(db: Session) -> None:
    legacy_tasks = db.scalars(select(Task).where(Task.contest_id.is_not(None))).all()
    changed = False
    for task in legacy_tasks:
        if task.contest_id is None:
            continue
        exists = db.scalar(select(ContestTask.id).where(ContestTask.contest_id == task.contest_id, ContestTask.task_id == task.id))
        if exists is None:
            position = db.query(ContestTask).filter(ContestTask.contest_id == task.contest_id).count()
            db.add(ContestTask(contest_id=task.contest_id, task_id=task.id, position=position))
            changed = True
    if changed:
        db.commit()


@app.on_event("startup")
def startup() -> None:
    # Migrations are the primary schema path. These MariaDB patches are kept
    # only to tolerate existing local volumes created before Alembic existed.
    ensure_language_enum_values()
    ensure_float_score_columns()
    ensure_partial_scoring_column()
    ensure_task_test_scoring_columns()
    ensure_task_versioning_schema()
    ensure_contest_access_columns()
    ensure_contest_registrations_table()
    ensure_clarifications_table()
    with SessionLocal() as db:
        ensure_admin(db)
        ensure_legacy_task_links(db)


def to_task_out(task: Task) -> TaskOut:
    contest_ids = sorted(link.contest_id for link in task.contests)
    current_version_number = max((version.version_number for version in task.versions), default=None)
    return TaskOut(
        id=task.id,
        contest_id=task.contest_id,
        contest_ids=contest_ids,
        current_version_number=current_version_number,
        title=task.title,
        statement=task.statement,
        input_format=task.input_format,
        output_format=task.output_format,
        samples=json.loads(task.samples or "[]"),
        time_limit_ms=task.time_limit_ms,
        memory_limit_mb=task.memory_limit_mb,
        points=task.points,
        partial_scoring=task.partial_scoring,
        test_count=len(task.tests),
    )


def to_task_detail_out(task: Task, include_tests: bool = False) -> TaskDetailOut:
    task_out = to_task_out(task)
    tests = None
    if include_tests:
        tests = [TaskTestPublicOut(id=test.id, is_sample=test.is_sample) for test in task.tests]
    return TaskDetailOut(**task_out.model_dump(), tests=tests)


def task_tests_snapshot(task: Task) -> list[dict[str, object]]:
    return [
        {
            "id": test.id,
            "input_data": test.input_data,
            "output_data": test.output_data,
            "is_sample": test.is_sample,
            "points": test.points,
            "group_name": test.group_name,
        }
        for test in sorted(task.tests, key=lambda item: item.id)
    ]


def task_snapshot_payload(task: Task) -> dict[str, object]:
    return {
        "title": task.title,
        "statement": task.statement,
        "input_format": task.input_format,
        "output_format": task.output_format,
        "samples": task.samples,
        "time_limit_ms": task.time_limit_ms,
        "memory_limit_mb": task.memory_limit_mb,
        "points": float(task.points),
        "partial_scoring": bool(task.partial_scoring),
        "tests_snapshot": json.dumps(task_tests_snapshot(task), sort_keys=True, separators=(",", ":")),
    }


def version_snapshot_payload(version: TaskVersion) -> dict[str, object]:
    return {
        "title": version.title,
        "statement": version.statement,
        "input_format": version.input_format,
        "output_format": version.output_format,
        "samples": version.samples,
        "time_limit_ms": version.time_limit_ms,
        "memory_limit_mb": version.memory_limit_mb,
        "points": float(version.points),
        "partial_scoring": bool(version.partial_scoring),
        "tests_snapshot": version.tests_snapshot,
    }


def create_task_version_if_changed(db: Session, task: Task, user_id: int | None = None) -> TaskVersion:
    db.flush()
    db.refresh(task, attribute_names=["tests", "versions"])
    latest = max(task.versions, key=lambda version: version.version_number, default=None)
    payload = task_snapshot_payload(task)
    if latest is not None and version_snapshot_payload(latest) == payload:
        return latest
    version_number = (latest.version_number if latest is not None else 0) + 1
    version = TaskVersion(
        task_id=task.id,
        version_number=version_number,
        created_by_user_id=user_id,
        **payload,
    )
    db.add(version)
    db.flush()
    if version not in task.versions:
        task.versions.append(version)
    return version


def to_task_version_out(version: TaskVersion) -> TaskVersionOut:
    return TaskVersionOut(
        id=version.id,
        task_id=version.task_id,
        version_number=version.version_number,
        title=version.title,
        statement=version.statement,
        input_format=version.input_format,
        output_format=version.output_format,
        samples=json.loads(version.samples or "[]"),
        time_limit_ms=version.time_limit_ms,
        memory_limit_mb=version.memory_limit_mb,
        points=version.points,
        partial_scoring=version.partial_scoring,
        tests_snapshot=json.loads(version.tests_snapshot or "[]"),
        created_at=version.created_at,
        created_by_user_id=version.created_by_user_id,
    )


def to_team_out(team: Team) -> TeamOut:
    return TeamOut(
        id=team.id,
        name=team.name,
        member_ids=[member.user_id for member in team.members],
        created_at=team.created_at,
    )


def get_user_or_404(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user


def get_team_or_404(db: Session, team_id: int) -> Team:
    team = db.scalar(select(Team).where(Team.id == team_id).options(selectinload(Team.members)))
    if team is None:
        raise HTTPException(status_code=404, detail="Team not found")
    return team


def get_contest_or_404(db: Session, contest_id: int) -> Contest:
    contest = db.get(Contest, contest_id)
    if contest is None:
        raise HTTPException(status_code=404, detail="Contest not found")
    return contest


def get_task_or_404(db: Session, task_id: int) -> Task:
    task = db.scalar(
        select(Task)
        .where(Task.id == task_id)
        .options(selectinload(Task.tests), selectinload(Task.contests), selectinload(Task.versions))
    )
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


def get_test_or_404(db: Session, test_id: int) -> TaskTest:
    test = db.get(TaskTest, test_id)
    if test is None:
        raise HTTPException(status_code=404, detail="Test not found")
    return test


def replace_team_members(db: Session, team: Team, user_ids: list[int]) -> None:
    unique_user_ids = list(dict.fromkeys(user_ids))
    if unique_user_ids:
        existing_ids = set(db.scalars(select(User.id).where(User.id.in_(unique_user_ids))).all())
        missing = sorted(set(unique_user_ids) - existing_ids)
        if missing:
            raise HTTPException(status_code=400, detail=f"Unknown user ids: {missing}")
    team.members.clear()
    db.flush()
    for user_id in unique_user_ids:
        team.members.append(TeamMember(user_id=user_id))


def replace_contest_teams(db: Session, contest: Contest, team_ids: list[int]) -> list[TeamOut]:
    unique_team_ids = list(dict.fromkeys(team_ids))
    if unique_team_ids:
        existing_ids = set(db.scalars(select(Team.id).where(Team.id.in_(unique_team_ids))).all())
        missing = sorted(set(unique_team_ids) - existing_ids)
        if missing:
            raise HTTPException(status_code=400, detail=f"Unknown team ids: {missing}")
    db.query(ContestTeam).filter(ContestTeam.contest_id == contest.id).delete(synchronize_session=False)
    db.flush()
    for team_id in unique_team_ids:
        db.add(ContestTeam(contest_id=contest.id, team_id=team_id))
    db.commit()
    return list_contest_teams(contest.id, db=db)


def participant_has_contest_access(db: Session, contest_id: int, user_id: int) -> bool:
    return (
        db.scalar(
            select(ParticipantContest.id).where(
                ParticipantContest.contest_id == contest_id,
                ParticipantContest.user_id == user_id,
            )
        )
        is not None
    )


def participant_has_approved_registration(db: Session, contest_id: int, user_id: int) -> bool:
    return (
        db.scalar(
            select(ContestRegistration.id).where(
                ContestRegistration.contest_id == contest_id,
                ContestRegistration.user_id == user_id,
                ContestRegistration.status == ContestRegistrationStatus.approved,
            )
        )
        is not None
    )


def get_assigned_contest_team_ids_for_user(db: Session, contest_id: int, user_id: int) -> list[int]:
    return list(
        db.scalars(
            select(Team.id)
            .join(TeamMember, TeamMember.team_id == Team.id)
            .join(ContestTeam, ContestTeam.team_id == Team.id)
            .where(ContestTeam.contest_id == contest_id, TeamMember.user_id == user_id)
            .order_by(Team.id)
        )
    )


def get_approved_registered_team_ids_for_user(db: Session, contest_id: int, user_id: int) -> list[int]:
    return list(
        db.scalars(
            select(Team.id)
            .join(TeamMember, TeamMember.team_id == Team.id)
            .join(ContestRegistration, ContestRegistration.team_id == Team.id)
            .where(
                ContestRegistration.contest_id == contest_id,
                ContestRegistration.status == ContestRegistrationStatus.approved,
                TeamMember.user_id == user_id,
            )
            .order_by(Team.id)
        )
    )


def get_accessible_team_ids_for_user(db: Session, contest_id: int, user_id: int) -> list[int]:
    return sorted(
        {
            *get_assigned_contest_team_ids_for_user(db, contest_id, user_id),
            *get_approved_registered_team_ids_for_user(db, contest_id, user_id),
        }
    )


def participant_has_team_contest_access(db: Session, contest: Contest, user_id: int) -> bool:
    if contest.participation_mode != ContestParticipationMode.team:
        return False
    return bool(get_accessible_team_ids_for_user(db, contest.id, user_id))


def assert_contest_access(db: Session, contest: Contest, user: User) -> None:
    if user.role == UserRole.admin:
        return
    if contest.is_public:
        return
    if participant_has_contest_access(db, contest.id, user.id):
        return
    if participant_has_team_contest_access(db, contest, user.id):
        return
    if participant_has_approved_registration(db, contest.id, user.id):
        return
    raise HTTPException(status_code=403, detail="Contest is not available")


def assert_contest_visible_for_registration(db: Session, contest: Contest, user: User) -> None:
    if contest.registration_enabled:
        return
    assert_contest_access(db, contest, user)


def get_user_team_ids(db: Session, user_id: int) -> list[int]:
    return list(
        db.scalars(
            select(Team.id)
            .join(TeamMember, TeamMember.team_id == Team.id)
            .where(TeamMember.user_id == user_id)
            .order_by(Team.id)
        )
    )


def resolve_registration_team_id(db: Session, contest: Contest, user: User) -> int | None:
    if contest.participation_mode == ContestParticipationMode.individual:
        return None
    team_ids = get_user_team_ids(db, user.id)
    if len(team_ids) != 1:
        detail = "Team contest registration requires exactly one team membership"
        if len(team_ids) > 1:
            detail = "Team contest registration requires exactly one team membership; multiple teams found"
        raise HTTPException(status_code=403, detail=detail)
    return team_ids[0]


def resolve_submission_team_id(db: Session, contest: Contest, user: User) -> int | None:
    if contest.participation_mode == ContestParticipationMode.individual:
        return None
    team_ids = get_accessible_team_ids_for_user(db, contest.id, user.id)
    if len(team_ids) != 1:
        detail = "Team contest requires exactly one approved team membership"
        if len(team_ids) > 1:
            detail = "Team contest requires exactly one approved team membership; multiple approved teams found"
        raise HTTPException(status_code=403, detail=detail)
    return team_ids[0]


def replace_contest_participants(db: Session, contest: Contest, user_ids: list[int]) -> list[User]:
    unique_user_ids = list(dict.fromkeys(user_ids))
    if unique_user_ids:
        users = db.scalars(select(User).where(User.id.in_(unique_user_ids))).all()
        users_by_id = {user.id: user for user in users}
        missing = sorted(set(unique_user_ids) - set(users_by_id))
        if missing:
            raise HTTPException(status_code=400, detail=f"Unknown user ids: {missing}")
        non_participants = sorted(user_id for user_id, user in users_by_id.items() if user.role != UserRole.participant)
        if non_participants:
            raise HTTPException(status_code=400, detail=f"Non-participant user ids: {non_participants}")
    existing = {
        row.user_id: row
        for row in db.scalars(select(ParticipantContest).where(ParticipantContest.contest_id == contest.id)).all()
    }
    for user_id, row in existing.items():
        if user_id not in unique_user_ids:
            db.delete(row)
    for user_id in unique_user_ids:
        if user_id not in existing:
            db.add(ParticipantContest(contest_id=contest.id, user_id=user_id))
    db.commit()
    return list_contest_participants(contest.id, db=db)


def to_registration_detail_out(db: Session, registration: ContestRegistration, user: User | None = None) -> ContestRegistrationDetailOut:
    contest = get_contest_or_404(db, registration.contest_id)
    registrant = db.get(User, registration.user_id) if registration.user_id else None
    team = db.get(Team, registration.team_id) if registration.team_id else None
    decided_by = db.get(User, registration.decided_by_user_id) if registration.decided_by_user_id else None
    can_access = False
    if user is not None:
        try:
            assert_contest_access(db, contest, user)
            can_access = True
        except HTTPException:
            can_access = False
    return ContestRegistrationDetailOut(
        id=registration.id,
        contest_id=registration.contest_id,
        user_id=registration.user_id,
        team_id=registration.team_id,
        status=registration.status,
        requested_at=registration.requested_at,
        decided_at=registration.decided_at,
        decided_by_user_id=registration.decided_by_user_id,
        contest_title=contest.title,
        username=registrant.username if registrant else None,
        user_display_name=registrant.display_name if registrant else None,
        team_name=team.name if team else None,
        decided_by_username=decided_by.username if decided_by else None,
        can_access=can_access,
    )


def get_current_registration(db: Session, contest: Contest, user: User) -> ContestRegistration | None:
    if contest.participation_mode == ContestParticipationMode.team:
        team_ids = get_user_team_ids(db, user.id)
        if not team_ids:
            return None
        return db.scalar(
            select(ContestRegistration)
            .where(
                ContestRegistration.contest_id == contest.id,
                ContestRegistration.team_id.in_(team_ids),
            )
            .order_by(ContestRegistration.requested_at.desc(), ContestRegistration.id.desc())
            .limit(1)
        )
    return db.scalar(
        select(ContestRegistration).where(
            ContestRegistration.contest_id == contest.id,
            ContestRegistration.user_id == user.id,
        )
    )


def get_or_start_participant_contest(db: Session, contest: Contest, user: User) -> ParticipantContest:
    existing = db.scalar(
        select(ParticipantContest).where(
            ParticipantContest.contest_id == contest.id,
            ParticipantContest.user_id == user.id,
        )
    )
    if existing and existing.started_at is not None and existing.deadline_at is not None:
        return existing
    started_at = now_utc()
    if contest.time_mode == ContestTimeMode.individual:
        if contest.individual_duration_minutes is None:
            raise HTTPException(status_code=400, detail="Individual duration is not configured")
        deadline = min(contest.ends_at, started_at + timedelta(minutes=contest.individual_duration_minutes))
    else:
        deadline = contest.ends_at
    participant = existing or ParticipantContest(contest_id=contest.id, user_id=user.id)
    participant.started_at = started_at
    participant.deadline_at = deadline
    if existing is None:
        db.add(participant)
    db.commit()
    db.refresh(participant)
    return participant


def assert_contest_allows_submission(db: Session, contest: Contest, user: User) -> None:
    assert_contest_access(db, contest, user)
    current = now_utc()
    if current < contest.starts_at or current > contest.ends_at:
        raise HTTPException(status_code=400, detail="Contest is outside the available window")
    if contest.time_mode == ContestTimeMode.individual and contest.individual_duration_minutes is None:
        raise HTTPException(status_code=400, detail="Individual duration is not configured")
    participant = get_or_start_participant_contest(db, contest, user)
    if participant.deadline_at is not None and current > participant.deadline_at:
        raise HTTPException(status_code=400, detail="Individual contest deadline has passed")


def get_sse_user(token: str | None, db: Session) -> User:
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    return get_user_from_token(token, db)


@app.post("/api/auth/login", response_model=TokenOut)
def login(data: LoginIn, db: Session = Depends(get_db)) -> TokenOut:
    user = db.scalar(select(User).where(User.username == data.username, User.is_active.is_(True)))
    if user is None or not verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    return TokenOut(access_token=create_access_token(user))


@app.get("/api/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> User:
    return user


@app.get("/api/users", response_model=list[UserOut])
def list_users(_: User = Depends(require_admin), db: Session = Depends(get_db)) -> list[User]:
    return list(db.scalars(select(User).order_by(User.username)))


@app.post("/api/users", response_model=UserOut)
def create_user(data: UserCreate, _: User = Depends(require_admin), db: Session = Depends(get_db)) -> User:
    user = User(
        username=data.username,
        password_hash=hash_password(data.password),
        display_name=data.display_name or data.username,
        role=data.role,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Username already exists") from exc
    db.refresh(user)
    return user


@app.get("/api/users/{user_id}", response_model=UserOut)
def get_user(user_id: int, _: User = Depends(require_admin), db: Session = Depends(get_db)) -> User:
    return get_user_or_404(db, user_id)


@app.patch("/api/users/{user_id}", response_model=UserOut)
def update_user(user_id: int, data: UserUpdate, _: User = Depends(require_admin), db: Session = Depends(get_db)) -> User:
    user = get_user_or_404(db, user_id)
    updates = data.model_dump(exclude_unset=True)
    password = updates.pop("password", None)
    for key, value in updates.items():
        setattr(user, key, value)
    if password is not None:
        user.password_hash = hash_password(password)
    if user.display_name is None:
        user.display_name = user.username
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Username already exists") from exc
    db.refresh(user)
    return user


@app.delete("/api/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(user_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)) -> Response:
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="Cannot delete current admin user")
    user = get_user_or_404(db, user_id)
    db.delete(user)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def parse_import_file(filename: str, content: bytes) -> list[dict]:
    suffix = filename.rsplit(".", 1)[-1].lower()
    text = content.decode("utf-8-sig")
    if suffix == "csv":
        return list(csv.DictReader(io.StringIO(text)))
    if suffix == "json":
        data = json.loads(text)
        if not isinstance(data, list):
            raise ValueError("JSON root must be an array")
        return data
    if suffix in {"yml", "yaml"}:
        data = yaml.safe_load(text)
        if not isinstance(data, list):
            raise ValueError("YAML root must be a list")
        return data
    raise ValueError("Unsupported import format")


@app.post("/api/users/import", response_model=ImportReport)
async def import_users(file: UploadFile = File(...), _: User = Depends(require_admin), db: Session = Depends(get_db)) -> ImportReport:
    try:
        rows = parse_import_file(file.filename or "", await file.read())
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    created = 0
    skipped = 0
    errors: list[str] = []
    for index, row in enumerate(rows, start=1):
        username = str(row.get("username") or "").strip()
        password = str(row.get("password") or "")
        display_name = str(row.get("display_name") or username).strip()
        role_value = str(row.get("role") or UserRole.participant.value).strip()
        if not username or not password:
            skipped += 1
            errors.append(f"Row {index}: username and password are required")
            continue
        if db.scalar(select(User).where(User.username == username)):
            skipped += 1
            errors.append(f"Row {index}: username '{username}' already exists")
            continue
        try:
            role = UserRole(role_value)
        except ValueError:
            skipped += 1
            errors.append(f"Row {index}: unknown role '{role_value}'")
            continue
        db.add(User(username=username, password_hash=hash_password(password), display_name=display_name, role=role))
        created += 1
    db.commit()
    return ImportReport(created=created, skipped=skipped, errors=errors)


def count_rows(db: Session, model: type[object]) -> int:
    return db.scalar(select(func.count()).select_from(model)) or 0


def grouped_counts(db: Session, column: object) -> dict[object, int]:
    rows = db.execute(select(column, func.count()).group_by(column)).all()
    return {key: count for key, count in rows}


def percentile_nearest_rank(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int((percentile / 100) * len(ordered) + 0.999999) - 1))
    return ordered[index]


def decode_json_list(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        data = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    return [str(item) for item in data]


def decode_json_dict(value: str | None) -> dict[str, object]:
    if not value:
        return {}
    try:
        data = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def normalize_optional_string(value: object | None) -> str | None:
    if value is None:
        return None
    return str(value).strip() or None


def judger_health(judger: Judger, current: datetime) -> str:
    if not judger.enabled or judger.status == "offline":
        return "offline"
    age_seconds = (current - normalize_dt(judger.last_seen_at)).total_seconds()
    if age_seconds <= JUDGER_ACTIVE_SECONDS:
        return "active"
    if age_seconds <= JUDGER_OFFLINE_SECONDS:
        return "stale"
    return "offline"


def to_admin_judger_out(judger: Judger, current: datetime) -> AdminJudgerOut:
    return AdminJudgerOut(
        id=judger.id,
        judger_id=judger.judger_id,
        hostname=judger.hostname,
        version=judger.version,
        supported_languages=decode_json_list(judger.supported_languages),
        sandbox_mode=judger.sandbox_mode,
        capabilities=decode_json_dict(judger.capabilities),
        status=judger.status,
        health=judger_health(judger, current),
        current_submission_id=judger.current_submission_id,
        registered_at=judger.registered_at,
        last_seen_at=judger.last_seen_at,
        last_state_change_at=judger.last_state_change_at,
        enabled=judger.enabled,
        last_error=judger.last_error,
    )


def decode_event_payload(value: str | None) -> object | None:
    if not value:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def to_admin_judger_event_out(event: JudgerEvent) -> AdminJudgerEventOut:
    return AdminJudgerEventOut(
        id=event.id,
        judger_id=event.judger_id,
        event_type=event.event_type,
        submission_id=event.submission_id,
        message=event.message,
        payload=decode_event_payload(event.payload),
        created_at=event.created_at,
    )


def record_judger_health_events(db: Session, judgers: list[Judger], current: datetime) -> None:
    changed = False
    for judger in judgers:
        health = judger_health(judger, current)
        if health not in {"stale", "offline"}:
            continue
        event_type = "heartbeat_missed" if health == "offline" else "heartbeat_stale"
        latest_event = db.scalar(
            select(JudgerEvent)
            .where(JudgerEvent.judger_id == judger.judger_id)
            .where(JudgerEvent.event_type == event_type)
            .order_by(JudgerEvent.created_at.desc(), JudgerEvent.id.desc())
            .limit(1)
        )
        if latest_event is not None and normalize_dt(latest_event.created_at) >= normalize_dt(judger.last_seen_at):
            continue
        age_seconds = max(0, int((current - normalize_dt(judger.last_seen_at)).total_seconds()))
        db.add(
            JudgerEvent(
                judger_id=judger.judger_id,
                event_type=event_type,
                message=f"Heartbeat {health}",
                payload=json.dumps({"age_seconds": age_seconds, "status": judger.status}),
                created_at=current,
            )
        )
        changed = True
    if changed:
        db.commit()


@app.get("/api/admin/stats", response_model=AdminStatsOut)
def admin_stats(_: User = Depends(require_admin), db: Session = Depends(get_db)) -> AdminStatsOut:
    current = now_utc()
    one_hour_ago = current - timedelta(hours=1)
    one_day_ago = current - timedelta(hours=24)
    stale_running_before = current - timedelta(seconds=STALE_RUNNING_SECONDS)

    users_by_role = grouped_counts(db, User.role)
    contests_by_status = grouped_counts(db, Contest.status)
    submissions_by_verdict = grouped_counts(db, Submission.verdict)
    submissions_by_language = grouped_counts(db, Submission.language)
    submission_total = sum(submissions_by_verdict.values())
    queue_depth = submissions_by_verdict.get(SubmissionVerdict.queued, 0)
    running_count = submissions_by_verdict.get(SubmissionVerdict.running, 0)
    accepted_total = submissions_by_verdict.get(SubmissionVerdict.accepted, 0)
    internal_error_count = submissions_by_verdict.get(SubmissionVerdict.internal_error, 0)
    average_score = db.scalar(select(func.avg(Submission.score))) if submission_total else 0
    oldest_queued_at = db.scalar(
        select(func.min(Submission.created_at)).where(Submission.verdict == SubmissionVerdict.queued)
    )
    oldest_queued_age_seconds = None
    if oldest_queued_at is not None:
        oldest_queued_age_seconds = max(0, int((current - normalize_dt(oldest_queued_at)).total_seconds()))
    stale_running_count = db.scalar(
        select(func.count())
        .select_from(Submission)
        .where(Submission.verdict == SubmissionVerdict.running)
        .where(Submission.started_at.is_not(None))
        .where(Submission.started_at < stale_running_before)
    ) or 0
    expired_running_leases = db.scalar(
        select(func.count())
        .select_from(Submission)
        .where(Submission.verdict == SubmissionVerdict.running)
        .where(Submission.claim_expires_at.is_not(None))
        .where(Submission.claim_expires_at < current)
    ) or 0
    finished_1h = db.scalar(
        select(func.count()).select_from(Submission).where(Submission.finished_at.is_not(None)).where(Submission.finished_at >= one_hour_ago)
    ) or 0
    finished_24h = db.scalar(
        select(func.count()).select_from(Submission).where(Submission.finished_at.is_not(None)).where(Submission.finished_at >= one_day_ago)
    ) or 0
    judging_rows = db.execute(
        select(Submission.started_at, Submission.finished_at)
        .where(Submission.started_at.is_not(None))
        .where(Submission.finished_at.is_not(None))
    ).all()
    judging_durations = []
    for started_at, finished_at in judging_rows:
        normalized_started_at = normalize_dt(started_at)
        normalized_finished_at = normalize_dt(finished_at)
        if normalized_finished_at >= normalized_started_at:
            judging_durations.append((normalized_finished_at - normalized_started_at).total_seconds())
    average_judging_time_seconds = (
        round(sum(judging_durations) / len(judging_durations), 2) if judging_durations else None
    )
    p95_judging_time = percentile_nearest_rank(judging_durations, 95)
    p95_judging_time_seconds = round(p95_judging_time, 2) if p95_judging_time is not None else None
    running_by_judger = db.execute(
        select(Submission.judger_id, func.count())
        .where(Submission.verdict == SubmissionVerdict.running)
        .group_by(Submission.judger_id)
    ).all()
    recent_finished_by_judger = db.execute(
        select(Submission.judger_id, func.count())
        .where(Submission.finished_at.is_not(None))
        .where(Submission.finished_at >= one_day_ago)
        .group_by(Submission.judger_id)
    ).all()
    database_ok = True
    try:
        db.execute(text("SELECT 1")).scalar()
    except Exception:
        database_ok = False
    registered_judgers = db.scalars(select(Judger)).all()
    record_judger_health_events(db, list(registered_judgers), current)
    judger_health_counts = {"active": 0, "stale": 0, "offline": 0}
    for judger in registered_judgers:
        judger_health_counts[judger_health(judger, current)] += 1

    return AdminStatsOut(
        users=AdminUsersStats(
            total=count_rows(db, User),
            active=db.scalar(select(func.count()).select_from(User).where(User.is_active.is_(True))) or 0,
            admin=users_by_role.get(UserRole.admin, 0),
            participant=users_by_role.get(UserRole.participant, 0),
        ),
        teams_total=count_rows(db, Team),
        contests=AdminContestsStats(
            total=count_rows(db, Contest),
            by_status={status: contests_by_status.get(status, 0) for status in ContestStatus},
            public=db.scalar(select(func.count()).select_from(Contest).where(Contest.is_public.is_(True))) or 0,
            private=db.scalar(select(func.count()).select_from(Contest).where(Contest.is_public.is_(False))) or 0,
            individual=db.scalar(select(func.count()).select_from(Contest).where(Contest.participation_mode == ContestParticipationMode.individual)) or 0,
            team=db.scalar(select(func.count()).select_from(Contest).where(Contest.participation_mode == ContestParticipationMode.team)) or 0,
        ),
        tasks_total=count_rows(db, Task),
        tests_total=count_rows(db, TaskTest),
        submissions=AdminSubmissionsStats(
            total=submission_total,
            by_verdict={verdict: submissions_by_verdict.get(verdict, 0) for verdict in SubmissionVerdict},
            by_language={language: submissions_by_language.get(language, 0) for language in Language},
            queued=queue_depth,
            running=running_count,
            recent_1h=db.scalar(select(func.count()).select_from(Submission).where(Submission.created_at >= one_hour_ago)) or 0,
            recent_24h=db.scalar(select(func.count()).select_from(Submission).where(Submission.created_at >= one_day_ago)) or 0,
            queue_depth=queue_depth,
            running_count=running_count,
            oldest_queued_age_seconds=oldest_queued_age_seconds,
            stale_running_count=stale_running_count,
            expired_running_leases=expired_running_leases,
            finished_1h=finished_1h,
            finished_24h=finished_24h,
            average_judging_time_seconds=average_judging_time_seconds,
            p95_judging_time_seconds=p95_judging_time_seconds,
            internal_error_count=internal_error_count,
            internal_error_rate=round((internal_error_count / submission_total) * 100, 2) if submission_total else 0,
            accepted_rate=round((accepted_total / submission_total) * 100, 2) if submission_total else 0,
            average_score=round(float(average_score or 0), 2),
        ),
        judgers=AdminJudgerStats(
            running_by_judger_id={judger_id or "unknown": count for judger_id, count in running_by_judger},
            recent_finished_by_judger_id={judger_id or "unknown": count for judger_id, count in recent_finished_by_judger},
            active=judger_health_counts["active"],
            stale=judger_health_counts["stale"],
            offline=judger_health_counts["offline"],
        ),
        system=AdminSystemStats(server_time=current, database_ok=database_ok),
    )


@app.get("/api/admin/judgers", response_model=list[AdminJudgerOut])
def list_admin_judgers(_: User = Depends(require_admin), db: Session = Depends(get_db)) -> list[AdminJudgerOut]:
    current = now_utc()
    judgers = db.scalars(select(Judger).order_by(Judger.judger_id)).all()
    record_judger_health_events(db, list(judgers), current)
    return [to_admin_judger_out(judger, current) for judger in judgers]


@app.get("/api/admin/judger-events", response_model=list[AdminJudgerEventOut])
def list_admin_judger_events(
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[AdminJudgerEventOut]:
    events = db.scalars(select(JudgerEvent).order_by(JudgerEvent.created_at.desc(), JudgerEvent.id.desc()).limit(limit)).all()
    return [to_admin_judger_event_out(event) for event in events]


@app.get("/api/admin/judgers/{judger_id}/events", response_model=list[AdminJudgerEventOut])
def list_admin_judger_events_for_judger(
    judger_id: str,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[AdminJudgerEventOut]:
    events = db.scalars(
        select(JudgerEvent)
        .where(JudgerEvent.judger_id == judger_id)
        .order_by(JudgerEvent.created_at.desc(), JudgerEvent.id.desc())
        .limit(limit)
    ).all()
    return [to_admin_judger_event_out(event) for event in events]


@app.get("/api/teams", response_model=list[TeamOut])
def list_teams(_: User = Depends(require_admin), db: Session = Depends(get_db)) -> list[TeamOut]:
    teams = db.scalars(select(Team).options(selectinload(Team.members)).order_by(Team.name)).all()
    return [to_team_out(team) for team in teams]


def replace_contest_tasks(db: Session, contest: Contest, task_ids: list[int]) -> list[TaskOut]:
    unique_task_ids = list(dict.fromkeys(task_ids))
    if unique_task_ids:
        existing_ids = set(db.scalars(select(Task.id).where(Task.id.in_(unique_task_ids))).all())
        missing = sorted(set(unique_task_ids) - existing_ids)
        if missing:
            raise HTTPException(status_code=400, detail=f"Unknown task ids: {missing}")
    db.query(ContestTask).filter(ContestTask.contest_id == contest.id).delete(synchronize_session=False)
    for position, task_id in enumerate(unique_task_ids):
        db.add(ContestTask(contest_id=contest.id, task_id=task_id, position=position))
    db.commit()
    return list_contest_tasks(db, contest.id)


def attach_task_to_contests(db: Session, task: Task, contest_ids: list[int]) -> None:
    unique_contest_ids = list(dict.fromkeys(contest_ids))
    if unique_contest_ids:
        existing_ids = set(db.scalars(select(Contest.id).where(Contest.id.in_(unique_contest_ids))).all())
        missing = sorted(set(unique_contest_ids) - existing_ids)
        if missing:
            raise HTTPException(status_code=404, detail=f"Unknown contest ids: {missing}")
    for contest_id in unique_contest_ids:
        exists = db.scalar(select(ContestTask.id).where(ContestTask.contest_id == contest_id, ContestTask.task_id == task.id))
        if exists is None:
            position = db.query(ContestTask).filter(ContestTask.contest_id == contest_id).count()
            db.add(ContestTask(contest_id=contest_id, task_id=task.id, position=position))


def task_belongs_to_contest(db: Session, contest_id: int, task_id: int) -> bool:
    return db.scalar(select(ContestTask.id).where(ContestTask.contest_id == contest_id, ContestTask.task_id == task_id)) is not None


def to_clarification_out(db: Session, clarification: Clarification) -> ClarificationOut:
    author = get_user_or_404(db, clarification.author_user_id)
    answered_by = db.get(User, clarification.answered_by_user_id) if clarification.answered_by_user_id else None
    task_title = db.scalar(select(Task.title).where(Task.id == clarification.task_id)) if clarification.task_id else None
    return ClarificationOut(
        id=clarification.id,
        contest_id=clarification.contest_id,
        task_id=clarification.task_id,
        task_title=task_title,
        author_user_id=clarification.author_user_id,
        author_username=author.username,
        author_display_name=author.display_name,
        question=clarification.question,
        answer=clarification.answer,
        status=clarification.status,
        visibility=clarification.visibility,
        answered_by_user_id=clarification.answered_by_user_id,
        answered_by_username=answered_by.username if answered_by else None,
        created_at=clarification.created_at,
        answered_at=clarification.answered_at,
    )


def list_clarifications_for_contest(db: Session, contest: Contest, user: User) -> list[Clarification]:
    stmt = select(Clarification).where(Clarification.contest_id == contest.id)
    if user.role != UserRole.admin:
        stmt = stmt.where(
            or_(
                Clarification.author_user_id == user.id,
                Clarification.visibility == ClarificationVisibility.broadcast,
            )
        )
    stmt = stmt.order_by(Clarification.created_at.desc(), Clarification.id.desc())
    return list(db.scalars(stmt))


def list_contest_tasks(db: Session, contest_id: int) -> list[TaskOut]:
    tasks = db.scalars(
        select(Task)
        .join(ContestTask, ContestTask.task_id == Task.id)
        .where(ContestTask.contest_id == contest_id)
        .options(selectinload(Task.tests), selectinload(Task.contests), selectinload(Task.versions))
        .order_by(ContestTask.position, Task.id)
    ).all()
    return [to_task_out(task) for task in tasks]


def safe_archive_member_name(name: str) -> str | None:
    if "\\" in name:
        return None
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        return None
    if not path.name:
        return None
    return path.name


def safe_package_member_name(name: str) -> str | None:
    if "\\" in name:
        return None
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        return None
    if not path.name:
        return None
    return path.as_posix()


def slug_filename(value: str, fallback: str = "package") -> str:
    safe = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in value.strip().lower())
    safe = "_".join(part for part in safe.split("_") if part)
    return safe or fallback


def read_package_zip(content: bytes) -> dict[str, bytes]:
    if len(content) > PACKAGE_MAX_TOTAL_BYTES:
        raise HTTPException(status_code=400, detail="Package archive is too large")
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as exc:
        raise HTTPException(status_code=400, detail="Invalid zip archive") from exc

    files: dict[str, bytes] = {}
    total_size = 0
    with archive:
        members = [info for info in archive.infolist() if not info.is_dir()]
        if len(members) > PACKAGE_MAX_FILES:
            raise HTTPException(status_code=400, detail=f"Package has too many files (max {PACKAGE_MAX_FILES})")
        for info in members:
            safe_name = safe_package_member_name(info.filename)
            if safe_name is None:
                raise HTTPException(status_code=400, detail=f"Unsafe package path: {info.filename}")
            if info.file_size > PACKAGE_MAX_FILE_BYTES:
                raise HTTPException(status_code=400, detail=f"Package file is too large: {safe_name}")
            total_size += info.file_size
            if total_size > PACKAGE_MAX_TOTAL_BYTES:
                raise HTTPException(status_code=400, detail="Package archive is too large")
            try:
                files[safe_name] = archive.read(info)
            except Exception as exc:
                raise HTTPException(status_code=400, detail=f"Cannot read package file {safe_name}: {exc}") from exc
    return files


def decode_package_text(files: dict[str, bytes], name: str, required: bool = True) -> str:
    data = files.get(name)
    if data is None:
        if required:
            raise HTTPException(status_code=400, detail=f"Missing package file: {name}")
        return ""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"Package file must be UTF-8 text: {name}") from exc


def load_package_metadata(files: dict[str, bytes], prefix: str = "") -> dict:
    json_name = f"{prefix}metadata.json"
    yaml_name = f"{prefix}metadata.yaml"
    yml_name = f"{prefix}metadata.yml"
    try:
        if json_name in files:
            metadata = json.loads(decode_package_text(files, json_name))
        elif yaml_name in files:
            metadata = yaml.safe_load(decode_package_text(files, yaml_name))
        elif yml_name in files:
            metadata = yaml.safe_load(decode_package_text(files, yml_name))
        else:
            raise HTTPException(status_code=400, detail=f"Missing package file: {prefix}metadata.json")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid package metadata: {exc}") from exc
    if not isinstance(metadata, dict):
        raise HTTPException(status_code=400, detail="Package metadata must be an object")
    return metadata


def parse_package_datetime(value: object, field_name: str) -> datetime:
    if value is None:
        raise HTTPException(status_code=400, detail=f"Contest {field_name} is required")
    try:
        return normalize_dt(datetime.fromisoformat(str(value).replace("Z", "+00:00")))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid contest {field_name}") from exc


def task_package_metadata(task: Task, tests: list[TaskTest], package_type: str = "task") -> dict[str, object]:
    return {
        "format": "simple-contester-package",
        "format_version": PACKAGE_FORMAT_VERSION,
        "type": package_type,
        "task": {
            "title": task.title,
            "input_format": task.input_format,
            "output_format": task.output_format,
            "samples": json.loads(task.samples or "[]"),
            "time_limit_ms": task.time_limit_ms,
            "memory_limit_mb": task.memory_limit_mb,
            "points": task.points,
            "partial_scoring": task.partial_scoring,
        },
        "tests": [
            {
                "name": f"{index:03d}",
                "is_sample": test.is_sample,
                "points": test.points,
                "group_name": test.group_name,
            }
            for index, test in enumerate(tests, start=1)
        ],
    }


def write_task_package_files(archive: zipfile.ZipFile, prefix: str, task: Task) -> None:
    tests = sorted(task.tests, key=lambda test: test.id)
    archive.writestr(f"{prefix}metadata.json", json.dumps(task_package_metadata(task, tests), ensure_ascii=False, indent=2))
    archive.writestr(f"{prefix}statement.md", task.statement)
    for index, test in enumerate(tests, start=1):
        name = f"{index:03d}"
        archive.writestr(f"{prefix}tests/{name}.in", test.input_data)
        archive.writestr(f"{prefix}tests/{name}.out", test.output_data)


def create_task_package_zip(task: Task) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        write_task_package_files(archive, "", task)
    return buffer.getvalue()


def create_contest_package_zip(contest: Contest) -> bytes:
    ordered_links = sorted(contest.tasks, key=lambda link: (link.position, link.task_id))
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        metadata = {
            "format": "simple-contester-package",
            "format_version": PACKAGE_FORMAT_VERSION,
            "type": "contest",
            "contest": {
                "title": contest.title,
                "description": contest.description,
                "registration_enabled": contest.registration_enabled,
                "registration_requires_approval": contest.registration_requires_approval,
                "time_mode": contest.time_mode.value if hasattr(contest.time_mode, "value") else contest.time_mode,
                "participation_mode": contest.participation_mode.value if hasattr(contest.participation_mode, "value") else contest.participation_mode,
                "starts_at": contest.starts_at.isoformat(),
                "ends_at": contest.ends_at.isoformat(),
                "individual_duration_minutes": contest.individual_duration_minutes,
                "scoreboard_freeze_at": contest.scoreboard_freeze_at.isoformat() if contest.scoreboard_freeze_at else None,
                "scoreboard_unfrozen": contest.scoreboard_unfrozen,
            },
            "tasks": [
                {"dir": f"tasks/{index:03d}", "position": index - 1}
                for index, _link in enumerate(ordered_links, start=1)
            ],
        }
        archive.writestr("metadata.json", json.dumps(metadata, ensure_ascii=False, indent=2))
        for index, link in enumerate(ordered_links, start=1):
            write_task_package_files(archive, f"tasks/{index:03d}/", link.task)
    return buffer.getvalue()


def create_task_from_package_metadata(db: Session, metadata: dict, statement: str, files: dict[str, bytes], prefix: str = "") -> tuple[Task, int]:
    task_data = metadata.get("task")
    if not isinstance(task_data, dict):
        raise HTTPException(status_code=400, detail=f"Missing task metadata in {prefix or 'package'}")
    title = str(task_data.get("title") or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="Task title is required")
    samples = task_data.get("samples", [])
    if not isinstance(samples, list):
        raise HTTPException(status_code=400, detail="Task samples must be a list")
    try:
        task = Task(
            contest_id=None,
            title=title,
            statement=statement,
            input_format=str(task_data.get("input_format") or ""),
            output_format=str(task_data.get("output_format") or ""),
            samples=json.dumps(samples),
            time_limit_ms=int(task_data.get("time_limit_ms") or 2000),
            memory_limit_mb=int(task_data.get("memory_limit_mb") or 256),
            points=float(task_data.get("points") if task_data.get("points") is not None else 100.0),
            partial_scoring=bool(task_data.get("partial_scoring", False)),
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Invalid task numeric metadata") from exc
    db.add(task)
    db.flush()

    tests_data = metadata.get("tests", [])
    if not isinstance(tests_data, list):
        raise HTTPException(status_code=400, detail="Package tests metadata must be a list")
    created_tests = 0
    for item in tests_data:
        if not isinstance(item, dict):
            raise HTTPException(status_code=400, detail="Each test metadata item must be an object")
        name = str(item.get("name") or "").strip()
        safe_name = safe_archive_member_name(f"{name}.in")
        if safe_name is None or safe_name != f"{name}.in":
            raise HTTPException(status_code=400, detail=f"Unsafe test name: {name}")
        input_data = decode_package_text(files, f"{prefix}tests/{name}.in")
        output_data = decode_package_text(files, f"{prefix}tests/{name}.out")
        points = item.get("points")
        group_name = item.get("group_name")
        try:
            test_points = float(points) if points is not None else None
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=f"Invalid test points for {name}") from exc
        if test_points is not None and test_points < 0:
            raise HTTPException(status_code=400, detail=f"Invalid test points for {name}")
        db.add(
            TaskTest(
                task_id=task.id,
                input_data=input_data,
                output_data=output_data,
                is_sample=bool(item.get("is_sample", False)),
                points=test_points,
                group_name=normalize_optional_string(group_name),
            )
        )
        created_tests += 1
    return task, created_tests


def import_task_package_zip(db: Session, content: bytes) -> PackageImportReport:
    files = read_package_zip(content)
    metadata = load_package_metadata(files)
    if metadata.get("type") not in {"task", None}:
        raise HTTPException(status_code=400, detail="Package is not a task package")
    statement = decode_package_text(files, "statement.md", required=False) or decode_package_text(files, "statement.txt", required=False)
    task, created_tests = create_task_from_package_metadata(db, metadata, statement, files)
    create_task_version_if_changed(db, task)
    db.commit()
    db.refresh(task)
    return PackageImportReport(created_tasks=1, created_tests=created_tests, task_ids=[task.id])


def import_contest_package_zip(db: Session, content: bytes) -> PackageImportReport:
    files = read_package_zip(content)
    metadata = load_package_metadata(files)
    if metadata.get("type") != "contest":
        raise HTTPException(status_code=400, detail="Package is not a contest package")
    contest_data = metadata.get("contest")
    if not isinstance(contest_data, dict):
        raise HTTPException(status_code=400, detail="Missing contest metadata")
    title = str(contest_data.get("title") or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="Contest title is required")
    starts_at = parse_package_datetime(contest_data.get("starts_at"), "starts_at")
    ends_at = parse_package_datetime(contest_data.get("ends_at"), "ends_at")
    scoreboard_freeze_at = None
    if contest_data.get("scoreboard_freeze_at") is not None:
        scoreboard_freeze_at = parse_package_datetime(contest_data.get("scoreboard_freeze_at"), "scoreboard_freeze_at")
    try:
        time_mode = ContestTimeMode(str(contest_data.get("time_mode") or ContestTimeMode.fixed.value))
        participation_mode = ContestParticipationMode(str(contest_data.get("participation_mode") or ContestParticipationMode.individual.value))
        individual_duration_minutes = contest_data.get("individual_duration_minutes")
        if individual_duration_minutes is not None:
            individual_duration_minutes = int(individual_duration_minutes)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Invalid contest mode or duration metadata") from exc
    validate_contest_time_window(starts_at, ends_at, time_mode, individual_duration_minutes, scoreboard_freeze_at)
    contest = Contest(
        title=title,
        description=str(contest_data.get("description") or ""),
        status=ContestStatus.draft,
        is_public=False,
        registration_enabled=bool(contest_data.get("registration_enabled", False)),
        registration_requires_approval=bool(contest_data.get("registration_requires_approval", True)),
        time_mode=time_mode,
        participation_mode=participation_mode,
        starts_at=starts_at,
        ends_at=ends_at,
        individual_duration_minutes=individual_duration_minutes,
        scoreboard_freeze_at=scoreboard_freeze_at,
        scoreboard_unfrozen=bool(contest_data.get("scoreboard_unfrozen", False)),
    )
    db.add(contest)
    db.flush()

    tasks_data = metadata.get("tasks", [])
    if not isinstance(tasks_data, list):
        raise HTTPException(status_code=400, detail="Contest tasks metadata must be a list")
    task_ids: list[int] = []
    created_tests = 0
    for position, item in enumerate(tasks_data):
        if not isinstance(item, dict):
            raise HTTPException(status_code=400, detail="Each contest task item must be an object")
        task_dir = str(item.get("dir") or "").strip().rstrip("/")
        if safe_package_member_name(f"{task_dir}/metadata.json") != f"{task_dir}/metadata.json":
            raise HTTPException(status_code=400, detail=f"Unsafe task directory: {task_dir}")
        prefix = f"{task_dir}/"
        task_metadata = load_package_metadata(files, prefix)
        statement = decode_package_text(files, f"{prefix}statement.md", required=False) or decode_package_text(files, f"{prefix}statement.txt", required=False)
        task, test_count = create_task_from_package_metadata(db, task_metadata, statement, files, prefix)
        db.add(ContestTask(contest_id=contest.id, task_id=task.id, position=int(item.get("position", position))))
        create_task_version_if_changed(db, task)
        task_ids.append(task.id)
        created_tests += test_count

    db.commit()
    db.refresh(contest)
    return PackageImportReport(created_tasks=len(task_ids), created_tests=created_tests, contest_id=contest.id, task_ids=task_ids)


def import_task_tests_zip(db: Session, task_id: int, content: bytes) -> TestArchiveImportReport:
    inputs: dict[str, bytes] = {}
    outputs: dict[str, bytes] = {}
    skipped: list[str] = []
    errors: list[str] = []
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as exc:
        raise HTTPException(status_code=400, detail="Invalid zip archive") from exc

    with archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            safe_name = safe_archive_member_name(info.filename)
            if safe_name is None:
                skipped.append(f"{info.filename}: unsafe path")
                continue
            base, dot, suffix = safe_name.rpartition(".")
            if dot == "" or suffix.lower() not in {"in", "out"} or not base:
                skipped.append(f"{info.filename}: unsupported file name")
                continue
            try:
                data = archive.read(info)
            except Exception as exc:
                errors.append(f"{info.filename}: {exc}")
                continue
            target = inputs if suffix.lower() == "in" else outputs
            target[base] = data

    created = 0
    for base in sorted(set(inputs) & set(outputs)):
        try:
            input_data = inputs[base].decode("utf-8")
            output_data = outputs[base].decode("utf-8")
        except UnicodeDecodeError as exc:
            errors.append(f"{base}: files must be UTF-8 text ({exc})")
            continue
        db.add(TaskTest(task_id=task_id, input_data=input_data, output_data=output_data, is_sample=False))
        created += 1

    unmatched_inputs = sorted(set(inputs) - set(outputs))
    unmatched_outputs = sorted(set(outputs) - set(inputs))
    skipped.extend(f"{base}.in: missing matching .out" for base in unmatched_inputs)
    skipped.extend(f"{base}.out: missing matching .in" for base in unmatched_outputs)
    if created:
        task = get_task_or_404(db, task_id)
        create_task_version_if_changed(db, task)
    db.commit()
    return TestArchiveImportReport(created=created, skipped=skipped, errors=errors)


@app.post("/api/teams", response_model=TeamOut)
def create_team(data: TeamCreate, _: User = Depends(require_admin), db: Session = Depends(get_db)) -> TeamOut:
    team = Team(name=data.name)
    db.add(team)
    db.flush()
    replace_team_members(db, team, data.user_ids)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Team already exists or user id is invalid") from exc
    return to_team_out(get_team_or_404(db, team.id))


@app.get("/api/teams/{team_id}", response_model=TeamOut)
def get_team(team_id: int, _: User = Depends(require_admin), db: Session = Depends(get_db)) -> TeamOut:
    return to_team_out(get_team_or_404(db, team_id))


@app.patch("/api/teams/{team_id}", response_model=TeamOut)
def update_team(team_id: int, data: TeamUpdate, _: User = Depends(require_admin), db: Session = Depends(get_db)) -> TeamOut:
    team = get_team_or_404(db, team_id)
    updates = data.model_dump(exclude_unset=True)
    if "name" in updates:
        team.name = updates["name"]
    if "user_ids" in updates and updates["user_ids"] is not None:
        replace_team_members(db, team, updates["user_ids"])
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Team already exists or user id is invalid") from exc
    return to_team_out(get_team_or_404(db, team_id))


@app.delete("/api/teams/{team_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_team(team_id: int, _: User = Depends(require_admin), db: Session = Depends(get_db)) -> Response:
    team = get_team_or_404(db, team_id)
    db.delete(team)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/api/contests", response_model=list[ContestOut])
def list_contests(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[Contest]:
    stmt = select(Contest).order_by(Contest.starts_at.desc())
    if user.role != UserRole.admin:
        accessible_contests = select(ParticipantContest.contest_id).where(ParticipantContest.user_id == user.id)
        registered_contests = select(ContestRegistration.contest_id).where(
            ContestRegistration.user_id == user.id,
            ContestRegistration.status == ContestRegistrationStatus.approved,
        )
        accessible_team_contests = (
            select(ContestTeam.contest_id)
            .join(TeamMember, TeamMember.team_id == ContestTeam.team_id)
            .where(TeamMember.user_id == user.id)
        )
        registered_team_contests = (
            select(ContestRegistration.contest_id)
            .join(TeamMember, TeamMember.team_id == ContestRegistration.team_id)
            .where(
                TeamMember.user_id == user.id,
                ContestRegistration.status == ContestRegistrationStatus.approved,
            )
        )
        stmt = stmt.where(
            or_(
                Contest.is_public.is_(True),
                Contest.registration_enabled.is_(True),
                Contest.id.in_(accessible_contests),
                Contest.id.in_(registered_contests),
                and_(Contest.participation_mode == ContestParticipationMode.team, Contest.id.in_(accessible_team_contests)),
                and_(Contest.participation_mode == ContestParticipationMode.team, Contest.id.in_(registered_team_contests)),
            )
        )
    return list(db.scalars(stmt))


@app.post("/api/contests", response_model=ContestOut)
def create_contest(data: ContestCreate, _: User = Depends(require_admin), db: Session = Depends(get_db)) -> Contest:
    payload = data.model_dump()
    payload["starts_at"] = normalize_dt(payload["starts_at"])
    payload["ends_at"] = normalize_dt(payload["ends_at"])
    if payload["scoreboard_freeze_at"] is not None:
        payload["scoreboard_freeze_at"] = normalize_dt(payload["scoreboard_freeze_at"])
    validate_contest_time_window(
        payload["starts_at"],
        payload["ends_at"],
        payload["time_mode"],
        payload["individual_duration_minutes"],
        payload["scoreboard_freeze_at"],
    )
    contest = Contest(**payload)
    db.add(contest)
    db.commit()
    db.refresh(contest)
    return contest


@app.post("/api/contests/import-package", response_model=PackageImportReport)
async def import_contest_package(
    file: UploadFile = File(...),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> PackageImportReport:
    filename = (file.filename or "").lower()
    if not filename.endswith(".zip"):
        raise HTTPException(status_code=400, detail="Only .zip packages are supported")
    return import_contest_package_zip(db, await file.read())


@app.get("/api/contests/{contest_id}", response_model=ContestOut)
def get_contest(contest_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> Contest:
    contest = get_contest_or_404(db, contest_id)
    assert_contest_visible_for_registration(db, contest, user)
    return contest


@app.patch("/api/contests/{contest_id}", response_model=ContestOut)
def update_contest(
    contest_id: int,
    data: ContestUpdate,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Contest:
    contest = get_contest_or_404(db, contest_id)
    updates = data.model_dump(exclude_unset=True)
    for key in ("starts_at", "ends_at", "scoreboard_freeze_at"):
        if key in updates and updates[key] is not None:
            updates[key] = normalize_dt(updates[key])
    candidate = {
        "starts_at": updates.get("starts_at", contest.starts_at),
        "ends_at": updates.get("ends_at", contest.ends_at),
        "time_mode": updates.get("time_mode", contest.time_mode),
        "individual_duration_minutes": updates.get(
            "individual_duration_minutes",
            contest.individual_duration_minutes,
        ),
        "scoreboard_freeze_at": updates.get("scoreboard_freeze_at", contest.scoreboard_freeze_at),
    }
    validate_contest_time_window(**candidate)
    for key, value in updates.items():
        setattr(contest, key, value)
    db.commit()
    db.refresh(contest)
    return contest


@app.delete("/api/contests/{contest_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_contest(contest_id: int, _: User = Depends(require_admin), db: Session = Depends(get_db)) -> Response:
    contest = get_contest_or_404(db, contest_id)
    db.delete(contest)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/api/contests/{contest_id}/package")
def export_contest_package(contest_id: int, _: User = Depends(require_admin), db: Session = Depends(get_db)) -> Response:
    contest = db.scalar(
        select(Contest)
        .where(Contest.id == contest_id)
        .options(selectinload(Contest.tasks).selectinload(ContestTask.task).selectinload(Task.tests))
    )
    if contest is None:
        raise HTTPException(status_code=404, detail="Contest not found")
    data = create_contest_package_zip(contest)
    filename = f"contest-{contest.id}-{slug_filename(contest.title, 'contest')}.zip"
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/contests/{contest_id}/start", response_model=ParticipantContestOut)
def start_contest(contest_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> ParticipantContest:
    contest = get_contest_or_404(db, contest_id)
    assert_contest_access(db, contest, user)
    return get_or_start_participant_contest(db, contest, user)


@app.get("/api/contests/{contest_id}/registration", response_model=ContestRegistrationDetailOut | None)
def get_contest_registration(
    contest_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ContestRegistrationDetailOut | None:
    contest = get_contest_or_404(db, contest_id)
    assert_contest_visible_for_registration(db, contest, user)
    registration = get_current_registration(db, contest, user)
    if registration is None:
        return None
    return to_registration_detail_out(db, registration, user)


@app.post("/api/contests/{contest_id}/registration", response_model=ContestRegistrationOut)
def request_contest_registration(
    contest_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ContestRegistration:
    contest = get_contest_or_404(db, contest_id)
    if user.role != UserRole.participant:
        raise HTTPException(status_code=403, detail="Only participants can request contest registration")
    if not contest.registration_enabled:
        raise HTTPException(status_code=403, detail="Contest registration is not enabled")
    try:
        assert_contest_access(db, contest, user)
        already_accessible = True
    except HTTPException:
        already_accessible = False
    if already_accessible:
        raise HTTPException(status_code=409, detail="Contest is already available")
    team_id = resolve_registration_team_id(db, contest, user)
    existing = get_current_registration(db, contest, user)
    if existing is not None:
        return existing
    current = now_utc()
    registration = ContestRegistration(
        contest_id=contest.id,
        user_id=user.id if team_id is None else None,
        team_id=team_id,
        status=ContestRegistrationStatus.pending,
        requested_at=current,
    )
    if not contest.registration_requires_approval:
        registration.status = ContestRegistrationStatus.approved
        registration.decided_at = current
    db.add(registration)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Contest registration already exists") from exc
    db.refresh(registration)
    return registration


@app.get("/api/admin/contest-registrations", response_model=list[ContestRegistrationDetailOut])
def list_admin_contest_registrations(
    status_filter: str | None = Query(default=ContestRegistrationStatus.pending.value, alias="status"),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[ContestRegistrationDetailOut]:
    stmt = select(ContestRegistration).order_by(ContestRegistration.requested_at.desc(), ContestRegistration.id.desc())
    if status_filter not in {None, "", "all"}:
        try:
            parsed_status = ContestRegistrationStatus(status_filter)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="Invalid registration status") from exc
        stmt = stmt.where(ContestRegistration.status == parsed_status)
    registrations = db.scalars(stmt).all()
    return [to_registration_detail_out(db, registration) for registration in registrations]


@app.patch("/api/admin/contest-registrations/{registration_id}", response_model=ContestRegistrationDetailOut)
def decide_admin_contest_registration(
    registration_id: int,
    decision: ContestRegistrationStatus = Query(...),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> ContestRegistrationDetailOut:
    if decision not in {ContestRegistrationStatus.approved, ContestRegistrationStatus.rejected}:
        raise HTTPException(status_code=400, detail="decision must be approved or rejected")
    registration = db.get(ContestRegistration, registration_id)
    if registration is None:
        raise HTTPException(status_code=404, detail="Contest registration not found")
    registration.status = decision
    registration.decided_at = now_utc()
    registration.decided_by_user_id = admin.id
    db.commit()
    db.refresh(registration)
    return to_registration_detail_out(db, registration)


@app.get("/api/contests/{contest_id}/participants", response_model=list[UserOut])
def list_contest_participants(
    contest_id: int,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[User]:
    get_contest_or_404(db, contest_id)
    return list(
        db.scalars(
            select(User)
            .join(ParticipantContest, ParticipantContest.user_id == User.id)
            .where(ParticipantContest.contest_id == contest_id)
            .order_by(User.username)
        )
    )


@app.put("/api/contests/{contest_id}/participants", response_model=list[UserOut])
def set_contest_participants(
    contest_id: int,
    data: ContestParticipantsUpdate,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[User]:
    contest = get_contest_or_404(db, contest_id)
    return replace_contest_participants(db, contest, data.user_ids)


@app.get("/api/contests/{contest_id}/teams", response_model=list[TeamOut])
def list_contest_teams(
    contest_id: int,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[TeamOut]:
    get_contest_or_404(db, contest_id)
    teams = db.scalars(
        select(Team)
        .join(ContestTeam, ContestTeam.team_id == Team.id)
        .where(ContestTeam.contest_id == contest_id)
        .options(selectinload(Team.members))
        .order_by(Team.name)
    ).all()
    return [to_team_out(team) for team in teams]


@app.put("/api/contests/{contest_id}/teams", response_model=list[TeamOut])
def set_contest_teams(
    contest_id: int,
    data: ContestTeamsUpdate,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[TeamOut]:
    contest = get_contest_or_404(db, contest_id)
    return replace_contest_teams(db, contest, data.team_ids)


@app.get("/api/contests/{contest_id}/clarifications", response_model=list[ClarificationOut])
def list_contest_clarifications(
    contest_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[ClarificationOut]:
    contest = get_contest_or_404(db, contest_id)
    assert_contest_access(db, contest, user)
    clarifications = list_clarifications_for_contest(db, contest, user)
    return [to_clarification_out(db, clarification) for clarification in clarifications]


@app.post("/api/contests/{contest_id}/clarifications", response_model=ClarificationOut)
def create_contest_clarification(
    contest_id: int,
    data: ClarificationCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ClarificationOut:
    contest = get_contest_or_404(db, contest_id)
    assert_contest_access(db, contest, user)
    if data.task_id is not None and not task_belongs_to_contest(db, contest_id, data.task_id):
        raise HTTPException(status_code=404, detail="Contest task not found")
    question = data.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Question is required")
    clarification = Clarification(
        contest_id=contest_id,
        task_id=data.task_id,
        author_user_id=user.id,
        question=question,
        status=ClarificationStatus.open,
        visibility=ClarificationVisibility.private,
    )
    db.add(clarification)
    db.commit()
    db.refresh(clarification)
    return to_clarification_out(db, clarification)


@app.get("/api/admin/clarifications", response_model=list[ClarificationOut])
def list_admin_clarifications(
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
    status_filter: ClarificationStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[ClarificationOut]:
    stmt = select(Clarification).order_by(Clarification.created_at.desc(), Clarification.id.desc()).limit(limit)
    if status_filter is not None:
        stmt = stmt.where(Clarification.status == status_filter)
    clarifications = db.scalars(stmt).all()
    return [to_clarification_out(db, clarification) for clarification in clarifications]


@app.patch("/api/admin/clarifications/{clarification_id}", response_model=ClarificationOut)
def update_admin_clarification(
    clarification_id: int,
    data: ClarificationAdminUpdate,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> ClarificationOut:
    clarification = db.get(Clarification, clarification_id)
    if clarification is None:
        raise HTTPException(status_code=404, detail="Clarification not found")
    updates = data.model_dump(exclude_unset=True)
    if "visibility" in updates and updates["visibility"] is not None:
        clarification.visibility = updates["visibility"]
    if "answer" in updates and updates["answer"] is not None:
        answer = updates["answer"].strip()
        if not answer:
            raise HTTPException(status_code=400, detail="Answer cannot be empty")
        clarification.answer = answer
        clarification.answered_by_user_id = admin.id
        clarification.answered_at = now_utc()
        if "status" not in updates or updates["status"] is None:
            clarification.status = ClarificationStatus.answered
    if "status" in updates and updates["status"] is not None:
        if updates["status"] == ClarificationStatus.answered and not clarification.answer:
            raise HTTPException(status_code=400, detail="Answer is required for answered status")
        clarification.status = updates["status"]
        if updates["status"] == ClarificationStatus.answered:
            clarification.answered_by_user_id = clarification.answered_by_user_id or admin.id
            clarification.answered_at = clarification.answered_at or now_utc()
    db.commit()
    db.refresh(clarification)
    return to_clarification_out(db, clarification)


@app.get("/api/contests/{contest_id}/tasks", response_model=list[TaskOut])
def list_tasks(contest_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[TaskOut]:
    contest = get_contest_or_404(db, contest_id)
    assert_contest_access(db, contest, user)
    return list_contest_tasks(db, contest_id)


@app.put("/api/contests/{contest_id}/tasks", response_model=list[TaskOut])
def set_contest_tasks(
    contest_id: int,
    data: ContestTasksUpdate,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[TaskOut]:
    contest = get_contest_or_404(db, contest_id)
    return replace_contest_tasks(db, contest, data.task_ids)


@app.get("/api/tasks", response_model=list[TaskOut])
def list_all_tasks(_: User = Depends(require_admin), db: Session = Depends(get_db)) -> list[TaskOut]:
    tasks = db.scalars(
        select(Task).options(selectinload(Task.tests), selectinload(Task.contests), selectinload(Task.versions)).order_by(Task.id)
    ).all()
    return [to_task_out(task) for task in tasks]


@app.post("/api/tasks/import-package", response_model=PackageImportReport)
async def import_task_package(
    file: UploadFile = File(...),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> PackageImportReport:
    filename = (file.filename or "").lower()
    if not filename.endswith(".zip"):
        raise HTTPException(status_code=400, detail="Only .zip packages are supported")
    return import_task_package_zip(db, await file.read())


@app.post("/api/tasks", response_model=TaskOut)
def create_task(data: TaskCreate, admin: User = Depends(require_admin), db: Session = Depends(get_db)) -> TaskOut:
    task = Task(
        contest_id=data.contest_id,
        title=data.title,
        statement=data.statement,
        input_format=data.input_format,
        output_format=data.output_format,
        samples=json.dumps(data.samples),
        time_limit_ms=data.time_limit_ms,
        memory_limit_mb=data.memory_limit_mb,
        points=data.points,
        partial_scoring=data.partial_scoring,
    )
    db.add(task)
    db.flush()
    attach_task_to_contests(db, task, [*data.contest_ids, *([data.contest_id] if data.contest_id is not None else [])])
    for test in data.tests:
        db.add(
            TaskTest(
                task_id=task.id,
                input_data=test.input_data,
                output_data=test.output_data,
                is_sample=test.is_sample,
                points=test.points,
                group_name=normalize_optional_string(test.group_name),
            )
        )
    create_task_version_if_changed(db, task, admin.id)
    db.commit()
    db.refresh(task)
    task = db.scalar(
        select(Task)
        .where(Task.id == task.id)
        .options(selectinload(Task.tests), selectinload(Task.contests), selectinload(Task.versions))
    )
    return to_task_out(task)


@app.get("/api/tasks/{task_id}", response_model=TaskDetailOut)
def get_task(task_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> TaskDetailOut:
    task = get_task_or_404(db, task_id)
    if user.role != UserRole.admin:
        contest_ids = {link.contest_id for link in task.contests}
        if task.contest_id is not None:
            contest_ids.add(task.contest_id)
        contests = db.scalars(select(Contest).where(Contest.id.in_(contest_ids))).all() if contest_ids else []
        has_access = False
        for contest in contests:
            try:
                assert_contest_access(db, contest, user)
                has_access = True
                break
            except HTTPException:
                continue
        if not has_access:
            raise HTTPException(status_code=403, detail="Task is not available")
    return to_task_detail_out(task, include_tests=user.role == UserRole.admin)


@app.patch("/api/tasks/{task_id}", response_model=TaskOut)
def update_task(task_id: int, data: TaskUpdate, _: User = Depends(require_admin), db: Session = Depends(get_db)) -> TaskOut:
    task = get_task_or_404(db, task_id)
    updates = data.model_dump(exclude_unset=True)
    samples = updates.pop("samples", None)
    for key, value in updates.items():
        setattr(task, key, value)
    if samples is not None:
        task.samples = json.dumps(samples)
    create_task_version_if_changed(db, task, _.id)
    db.commit()
    return to_task_out(get_task_or_404(db, task_id))


@app.get("/api/tasks/{task_id}/versions", response_model=list[TaskVersionOut])
def list_task_versions(task_id: int, _: User = Depends(require_admin), db: Session = Depends(get_db)) -> list[TaskVersionOut]:
    get_task_or_404(db, task_id)
    versions = db.scalars(
        select(TaskVersion).where(TaskVersion.task_id == task_id).order_by(TaskVersion.version_number.desc())
    ).all()
    return [to_task_version_out(version) for version in versions]


@app.get("/api/tasks/{task_id}/versions/{version_id}", response_model=TaskVersionOut)
def get_task_version(
    task_id: int,
    version_id: int,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> TaskVersionOut:
    version = db.scalar(select(TaskVersion).where(TaskVersion.task_id == task_id, TaskVersion.id == version_id))
    if version is None:
        raise HTTPException(status_code=404, detail="Task version not found")
    return to_task_version_out(version)


@app.delete("/api/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_task(task_id: int, _: User = Depends(require_admin), db: Session = Depends(get_db)) -> Response:
    task = get_task_or_404(db, task_id)
    db.delete(task)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/api/tasks/{task_id}/package")
def export_task_package(task_id: int, _: User = Depends(require_admin), db: Session = Depends(get_db)) -> Response:
    task = get_task_or_404(db, task_id)
    data = create_task_package_zip(task)
    filename = f"task-{task.id}-{slug_filename(task.title, 'task')}.zip"
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/tasks/{task_id}/tests", response_model=list[TaskTestOut])
def list_task_tests(task_id: int, _: User = Depends(require_admin), db: Session = Depends(get_db)) -> list[TaskTest]:
    get_task_or_404(db, task_id)
    return list(db.scalars(select(TaskTest).where(TaskTest.task_id == task_id).order_by(TaskTest.id)))


@app.post("/api/tasks/{task_id}/tests", response_model=TaskTestOut)
def create_task_test(
    task_id: int,
    data: TaskTestCreate,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> TaskTest:
    task = get_task_or_404(db, task_id)
    test = TaskTest(
        task_id=task_id,
        input_data=data.input_data,
        output_data=data.output_data,
        is_sample=data.is_sample,
        points=data.points,
        group_name=normalize_optional_string(data.group_name),
    )
    db.add(test)
    create_task_version_if_changed(db, task, _.id)
    db.commit()
    db.refresh(test)
    return test


@app.post("/api/tasks/{task_id}/tests/import-archive", response_model=TestArchiveImportReport)
async def import_task_tests_archive(
    task_id: int,
    file: UploadFile = File(...),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> TestArchiveImportReport:
    get_task_or_404(db, task_id)
    filename = (file.filename or "").lower()
    if not filename.endswith(".zip"):
        raise HTTPException(status_code=400, detail="Only .zip archives are supported")
    return import_task_tests_zip(db, task_id, await file.read())


@app.get("/api/tests/{test_id}", response_model=TaskTestOut)
def get_task_test(test_id: int, _: User = Depends(require_admin), db: Session = Depends(get_db)) -> TaskTest:
    return get_test_or_404(db, test_id)


@app.patch("/api/tests/{test_id}", response_model=TaskTestOut)
def update_task_test(
    test_id: int,
    data: TaskTestUpdate,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> TaskTest:
    test = get_test_or_404(db, test_id)
    for key, value in data.model_dump(exclude_unset=True).items():
        if key == "group_name":
            value = normalize_optional_string(value)
        setattr(test, key, value)
    task = get_task_or_404(db, test.task_id)
    create_task_version_if_changed(db, task, _.id)
    db.commit()
    db.refresh(test)
    return test


@app.delete("/api/tests/{test_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_task_test(test_id: int, _: User = Depends(require_admin), db: Session = Depends(get_db)) -> Response:
    test = get_test_or_404(db, test_id)
    task_id = test.task_id
    db.delete(test)
    task = get_task_or_404(db, task_id)
    create_task_version_if_changed(db, task, _.id)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.post("/api/contests/{contest_id}/tasks/{task_id}/submissions", response_model=SubmissionOut)
def create_submission(
    contest_id: int,
    task_id: int,
    data: SubmissionCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Submission:
    contest = db.get(Contest, contest_id)
    task = db.get(Task, task_id)
    if contest is None or task is None or not task_belongs_to_contest(db, contest_id, task_id):
        raise HTTPException(status_code=404, detail="Contest task not found")
    assert_contest_allows_submission(db, contest, user)
    task = get_task_or_404(db, task_id)
    task_version = max(task.versions, key=lambda version: version.version_number, default=None)
    if task_version is None:
        task_version = create_task_version_if_changed(db, task)
    team_id = resolve_submission_team_id(db, contest, user)
    submission = Submission(
        contest_id=contest_id,
        task_id=task_id,
        task_version_id=task_version.id,
        user_id=user.id,
        team_id=team_id,
        language=data.language,
        source_code=data.source_code,
        verdict=SubmissionVerdict.queued,
    )
    db.add(submission)
    db.commit()
    db.refresh(submission)
    return submission


@app.get("/api/submissions", response_model=list[SubmissionOut])
def list_submissions(
    contest_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[Submission]:
    stmt = select(Submission).order_by(Submission.created_at.desc()).limit(200)
    filters = []
    if contest_id is not None:
        contest = get_contest_or_404(db, contest_id)
        assert_contest_access(db, contest, user)
        filters.append(Submission.contest_id == contest_id)
    if user.role != UserRole.admin:
        team_ids: list[int] = []
        if contest_id is not None:
            contest = get_contest_or_404(db, contest_id)
            if contest.participation_mode == ContestParticipationMode.team:
                team_ids = get_accessible_team_ids_for_user(db, contest_id, user.id)
        ownership_filter = Submission.user_id == user.id
        if team_ids:
            ownership_filter = or_(ownership_filter, Submission.team_id.in_(team_ids))
        filters.append(ownership_filter)
        accessible_contests = select(ParticipantContest.contest_id).where(ParticipantContest.user_id == user.id)
        registered_contests = select(ContestRegistration.contest_id).where(
            ContestRegistration.user_id == user.id,
            ContestRegistration.status == ContestRegistrationStatus.approved,
        )
        accessible_team_contests = (
            select(ContestTeam.contest_id)
            .join(TeamMember, TeamMember.team_id == ContestTeam.team_id)
            .join(Contest, Contest.id == ContestTeam.contest_id)
            .where(TeamMember.user_id == user.id)
            .where(Contest.participation_mode == ContestParticipationMode.team)
        )
        registered_team_contests = (
            select(ContestRegistration.contest_id)
            .join(TeamMember, TeamMember.team_id == ContestRegistration.team_id)
            .join(Contest, Contest.id == ContestRegistration.contest_id)
            .where(TeamMember.user_id == user.id)
            .where(ContestRegistration.status == ContestRegistrationStatus.approved)
            .where(Contest.participation_mode == ContestParticipationMode.team)
        )
        public_contests = select(Contest.id).where(Contest.is_public.is_(True))
        filters.append(
            or_(
                Submission.contest_id.in_(accessible_contests),
                Submission.contest_id.in_(registered_contests),
                Submission.contest_id.in_(accessible_team_contests),
                Submission.contest_id.in_(registered_team_contests),
                Submission.contest_id.in_(public_contests),
            )
        )
    if filters:
        stmt = stmt.where(and_(*filters))
    return list(db.scalars(stmt))


@app.get("/api/submissions/{submission_id}", response_model=SubmissionOut)
def get_submission(submission_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> Submission:
    submission = db.get(Submission, submission_id)
    if submission is None:
        raise HTTPException(status_code=404, detail="Submission not found")
    contest = get_contest_or_404(db, submission.contest_id)
    assert_contest_access(db, contest, user)
    if user.role != UserRole.admin:
        team_ids = get_accessible_team_ids_for_user(db, contest.id, user.id) if contest.participation_mode == ContestParticipationMode.team else []
        if submission.user_id != user.id and (submission.team_id is None or submission.team_id not in team_ids):
            raise HTTPException(status_code=403, detail="Submission is not available")
    return submission


@app.get("/api/admin/submissions/{submission_id}", response_model=SubmissionAdminDetailOut)
def get_admin_submission_detail(
    submission_id: int,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Submission:
    submission = db.scalar(
        select(Submission).where(Submission.id == submission_id).options(selectinload(Submission.results))
    )
    if submission is None:
        raise HTTPException(status_code=404, detail="Submission not found")
    return submission


@app.get("/api/admin/submissions/{submission_id}/test-results", response_model=list[TestResultOut])
def list_submission_test_results(
    submission_id: int,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[TestResultOut]:
    submission = db.scalar(
        select(Submission).where(Submission.id == submission_id).options(selectinload(Submission.results))
    )
    if submission is None:
        raise HTTPException(status_code=404, detail="Submission not found")
    return list(submission.results)


def sse_event(event: str, data: object) -> str:
    return f"event: {event}\ndata: {json.dumps(jsonable_encoder(data), separators=(',', ':'))}\n\n"


def contest_events_payload(db: Session, contest_id: int, user: User) -> dict[str, object]:
    contest = get_contest_or_404(db, contest_id)
    submissions = [
        SubmissionOut.model_validate(submission).model_dump(mode="json")
        for submission in list_submissions(contest_id=contest_id, db=db, user=user)
    ]
    rows = [row.model_dump(mode="json") for row in scoreboard(contest_id=contest_id, db=db, user=user)]
    return {"submissions": submissions, "scoreboard": rows, "scoreboard_frozen": is_scoreboard_frozen_for_user(contest, user)}


def contest_events_fingerprint(db: Session, contest_id: int) -> str:
    contest = get_contest_or_404(db, contest_id)
    stmt = (
        select(
            Submission.id,
            Submission.user_id,
            Submission.team_id,
            Submission.verdict,
            Submission.score,
            Submission.started_at,
            Submission.finished_at,
        )
        .where(Submission.contest_id == contest_id)
        .order_by(Submission.id)
    )
    rows = db.execute(stmt).all()
    return json.dumps(
        [
            [
                row.id,
                row.user_id,
                row.team_id,
                row.verdict.value if hasattr(row.verdict, "value") else row.verdict,
                row.score,
                row.started_at.isoformat() if row.started_at else None,
                row.finished_at.isoformat() if row.finished_at else None,
            ]
            for row in rows
        ]
        + [
            [
                "contest",
                contest.scoreboard_freeze_at.isoformat() if contest.scoreboard_freeze_at else None,
                contest.scoreboard_unfrozen,
            ]
        ],
        separators=(",", ":"),
    )


@app.get("/api/contests/{contest_id}/scoreboard", response_model=list[ScoreboardRow])
def scoreboard(contest_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[ScoreboardRow]:
    contest = get_contest_or_404(db, contest_id)
    assert_contest_access(db, contest, user)
    tasks = db.scalars(
        select(Task)
        .join(ContestTask, ContestTask.task_id == Task.id)
        .where(ContestTask.contest_id == contest_id)
        .order_by(ContestTask.position, Task.id)
    ).all()
    if contest.participation_mode == ContestParticipationMode.team:
        assigned_teams = db.scalars(
            select(Team)
            .join(ContestTeam, ContestTeam.team_id == Team.id)
            .where(ContestTeam.contest_id == contest_id)
        ).all()
        registered_teams = db.scalars(
            select(Team)
            .join(ContestRegistration, ContestRegistration.team_id == Team.id)
            .where(
                ContestRegistration.contest_id == contest_id,
                ContestRegistration.status == ContestRegistrationStatus.approved,
            )
        ).all()
        teams_by_id = {team.id: team for team in [*assigned_teams, *registered_teams]}
        teams = sorted(teams_by_id.values(), key=lambda team: team.name)
        team_ids = [team.id for team in teams]
        submission_stmt = select(Submission).where(Submission.contest_id == contest_id).order_by(Submission.created_at)
        if is_scoreboard_frozen_for_user(contest, user):
            submission_stmt = submission_stmt.where(Submission.created_at < contest.scoreboard_freeze_at)
        submissions = db.scalars(submission_stmt.where(Submission.team_id.in_(team_ids))).all() if team_ids else []

        rows: list[ScoreboardRow] = []
        for team in teams:
            cells: list[ScoreboardCell] = []
            score = 0.0
            penalty = 0
            for task in tasks:
                task_submissions = [s for s in submissions if s.team_id == team.id and s.task_id == task.id]
                accepted = next((s for s in task_submissions if s.verdict == SubmissionVerdict.accepted), None)
                attempts_before_accept = [s for s in task_submissions if accepted is None or s.created_at <= accepted.created_at]
                best_score = max((submission.score for submission in task_submissions), default=0.0)
                solved_at_minutes = None
                score += best_score
                if accepted:
                    solved_at_minutes = max(0, int((accepted.created_at - contest.starts_at).total_seconds() // 60))
                    penalty += solved_at_minutes + 20 * max(0, len(attempts_before_accept) - 1)
                cells.append(
                    ScoreboardCell(
                        task_id=task.id,
                        attempts=len(attempts_before_accept),
                        solved=accepted is not None,
                        solved_at_minutes=solved_at_minutes,
                    )
                )
            rows.append(
                ScoreboardRow(
                    user_id=team.id,
                    username=team.name,
                    display_name=team.name,
                    team_id=team.id,
                    team_name=team.name,
                    score=round(score, 2),
                    penalty=penalty,
                    cells=cells,
                )
            )
        return sorted(rows, key=lambda row: (-row.score, row.penalty, row.team_name or row.username))

    participant_windows = {
        row.user_id: row
        for row in db.scalars(select(ParticipantContest).where(ParticipantContest.contest_id == contest_id)).all()
    }
    registered_user_ids = set(
        db.scalars(
            select(ContestRegistration.user_id).where(
                ContestRegistration.contest_id == contest_id,
                ContestRegistration.user_id.is_not(None),
                ContestRegistration.status == ContestRegistrationStatus.approved,
            )
        ).all()
    )
    participant_ids = set(participant_windows) | registered_user_ids
    user_stmt = select(User).where(User.role == UserRole.participant, User.is_active.is_(True)).order_by(User.username)
    if not contest.is_public:
        user_stmt = user_stmt.where(User.id.in_(participant_ids))
    users = db.scalars(user_stmt).all()
    user_ids = [participant.id for participant in users]
    submission_stmt = select(Submission).where(Submission.contest_id == contest_id).order_by(Submission.created_at)
    if is_scoreboard_frozen_for_user(contest, user):
        submission_stmt = submission_stmt.where(Submission.created_at < contest.scoreboard_freeze_at)
    if user_ids:
        submission_stmt = submission_stmt.where(Submission.user_id.in_(user_ids))
        submissions = db.scalars(submission_stmt).all()
    else:
        submissions = []

    rows: list[ScoreboardRow] = []
    for participant in users:
        participant_window = participant_windows.get(participant.id)
        cells: list[ScoreboardCell] = []
        score = 0.0
        penalty = 0
        for task in tasks:
            task_submissions = [s for s in submissions if s.user_id == participant.id and s.task_id == task.id]
            accepted = next((s for s in task_submissions if s.verdict == SubmissionVerdict.accepted), None)
            attempts_before_accept = [s for s in task_submissions if accepted is None or s.created_at <= accepted.created_at]
            best_score = max((submission.score for submission in task_submissions), default=0.0)
            solved_at_minutes = None
            score += best_score
            if accepted:
                base = participant_window.started_at if participant_window and participant_window.started_at else accepted.created_at
                solved_at_minutes = max(0, int((accepted.created_at - base).total_seconds() // 60))
                penalty += solved_at_minutes + 20 * max(0, len(attempts_before_accept) - 1)
            cells.append(
                ScoreboardCell(
                    task_id=task.id,
                    attempts=len(attempts_before_accept),
                    solved=accepted is not None,
                    solved_at_minutes=solved_at_minutes,
                )
            )
        rows.append(
            ScoreboardRow(
                user_id=participant.id,
                username=participant.username,
                display_name=participant.display_name,
                score=round(score, 2),
                penalty=penalty,
                cells=cells,
            )
        )
    return sorted(rows, key=lambda row: (-row.score, row.penalty, row.username))


@app.get("/api/contests/{contest_id}/live-snapshot")
def contest_live_snapshot(contest_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, object]:
    return contest_events_payload(db, contest_id, user)


@app.get("/api/contests/{contest_id}/events")
async def contest_events(contest_id: int, request: Request, token: str | None = None) -> StreamingResponse:
    with SessionLocal() as db:
        user = get_sse_user(token, db)
        contest = get_contest_or_404(db, contest_id)
        assert_contest_access(db, contest, user)

    async def stream():
        last_fingerprint: str | None = None
        while not await request.is_disconnected():
            with SessionLocal() as db:
                user = get_sse_user(token, db)
                contest = get_contest_or_404(db, contest_id)
                assert_contest_access(db, contest, user)
                fingerprint = contest_events_fingerprint(db, contest_id)
                if fingerprint != last_fingerprint:
                    payload = contest_events_payload(db, contest_id, user)
                    yield sse_event("contest", payload)
                    last_fingerprint = fingerprint
                else:
                    yield ": heartbeat\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
