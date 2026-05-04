from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .models import ContestParticipationMode, ContestStatus, ContestTimeMode, Language, SubmissionVerdict, UserRole


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class LoginIn(BaseModel):
    username: str
    password: str


class UserCreate(BaseModel):
    username: str = Field(min_length=2, max_length=80)
    password: str = Field(min_length=3)
    display_name: str | None = None
    role: UserRole = UserRole.participant


class UserUpdate(BaseModel):
    username: str | None = Field(default=None, min_length=2, max_length=80)
    password: str | None = Field(default=None, min_length=3)
    display_name: str | None = Field(default=None, max_length=160)
    role: UserRole | None = None
    is_active: bool | None = None


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    display_name: str
    role: UserRole
    is_active: bool
    created_at: datetime | None = None


class ImportReport(BaseModel):
    created: int
    skipped: int
    errors: list[str]


class AdminUsersStats(BaseModel):
    total: int
    active: int
    admin: int
    participant: int


class AdminContestsStats(BaseModel):
    total: int
    by_status: dict[ContestStatus, int]
    public: int
    private: int
    individual: int
    team: int


class AdminSubmissionsStats(BaseModel):
    total: int
    by_verdict: dict[SubmissionVerdict, int]
    by_language: dict[Language, int]
    queued: int
    running: int
    recent_1h: int
    recent_24h: int
    accepted_rate: float
    average_score: float


class AdminJudgerStats(BaseModel):
    running_by_judger_id: dict[str, int]
    recent_finished_by_judger_id: dict[str, int]


class AdminSystemStats(BaseModel):
    server_time: datetime
    database_ok: bool
    app_version: str = "unknown"
    build: str = "unknown"


class AdminStatsOut(BaseModel):
    users: AdminUsersStats
    teams_total: int
    contests: AdminContestsStats
    tasks_total: int
    tests_total: int
    submissions: AdminSubmissionsStats
    judgers: AdminJudgerStats
    system: AdminSystemStats


class TeamCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    user_ids: list[int] = Field(default_factory=list)


class TeamUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=160)
    user_ids: list[int] | None = None


class TeamOut(BaseModel):
    id: int
    name: str
    member_ids: list[int]
    created_at: datetime | None = None


class ContestTeamsUpdate(BaseModel):
    team_ids: list[int] = Field(default_factory=list)


class ContestParticipantsUpdate(BaseModel):
    user_ids: list[int] = Field(default_factory=list)


class ContestTasksUpdate(BaseModel):
    task_ids: list[int] = Field(default_factory=list)


class ContestCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = ""
    status: ContestStatus = ContestStatus.draft
    is_public: bool = False
    time_mode: ContestTimeMode = ContestTimeMode.fixed
    participation_mode: ContestParticipationMode = ContestParticipationMode.individual
    starts_at: datetime
    ends_at: datetime
    individual_duration_minutes: int | None = None


class ContestUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    status: ContestStatus | None = None
    is_public: bool | None = None
    time_mode: ContestTimeMode | None = None
    participation_mode: ContestParticipationMode | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    individual_duration_minutes: int | None = Field(default=None, gt=0)


class ContestOut(ContestCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime | None = None


class ParticipantContestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    contest_id: int
    user_id: int
    started_at: datetime | None
    deadline_at: datetime | None


class TaskTestCreate(BaseModel):
    input_data: str
    output_data: str
    is_sample: bool = False


class TaskTestUpdate(BaseModel):
    input_data: str | None = None
    output_data: str | None = None
    is_sample: bool | None = None


class TaskTestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: int
    input_data: str
    output_data: str
    is_sample: bool


class TaskTestPublicOut(BaseModel):
    id: int
    is_sample: bool


class TaskCreate(BaseModel):
    contest_id: int | None = None
    contest_ids: list[int] = Field(default_factory=list)
    title: str = Field(min_length=1, max_length=200)
    statement: str
    input_format: str = ""
    output_format: str = ""
    samples: list[dict[str, Any]] = Field(default_factory=list)
    time_limit_ms: int = 2000
    memory_limit_mb: int = 256
    points: float = 100.0
    partial_scoring: bool = False
    tests: list[TaskTestCreate] = Field(default_factory=list)


class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    statement: str | None = None
    input_format: str | None = None
    output_format: str | None = None
    samples: list[dict[str, Any]] | None = None
    time_limit_ms: int | None = Field(default=None, gt=0)
    memory_limit_mb: int | None = Field(default=None, gt=0)
    points: float | None = Field(default=None, ge=0)
    partial_scoring: bool | None = None


class TaskOut(BaseModel):
    id: int
    contest_id: int | None = None
    contest_ids: list[int] = Field(default_factory=list)
    title: str
    statement: str
    input_format: str
    output_format: str
    samples: list[dict[str, Any]]
    time_limit_ms: int
    memory_limit_mb: int
    points: float
    partial_scoring: bool
    test_count: int


class TaskDetailOut(TaskOut):
    tests: list[TaskTestPublicOut] | None = None


class TestArchiveImportReport(BaseModel):
    created: int
    skipped: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class PackageImportReport(BaseModel):
    created_tasks: int
    created_tests: int
    contest_id: int | None = None
    task_ids: list[int] = Field(default_factory=list)


class SubmissionCreate(BaseModel):
    language: Language
    source_code: str = Field(min_length=1)


class SubmissionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    contest_id: int
    task_id: int
    user_id: int
    team_id: int | None = None
    language: Language
    verdict: SubmissionVerdict
    score: float
    compile_output: str
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class TestResultOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    submission_id: int
    task_test_id: int
    verdict: SubmissionVerdict
    time_ms: int
    output: str
    error: str


class SubmissionAdminDetailOut(SubmissionOut):
    source_code: str
    judger_id: str | None
    results: list[TestResultOut] = Field(default_factory=list)


class ScoreboardCell(BaseModel):
    task_id: int
    attempts: int
    solved: bool
    solved_at_minutes: int | None


class ScoreboardRow(BaseModel):
    user_id: int
    username: str
    display_name: str
    team_id: int | None = None
    team_name: str | None = None
    score: float
    penalty: int
    cells: list[ScoreboardCell]
