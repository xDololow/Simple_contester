from datetime import datetime
from enum import Enum

from sqlalchemy import Boolean, DateTime, Enum as SAEnum, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utc_now() -> datetime:
    return datetime.utcnow()


class UserRole(str, Enum):
    admin = "admin"
    participant = "participant"


class ContestStatus(str, Enum):
    draft = "draft"
    scheduled = "scheduled"
    running = "running"
    finished = "finished"
    archived = "archived"


class ContestTimeMode(str, Enum):
    fixed = "fixed"
    individual = "individual"


class ContestParticipationMode(str, Enum):
    individual = "individual"
    team = "team"


class ScoringMode(str, Enum):
    ioi = "ioi"
    ecoo = "ecoo"
    icpc = "icpc"
    atcoder = "atcoder"


class ScoreboardVisibility(str, Enum):
    public = "public"
    anonymous = "anonymous"
    hidden = "hidden"


class ContestRegistrationStatus(str, Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class SubmissionVerdict(str, Enum):
    queued = "Queued"
    running = "Running"
    accepted = "Accepted"
    wrong_answer = "Wrong Answer"
    time_limit = "Time Limit"
    memory_limit = "Memory Limit"
    runtime_error = "Runtime Error"
    compilation_error = "Compilation Error"
    internal_error = "Internal Error"


class Language(str, Enum):
    python = "python"
    java = "java"
    javascript = "javascript"
    typescript = "typescript"
    c11 = "c11"
    cpp17 = "cpp17"
    cpp20 = "cpp20"
    csharp = "csharp"
    object_pascal = "object_pascal"
    fortran = "fortran"
    go = "go"
    lua = "lua"


class JudgerStatus(str, Enum):
    starting = "starting"
    idle = "idle"
    polling = "polling"
    claiming = "claiming"
    compiling = "compiling"
    running = "running"
    reporting = "reporting"
    stopping = "stopping"
    offline = "offline"


class ClarificationStatus(str, Enum):
    open = "open"
    answered = "answered"
    closed = "closed"


class ClarificationVisibility(str, Enum):
    private = "private"
    broadcast = "broadcast"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(160))
    role: Mapped[UserRole] = mapped_column(SAEnum(UserRole), default=UserRole.participant)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    teams: Mapped[list["TeamMember"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    members: Mapped[list["TeamMember"]] = relationship(back_populates="team", cascade="all, delete-orphan")
    contests: Mapped[list["ContestTeam"]] = relationship(back_populates="team", cascade="all, delete-orphan")


class TeamMember(Base):
    __tablename__ = "team_members"
    __table_args__ = (UniqueConstraint("team_id", "user_id", name="uq_team_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))

    team: Mapped[Team] = relationship(back_populates="members")
    user: Mapped[User] = relationship(back_populates="teams")


class Contest(Base):
    __tablename__ = "contests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[ContestStatus] = mapped_column(SAEnum(ContestStatus), default=ContestStatus.draft)
    is_public: Mapped[bool] = mapped_column(Boolean, default=False)
    registration_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    registration_requires_approval: Mapped[bool] = mapped_column(Boolean, default=True)
    time_mode: Mapped[ContestTimeMode] = mapped_column(SAEnum(ContestTimeMode), default=ContestTimeMode.fixed)
    participation_mode: Mapped[ContestParticipationMode] = mapped_column(
        SAEnum(ContestParticipationMode),
        default=ContestParticipationMode.individual,
    )
    scoring_mode: Mapped[str] = mapped_column(String(20), default=ScoringMode.ioi.value)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    individual_duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    scoreboard_freeze_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scoreboard_unfrozen: Mapped[bool] = mapped_column(Boolean, default=False)
    scoreboard_visibility: Mapped[str] = mapped_column(String(20), default=ScoreboardVisibility.public.value)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    tasks: Mapped[list["ContestTask"]] = relationship(back_populates="contest", cascade="all, delete-orphan")
    teams: Mapped[list["ContestTeam"]] = relationship(back_populates="contest", cascade="all, delete-orphan")
    registrations: Mapped[list["ContestRegistration"]] = relationship(back_populates="contest", cascade="all, delete-orphan")


class ContestTeam(Base):
    __tablename__ = "contest_teams"
    __table_args__ = (UniqueConstraint("contest_id", "team_id", name="uq_contest_team"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contest_id: Mapped[int] = mapped_column(ForeignKey("contests.id", ondelete="CASCADE"), index=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), index=True)

    contest: Mapped[Contest] = relationship(back_populates="teams")
    team: Mapped[Team] = relationship(back_populates="contests")


class ParticipantContest(Base):
    __tablename__ = "participant_contests"
    __table_args__ = (UniqueConstraint("contest_id", "user_id", name="uq_participant_contest"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contest_id: Mapped[int] = mapped_column(ForeignKey("contests.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ContestRegistration(Base):
    __tablename__ = "contest_registrations"
    __table_args__ = (
        UniqueConstraint("contest_id", "user_id", name="uq_contest_registration_user"),
        UniqueConstraint("contest_id", "team_id", name="uq_contest_registration_team"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contest_id: Mapped[int] = mapped_column(ForeignKey("contests.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), nullable=True, index=True)
    status: Mapped[ContestRegistrationStatus] = mapped_column(
        SAEnum(ContestRegistrationStatus),
        default=ContestRegistrationStatus.pending,
        index=True,
    )
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    contest: Mapped[Contest] = relationship(back_populates="registrations")


class ContestTask(Base):
    __tablename__ = "contest_tasks"
    __table_args__ = (UniqueConstraint("contest_id", "task_id", name="uq_contest_task"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contest_id: Mapped[int] = mapped_column(ForeignKey("contests.id", ondelete="CASCADE"), index=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)

    contest: Mapped[Contest] = relationship(back_populates="tasks")
    task: Mapped["Task"] = relationship(back_populates="contests")


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contest_id: Mapped[int | None] = mapped_column(ForeignKey("contests.id", ondelete="SET NULL"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(200))
    statement: Mapped[str] = mapped_column(Text)
    input_format: Mapped[str] = mapped_column(Text, default="")
    output_format: Mapped[str] = mapped_column(Text, default="")
    samples: Mapped[str] = mapped_column(Text, default="[]")
    time_limit_ms: Mapped[int] = mapped_column(Integer, default=2000)
    memory_limit_mb: Mapped[int] = mapped_column(Integer, default=256)
    points: Mapped[float] = mapped_column(Float, default=100.0)
    partial_scoring: Mapped[bool] = mapped_column(Boolean, default=False)

    contests: Mapped[list[ContestTask]] = relationship(back_populates="task", cascade="all, delete-orphan")
    tests: Mapped[list["TaskTest"]] = relationship(back_populates="task", cascade="all, delete-orphan")
    versions: Mapped[list["TaskVersion"]] = relationship(back_populates="task", cascade="all, delete-orphan")


class TaskVersion(Base):
    __tablename__ = "task_versions"
    __table_args__ = (UniqueConstraint("task_id", "version_number", name="uq_task_version_number"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    version_number: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(200))
    statement: Mapped[str] = mapped_column(Text)
    input_format: Mapped[str] = mapped_column(Text, default="")
    output_format: Mapped[str] = mapped_column(Text, default="")
    samples: Mapped[str] = mapped_column(Text, default="[]")
    time_limit_ms: Mapped[int] = mapped_column(Integer, default=2000)
    memory_limit_mb: Mapped[int] = mapped_column(Integer, default=256)
    points: Mapped[float] = mapped_column(Float, default=100.0)
    partial_scoring: Mapped[bool] = mapped_column(Boolean, default=False)
    tests_snapshot: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    task: Mapped[Task] = relationship(back_populates="versions")


class TaskTest(Base):
    __tablename__ = "task_tests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    input_data: Mapped[str] = mapped_column(Text)
    output_data: Mapped[str] = mapped_column(Text)
    is_sample: Mapped[bool] = mapped_column(Boolean, default=False)
    points: Mapped[float | None] = mapped_column(Float, nullable=True)
    group_name: Mapped[str | None] = mapped_column(String(120), nullable=True)

    task: Mapped[Task] = relationship(back_populates="tests")


class Submission(Base):
    __tablename__ = "submissions"
    __table_args__ = (
        Index("ix_submissions_verdict_claim_expires_at", "verdict", "claim_expires_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contest_id: Mapped[int] = mapped_column(ForeignKey("contests.id", ondelete="CASCADE"), index=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    task_version_id: Mapped[int | None] = mapped_column(ForeignKey("task_versions.id", ondelete="SET NULL"), nullable=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id", ondelete="SET NULL"), nullable=True, index=True)
    language: Mapped[Language] = mapped_column(SAEnum(Language))
    source_code: Mapped[str] = mapped_column(Text)
    verdict: Mapped[SubmissionVerdict] = mapped_column(SAEnum(SubmissionVerdict), default=SubmissionVerdict.queued, index=True)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    compile_output: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    judger_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    claim_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    claim_token: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    attempt_number: Mapped[int] = mapped_column(Integer, default=0)

    results: Mapped[list["TestResult"]] = relationship(back_populates="submission", cascade="all, delete-orphan")


class Clarification(Base):
    __tablename__ = "clarifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contest_id: Mapped[int] = mapped_column(ForeignKey("contests.id", ondelete="CASCADE"), index=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True, index=True)
    author_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[ClarificationStatus] = mapped_column(
        SAEnum(ClarificationStatus),
        default=ClarificationStatus.open,
        index=True,
    )
    visibility: Mapped[ClarificationVisibility] = mapped_column(
        SAEnum(ClarificationVisibility),
        default=ClarificationVisibility.private,
        index=True,
    )
    answered_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Judger(Base):
    __tablename__ = "judgers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    judger_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    hostname: Mapped[str] = mapped_column(String(255), default="")
    version: Mapped[str] = mapped_column(String(80), default="unknown")
    supported_languages: Mapped[str] = mapped_column(Text, default="[]")
    sandbox_mode: Mapped[str] = mapped_column(String(80), default="subprocess")
    capabilities: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String(32), default=JudgerStatus.starting.value, index=True)
    current_submission_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    last_state_change_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class JudgerEvent(Base):
    __tablename__ = "judger_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    judger_id: Mapped[str] = mapped_column(String(120), index=True)
    event_type: Mapped[str] = mapped_column(String(80))
    submission_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)


class TestResult(Base):
    __tablename__ = "test_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    submission_id: Mapped[int] = mapped_column(ForeignKey("submissions.id", ondelete="CASCADE"), index=True)
    task_test_id: Mapped[int] = mapped_column(ForeignKey("task_tests.id", ondelete="CASCADE"))
    verdict: Mapped[SubmissionVerdict] = mapped_column(SAEnum(SubmissionVerdict))
    time_ms: Mapped[int] = mapped_column(Integer, default=0)
    output: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str] = mapped_column(Text, default="")

    submission: Mapped[Submission] = relationship(back_populates="results")
