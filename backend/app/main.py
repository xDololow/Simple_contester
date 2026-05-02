import csv
import io
import json
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import PurePosixPath

import yaml
from fastapi import Depends, FastAPI, File, HTTPException, Response, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import and_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from .auth import create_access_token, get_current_user, hash_password, require_admin, verify_password
from .config import settings
from .database import Base, SessionLocal, engine, get_db
from .models import (
    Contest,
    ContestTeam,
    ContestTask,
    ContestTimeMode,
    Language,
    ParticipantContest,
    Submission,
    SubmissionVerdict,
    Task,
    TaskTest,
    Team,
    TeamMember,
    User,
    UserRole,
)
from .schemas import (
    ContestCreate,
    ContestOut,
    ContestTeamsUpdate,
    ContestTasksUpdate,
    ContestUpdate,
    ImportReport,
    LoginIn,
    ParticipantContestOut,
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


def validate_contest_time_window(
    starts_at: datetime,
    ends_at: datetime,
    time_mode: ContestTimeMode,
    individual_duration_minutes: int | None,
) -> None:
    if ends_at <= starts_at:
        raise HTTPException(status_code=400, detail="ends_at must be after starts_at")
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
    Base.metadata.create_all(bind=engine)
    ensure_language_enum_values()
    ensure_float_score_columns()
    ensure_partial_scoring_column()
    with SessionLocal() as db:
        ensure_admin(db)
        ensure_legacy_task_links(db)


def to_task_out(task: Task) -> TaskOut:
    contest_ids = sorted(link.contest_id for link in task.contests)
    return TaskOut(
        id=task.id,
        contest_id=task.contest_id,
        contest_ids=contest_ids,
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
    task = db.scalar(select(Task).where(Task.id == task_id).options(selectinload(Task.tests), selectinload(Task.contests)))
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


def get_or_start_participant_contest(db: Session, contest: Contest, user: User) -> ParticipantContest:
    existing = db.scalar(
        select(ParticipantContest).where(
            ParticipantContest.contest_id == contest.id,
            ParticipantContest.user_id == user.id,
        )
    )
    if existing:
        return existing
    started_at = now_utc()
    if contest.time_mode == ContestTimeMode.individual:
        if contest.individual_duration_minutes is None:
            raise HTTPException(status_code=400, detail="Individual duration is not configured")
        deadline = min(contest.ends_at, started_at + timedelta(minutes=contest.individual_duration_minutes))
    else:
        deadline = contest.ends_at
    participant = ParticipantContest(
        contest_id=contest.id,
        user_id=user.id,
        started_at=started_at,
        deadline_at=deadline,
    )
    db.add(participant)
    db.commit()
    db.refresh(participant)
    return participant


def assert_contest_allows_submission(db: Session, contest: Contest, user: User) -> None:
    current = now_utc()
    if current < contest.starts_at or current > contest.ends_at:
        raise HTTPException(status_code=400, detail="Contest is outside the available window")
    if contest.time_mode == ContestTimeMode.individual and contest.individual_duration_minutes is None:
        raise HTTPException(status_code=400, detail="Individual duration is not configured")
    participant = get_or_start_participant_contest(db, contest, user)
    if current > participant.deadline_at:
        raise HTTPException(status_code=400, detail="Individual contest deadline has passed")


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


def list_contest_tasks(db: Session, contest_id: int) -> list[TaskOut]:
    tasks = db.scalars(
        select(Task)
        .join(ContestTask, ContestTask.task_id == Task.id)
        .where(ContestTask.contest_id == contest_id)
        .options(selectinload(Task.tests), selectinload(Task.contests))
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
def list_contests(db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> list[Contest]:
    return list(db.scalars(select(Contest).order_by(Contest.starts_at.desc())))


@app.post("/api/contests", response_model=ContestOut)
def create_contest(data: ContestCreate, _: User = Depends(require_admin), db: Session = Depends(get_db)) -> Contest:
    payload = data.model_dump()
    payload["starts_at"] = normalize_dt(payload["starts_at"])
    payload["ends_at"] = normalize_dt(payload["ends_at"])
    validate_contest_time_window(
        payload["starts_at"],
        payload["ends_at"],
        payload["time_mode"],
        payload["individual_duration_minutes"],
    )
    contest = Contest(**payload)
    db.add(contest)
    db.commit()
    db.refresh(contest)
    return contest


@app.get("/api/contests/{contest_id}", response_model=ContestOut)
def get_contest(contest_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> Contest:
    return get_contest_or_404(db, contest_id)


@app.patch("/api/contests/{contest_id}", response_model=ContestOut)
def update_contest(
    contest_id: int,
    data: ContestUpdate,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Contest:
    contest = get_contest_or_404(db, contest_id)
    updates = data.model_dump(exclude_unset=True)
    for key in ("starts_at", "ends_at"):
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


@app.get("/api/contests/{contest_id}/start", response_model=ParticipantContestOut)
def start_contest(contest_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> ParticipantContest:
    contest = get_contest_or_404(db, contest_id)
    return get_or_start_participant_contest(db, contest, user)


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


@app.get("/api/contests/{contest_id}/tasks", response_model=list[TaskOut])
def list_tasks(contest_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> list[TaskOut]:
    get_contest_or_404(db, contest_id)
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
    tasks = db.scalars(select(Task).options(selectinload(Task.tests), selectinload(Task.contests)).order_by(Task.id)).all()
    return [to_task_out(task) for task in tasks]


@app.post("/api/tasks", response_model=TaskOut)
def create_task(data: TaskCreate, _: User = Depends(require_admin), db: Session = Depends(get_db)) -> TaskOut:
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
        db.add(TaskTest(task_id=task.id, input_data=test.input_data, output_data=test.output_data, is_sample=test.is_sample))
    db.commit()
    db.refresh(task)
    task = db.scalar(select(Task).where(Task.id == task.id).options(selectinload(Task.tests), selectinload(Task.contests)))
    return to_task_out(task)


@app.get("/api/tasks/{task_id}", response_model=TaskDetailOut)
def get_task(task_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> TaskDetailOut:
    task = get_task_or_404(db, task_id)
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
    db.commit()
    return to_task_out(get_task_or_404(db, task_id))


@app.delete("/api/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_task(task_id: int, _: User = Depends(require_admin), db: Session = Depends(get_db)) -> Response:
    task = get_task_or_404(db, task_id)
    db.delete(task)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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
    get_task_or_404(db, task_id)
    test = TaskTest(task_id=task_id, input_data=data.input_data, output_data=data.output_data, is_sample=data.is_sample)
    db.add(test)
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
        setattr(test, key, value)
    db.commit()
    db.refresh(test)
    return test


@app.delete("/api/tests/{test_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_task_test(test_id: int, _: User = Depends(require_admin), db: Session = Depends(get_db)) -> Response:
    test = get_test_or_404(db, test_id)
    db.delete(test)
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
    submission = Submission(
        contest_id=contest_id,
        task_id=task_id,
        user_id=user.id,
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
    if contest_id:
        filters.append(Submission.contest_id == contest_id)
    if user.role != UserRole.admin:
        filters.append(Submission.user_id == user.id)
    if filters:
        stmt = stmt.where(and_(*filters))
    return list(db.scalars(stmt))


@app.get("/api/submissions/{submission_id}", response_model=SubmissionOut)
def get_submission(submission_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> Submission:
    submission = db.get(Submission, submission_id)
    if submission is None:
        raise HTTPException(status_code=404, detail="Submission not found")
    if user.role != UserRole.admin and submission.user_id != user.id:
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


@app.get("/api/contests/{contest_id}/scoreboard", response_model=list[ScoreboardRow])
def scoreboard(contest_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> list[ScoreboardRow]:
    tasks = db.scalars(
        select(Task)
        .join(ContestTask, ContestTask.task_id == Task.id)
        .where(ContestTask.contest_id == contest_id)
        .order_by(ContestTask.position, Task.id)
    ).all()
    users = db.scalars(select(User).where(User.role == UserRole.participant, User.is_active.is_(True)).order_by(User.username)).all()
    participants = {
        row.user_id: row
        for row in db.scalars(select(ParticipantContest).where(ParticipantContest.contest_id == contest_id)).all()
    }
    submissions = db.scalars(select(Submission).where(Submission.contest_id == contest_id).order_by(Submission.created_at)).all()

    rows: list[ScoreboardRow] = []
    for participant in users:
        participant_window = participants.get(participant.id)
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
                base = participant_window.started_at if participant_window else accepted.created_at
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
