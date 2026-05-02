export type Role = "admin" | "participant";
export type ContestStatus = "draft" | "scheduled" | "running" | "finished" | "archived";
export type TimeMode = "fixed" | "individual";
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

export type User = {
  id: number;
  username: string;
  display_name: string;
  role: Role;
  is_active: boolean;
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
  time_mode: TimeMode;
  starts_at: string;
  ends_at: string;
  individual_duration_minutes: number | null;
  created_at?: string | null;
};

export type Task = {
  id: number;
  contest_id?: number | null;
  contest_ids: number[];
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

export type TaskTest = {
  id: number;
  task_id: number;
  input_data: string;
  output_data: string;
  is_sample: boolean;
};

export type Submission = {
  id: number;
  contest_id: number;
  task_id: number;
  user_id: number;
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
  score: number;
  penalty: number;
  cells: Array<{ task_id: number; attempts: number; solved: boolean; solved_at_minutes: number | null }>;
};

export type ContestLiveEvent = {
  submissions: Submission[];
  scoreboard: ScoreboardRow[];
};

export type ImportReport = {
  created: number;
  skipped: number;
  errors: string[];
};

export type TestArchiveImportReport = {
  created: number;
  skipped: string[];
  errors: string[];
};

export type Flash = { kind: "ok" | "error"; text: string };
