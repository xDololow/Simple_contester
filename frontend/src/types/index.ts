export type Role = "admin" | "participant";
export type ContestStatus = "draft" | "scheduled" | "running" | "finished" | "archived";
export type TimeMode = "fixed" | "individual";
export type ParticipationMode = "individual" | "team";
export type ScoreboardVisibility = "public" | "anonymous" | "hidden";
export type ContestRegistrationStatus = "pending" | "approved" | "rejected";
export type ClarificationStatus = "open" | "answered" | "closed";
export type ClarificationVisibility = "private" | "broadcast";
export type Language =
  | "python"
  | "java"
  | "javascript"
  | "typescript"
  | "c11"
  | "cpp17"
  | "cpp20"
  | "csharp"
  | "object_pascal"
  | "fortran"
  | "go"
  | "lua";

export type ApiClient = <T>(path: string, init?: RequestInit) => Promise<T>;

export type AppConfig = {
  site_timezone: string;
};

export type User = {
  id: number;
  username: string;
  display_name: string;
  role: Role;
  is_active: boolean;
  timezone?: string | null;
  created_at?: string | null;
};

export type Team = {
  id: number;
  name: string;
  member_ids: number[];
  created_at?: string | null;
};

export type Contest = {
  id: number;
  title: string;
  description: string;
  status: ContestStatus;
  is_public: boolean;
  registration_enabled: boolean;
  registration_requires_approval: boolean;
  time_mode: TimeMode;
  participation_mode: ParticipationMode;
  starts_at: string;
  ends_at: string;
  individual_duration_minutes: number | null;
  scoreboard_freeze_at: string | null;
  scoreboard_unfrozen: boolean;
  scoreboard_visibility: ScoreboardVisibility;
  created_at?: string | null;
};

export type ContestRegistration = {
  id: number;
  contest_id: number;
  user_id: number | null;
  team_id: number | null;
  status: ContestRegistrationStatus;
  requested_at: string;
  decided_at: string | null;
  decided_by_user_id: number | null;
  contest_title?: string;
  username?: string | null;
  user_display_name?: string | null;
  team_name?: string | null;
  decided_by_username?: string | null;
  can_access?: boolean;
};

export type ParticipantContestTime = {
  id: number;
  contest_id: number;
  user_id: number;
  username: string;
  display_name: string;
  started_at: string | null;
  deadline_at: string | null;
  duration_seconds: number | null;
  spent_seconds: number | null;
  remaining_seconds: number | null;
};

export type ParticipantContest = {
  id: number;
  contest_id: number;
  user_id: number;
  started_at: string | null;
  deadline_at: string | null;
};

export type Task = {
  id: number;
  contest_id?: number | null;
  contest_ids: number[];
  current_version_number: number | null;
  title: string;
  statement: string;
  input_format: string;
  output_format: string;
  samples: Array<Record<string, unknown>>;
  time_limit_ms: number;
  memory_limit_mb: number;
  points: number;
  partial_scoring: boolean;
  test_count: number;
  tests?: Array<{ id: number; is_sample: boolean }> | null;
};

export type TaskVersion = {
  id: number;
  task_id: number;
  version_number: number;
  title: string;
  statement: string;
  input_format: string;
  output_format: string;
  samples: Array<Record<string, unknown>>;
  time_limit_ms: number;
  memory_limit_mb: number;
  points: number;
  partial_scoring: boolean;
  tests_snapshot: Array<Record<string, unknown>>;
  created_at: string;
  created_by_user_id: number | null;
};

export type TaskTest = {
  id: number;
  task_id: number;
  input_data: string;
  output_data: string;
  is_sample: boolean;
  points: number | null;
  group_name: string | null;
};

export type Submission = {
  id: number;
  contest_id: number;
  task_id: number;
  task_version_id?: number | null;
  user_id: number;
  team_id?: number | null;
  language: Language;
  verdict: string;
  score: number;
  compile_output: string;
  created_at: string;
  started_at?: string | null;
  finished_at?: string | null;
};

export type TestResult = {
  id: number;
  submission_id: number;
  task_test_id: number;
  verdict: string;
  time_ms: number;
  output: string;
  error: string;
};

export type SubmissionDetail = Submission & {
  source_code: string;
  judger_id: string | null;
  results: TestResult[];
};

export type ScoreboardRow = {
  user_id: number;
  username: string;
  display_name: string;
  team_id?: number | null;
  team_name?: string | null;
  score: number;
  penalty: number;
  cells: Array<{ task_id: number; attempts: number; solved: boolean; solved_at_minutes: number | null }>;
};

export type ContestLiveEvent = {
  submissions: Submission[];
  scoreboard: ScoreboardRow[];
  scoreboard_frozen?: boolean;
  scoreboard_visibility?: ScoreboardVisibility;
};

export type Clarification = {
  id: number;
  contest_id: number;
  task_id: number | null;
  task_title: string | null;
  author_user_id: number;
  author_username: string;
  author_display_name: string;
  question: string;
  answer: string | null;
  status: ClarificationStatus;
  visibility: ClarificationVisibility;
  answered_by_user_id: number | null;
  answered_by_username: string | null;
  created_at: string;
  answered_at: string | null;
};

export type ImportReport = {
  created: number;
  skipped: number;
  errors: string[];
  team_id?: number | null;
  team_members_added?: number;
};

export type TestArchiveImportReport = {
  created: number;
  skipped: string[];
  errors: string[];
};

export type PackageImportReport = {
  created_tasks: number;
  created_tests: number;
  contest_id: number | null;
  task_ids: number[];
};

export type Flash = { kind: "ok" | "error"; text: string };

export type AdminStats = {
  users: {
    total: number;
    active: number;
    admin: number;
    participant: number;
  };
  teams_total: number;
  contests: {
    total: number;
    by_status: Record<ContestStatus, number>;
    public: number;
    private: number;
    individual: number;
    team: number;
  };
  tasks_total: number;
  tests_total: number;
  submissions: {
    total: number;
    by_verdict: Record<string, number>;
    by_language: Record<Language, number>;
    queued: number;
    running: number;
    recent_1h: number;
    recent_24h: number;
    queue_depth: number;
    running_count: number;
    oldest_queued_age_seconds: number | null;
    stale_running_count: number;
    expired_running_leases: number;
    finished_1h: number;
    finished_24h: number;
    average_judging_time_seconds: number | null;
    p95_judging_time_seconds: number | null;
    internal_error_count: number;
    internal_error_rate: number;
    accepted_rate: number;
    average_score: number;
  };
  judgers: {
    running_by_judger_id: Record<string, number>;
    recent_finished_by_judger_id: Record<string, number>;
    active: number;
    stale: number;
    offline: number;
  };
  system: {
    server_time: string;
    database_ok: boolean;
    app_version: string;
    build: string;
  };
};

export type JudgerHealth = "active" | "stale" | "offline";

export type JudgerWorker = {
  id: number;
  judger_id: string;
  hostname: string;
  version: string;
  supported_languages: string[];
  sandbox_mode: string;
  capabilities: Record<string, unknown>;
  status: string;
  health: JudgerHealth;
  current_submission_id: number | null;
  registered_at: string;
  last_seen_at: string;
  last_state_change_at: string;
  enabled: boolean;
  last_error: string | null;
};

export type JudgerEvent = {
  id: number;
  judger_id: string;
  event_type: string;
  submission_id: number | null;
  message: string | null;
  payload: unknown | null;
  created_at: string;
};
