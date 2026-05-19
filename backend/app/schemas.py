from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_serializer

from .models import (
    ClarificationStatus,
    ClarificationVisibility,
    ContestParticipationMode,
    ContestRegistrationStatus,
    ContestStatus,
    ContestTimeMode,
    JudgerStatus,
    Language,
    ScoringMode,
    ScoreboardVisibility,
    SubmissionVerdict,
    UserRole,
)


def encode_datetime_utc(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    else:
        value = value.astimezone(timezone.utc)
    return value.isoformat().replace("+00:00", "Z")


class ApiModel(BaseModel):
    model_config = ConfigDict(json_encoders={datetime: encode_datetime_utc})

    @model_serializer(mode="wrap", when_used="json")
    def serialize_model(self, handler: Any) -> Any:
        return encode_datetimes(handler(self))


def encode_datetimes(value: Any) -> Any:
    if isinstance(value, datetime):
        return encode_datetime_utc(value)
    if isinstance(value, list):
        return [encode_datetimes(item) for item in value]
    if isinstance(value, tuple):
        return tuple(encode_datetimes(item) for item in value)
    if isinstance(value, dict):
        return {key: encode_datetimes(item) for key, item in value.items()}
    return value


class TokenOut(ApiModel):
    access_token: str
    token_type: str = "bearer"


class AppConfigOut(ApiModel):
    site_timezone: str


class LoginIn(ApiModel):
    username: str
    password: str


class PasswordChangeIn(ApiModel):
    old_password: str = Field(min_length=1)
    new_password: str = Field(min_length=3)


class UserPreferencesUpdate(ApiModel):
    timezone: str | None = Field(default=None, max_length=64)


class UserCreate(ApiModel):
    username: str = Field(min_length=2, max_length=80)
    password: str = Field(min_length=3)
    display_name: str | None = None
    role: UserRole = UserRole.participant
    timezone: str | None = Field(default=None, max_length=64)


class UserUpdate(ApiModel):
    username: str | None = Field(default=None, min_length=2, max_length=80)
    password: str | None = Field(default=None, min_length=3)
    display_name: str | None = Field(default=None, max_length=160)
    role: UserRole | None = None
    is_active: bool | None = None
    timezone: str | None = Field(default=None, max_length=64)


class UserOut(ApiModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    display_name: str
    role: UserRole
    is_active: bool
    timezone: str | None = None
    created_at: datetime | None = None


class ImportReport(ApiModel):
    created: int
    skipped: int
    errors: list[str]
    team_id: int | None = None
    team_members_added: int = 0


class AdminUsersStats(ApiModel):
    total: int
    active: int
    admin: int
    participant: int


class AdminContestsStats(ApiModel):
    total: int
    by_status: dict[ContestStatus, int]
    public: int
    private: int
    individual: int
    team: int


class AdminSubmissionsStats(ApiModel):
    total: int
    by_verdict: dict[SubmissionVerdict, int]
    by_language: dict[Language, int]
    queued: int
    running: int
    recent_1h: int
    recent_24h: int
    queue_depth: int
    running_count: int
    oldest_queued_age_seconds: int | None = None
    stale_running_count: int
    expired_running_leases: int
    finished_1h: int
    finished_24h: int
    average_judging_time_seconds: float | None = None
    p95_judging_time_seconds: float | None = None
    internal_error_count: int
    internal_error_rate: float
    accepted_rate: float
    average_score: float


class AdminJudgerStats(ApiModel):
    running_by_judger_id: dict[str, int]
    recent_finished_by_judger_id: dict[str, int]
    active: int = 0
    stale: int = 0
    offline: int = 0


class AdminSystemStats(ApiModel):
    server_time: datetime
    database_ok: bool
    app_version: str = "unknown"
    build: str = "unknown"


class AdminStatsOut(ApiModel):
    users: AdminUsersStats
    teams_total: int
    contests: AdminContestsStats
    tasks_total: int
    tests_total: int
    submissions: AdminSubmissionsStats
    judgers: AdminJudgerStats
    system: AdminSystemStats


class AdminJudgerOut(ApiModel):
    id: int
    judger_id: str
    hostname: str
    version: str
    supported_languages: list[str]
    sandbox_mode: str
    capabilities: dict[str, Any]
    status: JudgerStatus | str
    health: str
    current_submission_id: int | None = None
    registered_at: datetime
    last_seen_at: datetime
    last_state_change_at: datetime
    enabled: bool
    last_error: str | None = None


class AdminJudgerEventOut(ApiModel):
    id: int
    judger_id: str
    event_type: str
    submission_id: int | None = None
    message: str | None = None
    payload: Any | None = None
    created_at: datetime


class TeamCreate(ApiModel):
    name: str = Field(min_length=2, max_length=160)
    user_ids: list[int] = Field(default_factory=list)


class TeamUpdate(ApiModel):
    name: str | None = Field(default=None, min_length=2, max_length=160)
    user_ids: list[int] | None = None


class TeamOut(ApiModel):
    id: int
    name: str
    member_ids: list[int]
    created_at: datetime | None = None


class ContestTeamsUpdate(ApiModel):
    team_ids: list[int] = Field(default_factory=list)


class ContestParticipantsUpdate(ApiModel):
    user_ids: list[int] = Field(default_factory=list)


class ContestTasksUpdate(ApiModel):
    task_ids: list[int] = Field(default_factory=list)


class ContestCreate(ApiModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = ""
    status: ContestStatus = ContestStatus.draft
    is_public: bool = False
    registration_enabled: bool = False
    registration_requires_approval: bool = True
    time_mode: ContestTimeMode = ContestTimeMode.fixed
    participation_mode: ContestParticipationMode = ContestParticipationMode.individual
    scoring_mode: ScoringMode = ScoringMode.ioi
    starts_at: datetime
    ends_at: datetime
    individual_duration_minutes: int | None = None
    scoreboard_freeze_at: datetime | None = None
    scoreboard_unfrozen: bool = False
    scoreboard_visibility: ScoreboardVisibility = ScoreboardVisibility.public


class ContestUpdate(ApiModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    status: ContestStatus | None = None
    is_public: bool | None = None
    registration_enabled: bool | None = None
    registration_requires_approval: bool | None = None
    time_mode: ContestTimeMode | None = None
    participation_mode: ContestParticipationMode | None = None
    scoring_mode: ScoringMode | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    individual_duration_minutes: int | None = Field(default=None, gt=0)
    scoreboard_freeze_at: datetime | None = None
    scoreboard_unfrozen: bool | None = None
    scoreboard_visibility: ScoreboardVisibility | None = None


class ContestOut(ContestCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime | None = None


class ParticipantContestOut(ApiModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    contest_id: int
    user_id: int
    started_at: datetime | None
    deadline_at: datetime | None


class AdminParticipantContestTimeOut(ApiModel):
    id: int
    contest_id: int
    user_id: int
    username: str
    display_name: str
    started_at: datetime | None
    deadline_at: datetime | None
    duration_seconds: int | None
    spent_seconds: int | None
    remaining_seconds: int | None


class ParticipantContestTimeUpdate(ApiModel):
    started_at: datetime | None = None
    deadline_at: datetime | None = None
    duration_seconds: int | None = Field(default=None, gt=0)
    delta_seconds: int | None = None
    reset: bool = False


class ContestRegistrationOut(ApiModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    contest_id: int
    user_id: int | None
    team_id: int | None
    status: ContestRegistrationStatus
    requested_at: datetime
    decided_at: datetime | None = None
    decided_by_user_id: int | None = None


class ContestRegistrationDetailOut(ContestRegistrationOut):
    contest_title: str
    username: str | None = None
    user_display_name: str | None = None
    team_name: str | None = None
    decided_by_username: str | None = None
    can_access: bool = False


class TaskTestCreate(ApiModel):
    input_data: str
    output_data: str
    is_sample: bool = False
    points: float | None = Field(default=None, ge=0)
    group_name: str | None = Field(default=None, max_length=120)


class TaskTestUpdate(ApiModel):
    input_data: str | None = None
    output_data: str | None = None
    is_sample: bool | None = None
    points: float | None = Field(default=None, ge=0)
    group_name: str | None = Field(default=None, max_length=120)


class TaskTestOut(ApiModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: int
    input_data: str
    output_data: str
    is_sample: bool
    points: float | None = None
    group_name: str | None = None


class TaskTestPublicOut(ApiModel):
    id: int
    is_sample: bool


class TaskCreate(ApiModel):
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


class TaskUpdate(ApiModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    statement: str | None = None
    input_format: str | None = None
    output_format: str | None = None
    samples: list[dict[str, Any]] | None = None
    time_limit_ms: int | None = Field(default=None, gt=0)
    memory_limit_mb: int | None = Field(default=None, gt=0)
    points: float | None = Field(default=None, ge=0)
    partial_scoring: bool | None = None


class TaskOut(ApiModel):
    id: int
    contest_id: int | None = None
    contest_ids: list[int] = Field(default_factory=list)
    current_version_number: int | None = None
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


class TaskVersionOut(ApiModel):
    id: int
    task_id: int
    version_number: int
    title: str
    statement: str
    input_format: str
    output_format: str
    samples: list[dict[str, Any]]
    time_limit_ms: int
    memory_limit_mb: int
    points: float
    partial_scoring: bool
    tests_snapshot: list[dict[str, Any]]
    created_at: datetime
    created_by_user_id: int | None = None


class TestArchiveImportReport(ApiModel):
    created: int
    skipped: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class PackageImportReport(ApiModel):
    created_tasks: int
    created_tests: int
    contest_id: int | None = None
    task_ids: list[int] = Field(default_factory=list)


class ClarificationCreate(ApiModel):
    task_id: int | None = None
    question: str = Field(min_length=1, max_length=10000)


class ClarificationAdminUpdate(ApiModel):
    answer: str | None = Field(default=None, max_length=10000)
    status: ClarificationStatus | None = None
    visibility: ClarificationVisibility | None = None


class ClarificationOut(ApiModel):
    id: int
    contest_id: int
    task_id: int | None = None
    task_title: str | None = None
    author_user_id: int
    author_username: str
    author_display_name: str
    question: str
    answer: str | None = None
    status: ClarificationStatus
    visibility: ClarificationVisibility
    answered_by_user_id: int | None = None
    answered_by_username: str | None = None
    created_at: datetime
    answered_at: datetime | None = None


class SubmissionCreate(ApiModel):
    language: Language
    source_code: str = Field(min_length=1)


class SubmissionOut(ApiModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    contest_id: int
    task_id: int
    task_version_id: int | None = None
    user_id: int
    team_id: int | None = None
    language: Language
    verdict: SubmissionVerdict
    score: float
    compile_output: str
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    claimed_at: datetime | None = None
    claim_expires_at: datetime | None = None
    attempt_number: int = 0


class TestResultOut(ApiModel):
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


class ScoreboardCell(ApiModel):
    task_id: int
    attempts: int
    solved: bool
    solved_at_minutes: int | None


class ScoreboardRow(ApiModel):
    user_id: int
    username: str
    display_name: str
    team_id: int | None = None
    team_name: str | None = None
    score: float
    penalty: int
    cells: list[ScoreboardCell]
