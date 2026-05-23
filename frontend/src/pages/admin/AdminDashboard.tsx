import React, { useCallback, useEffect, useMemo, useState } from "react";
import { API_BASE } from "../../api/client";
import { FlashMessage, Header, SubmissionDetailView } from "../../components/shared";
import { useI18n } from "../../i18n";
import type { AdminStats, ApiClient, Clarification, ClarificationStatus, ClarificationVisibility, Contest, ContestRegistration, ContestStatus, Flash, ImportReport, JudgerEvent, JudgerWorker, PackageImportReport, ParticipantContestTime, ParticipationMode, Role, ScoringMode, ScoreboardVisibility, Submission, SubmissionDetail, Task, TaskTest, Team, TestArchiveImportReport, TimeMode, User } from "../../types";
import { emptyFlash, errorText, formatDate, formatScore, fromLocalInputValue, toLocalInputValue, verdictClass } from "../../utils/format";

type AdminTab = "status" | "users" | "import" | "teams" | "contests" | "tasks" | "packages" | "tests" | "submissions" | "clarifications";
const ADMIN_NAV_STORAGE_KEY = "simple-contester-admin-nav-hidden";

export function AdminDashboard({ api, token, reloadContests, siteTimezone }: { api: ApiClient; token: string; reloadContests: () => void; siteTimezone: string }) {
  const { t } = useI18n();
  const [tab, setTab] = useState<AdminTab>("status");
  const [navHidden, setNavHidden] = useState(() => localStorage.getItem(ADMIN_NAV_STORAGE_KEY) === "1");

  useEffect(() => {
    localStorage.setItem(ADMIN_NAV_STORAGE_KEY, navHidden ? "1" : "0");
  }, [navHidden]);

  return (
    <div className={navHidden ? "admin-shell admin-nav-hidden" : "admin-shell"}>
      {!navHidden && <AdminNav activeTab={tab} onChange={setTab} onHide={() => setNavHidden(true)} />}
      <div className="admin-content">
        {navHidden && <button type="button" className="admin-nav-toggle" onClick={() => setNavHidden(false)}>{t("layout.showAdminMenu")}</button>}
        {tab === "status" && <StatusAdmin api={api} siteTimezone={siteTimezone} />}
        {tab === "users" && <UsersAdmin api={api} siteTimezone={siteTimezone} />}
        {tab === "import" && <ImportUsersAdmin api={api} token={token} />}
        {tab === "teams" && <TeamsAdmin api={api} siteTimezone={siteTimezone} />}
        {tab === "contests" && <ContestsAdmin api={api} onChanged={reloadContests} siteTimezone={siteTimezone} />}
        {tab === "tasks" && <TasksAdmin api={api} />}
        {tab === "packages" && <PackagesAdmin api={api} token={token} onChanged={reloadContests} />}
        {tab === "tests" && <TestsAdmin api={api} />}
        {tab === "submissions" && <SubmissionsAdmin api={api} siteTimezone={siteTimezone} />}
        {tab === "clarifications" && <ClarificationsAdmin api={api} siteTimezone={siteTimezone} />}
      </div>
    </div>
  );
}

function AdminNav({ activeTab, onChange, onHide }: { activeTab: AdminTab; onChange: (tab: AdminTab) => void; onHide: () => void }) {
  const { t } = useI18n();
  const groups: Array<{ label: string; tabs: AdminTab[] }> = [
    { label: t("admin.nav.monitoring"), tabs: ["status", "submissions"] },
    { label: t("admin.nav.accounts"), tabs: ["users", "import", "teams"] },
    { label: t("admin.nav.content"), tabs: ["contests", "tasks", "packages", "tests"] },
    { label: t("admin.nav.support"), tabs: ["clarifications"] }
  ];
  return (
    <nav className="admin-nav" aria-label={t("nav.adminWorkspace")}>
      <button type="button" className="small" onClick={onHide}>{t("layout.hideAdminMenu")}</button>
      {groups.map((group) => (
        <div className="admin-nav-group" key={group.label}>
          <span>{group.label}</span>
          <div className="tabs">
            {group.tabs.map((id) => (
              <button key={id} className={activeTab === id ? "active" : ""} onClick={() => onChange(id)} type="button">
                {t(`tab.${id}`)}
              </button>
            ))}
          </div>
        </div>
      ))}
    </nav>
  );
}

function matchesSearch(values: Array<string | number | boolean | null | undefined>, query: string) {
  const normalized = query.trim().toLowerCase();
  if (!normalized) return true;
  return values.some((value) => String(value ?? "").toLowerCase().includes(normalized));
}

function TableToolbar({
  query,
  onQueryChange,
  total,
  filtered,
  placeholder
}: {
  query: string;
  onQueryChange: (query: string) => void;
  total: number;
  filtered: number;
  placeholder: string;
}) {
  const { t } = useI18n();
  return (
    <div className="table-toolbar">
      <label className="table-search">
        {t("common.search")}
        <input value={query} onChange={(event) => onQueryChange(event.target.value)} placeholder={placeholder} />
      </label>
      <span className="muted">{t("common.showing", { filtered, total })}</span>
      {query && <button type="button" className="small" onClick={() => onQueryChange("")}>{t("common.clear")}</button>}
    </div>
  );
}

type ContestAccessMode = "public" | "registration" | "private";

type ContestAccessFields = {
  is_public: boolean;
  registration_enabled: boolean;
  registration_requires_approval: boolean;
  participant_ids: number[];
  team_ids: number[];
};

type ContestFormState = ContestAccessFields & {
  title: string;
  description: string;
  status: ContestStatus;
  time_mode: TimeMode;
  participation_mode: ParticipationMode;
  scoring_mode: ScoringMode;
  starts_at: string;
  ends_at: string;
  individual_duration_minutes: string;
  scoreboard_freeze_at: string;
  scoreboard_unfrozen: boolean;
  scoreboard_visibility: ScoreboardVisibility;
  task_ids: number[];
};

function accessModeOf(value: Pick<ContestAccessFields, "is_public" | "registration_enabled">): ContestAccessMode {
  if (value.is_public) return "public";
  if (value.registration_enabled) return "registration";
  return "private";
}

function applyContestAccessMode<T extends ContestAccessFields>(current: T, mode: ContestAccessMode): T {
  return {
    ...current,
    is_public: mode === "public",
    registration_enabled: mode === "registration",
    registration_requires_approval: mode === "registration",
    participant_ids: mode === "private" ? current.participant_ids : [],
    team_ids: mode === "private" ? current.team_ids : []
  };
}

function formatDurationClock(totalSeconds: number | null | undefined) {
  if (totalSeconds == null || !Number.isFinite(totalSeconds)) return "-";
  const normalized = Math.max(0, Math.floor(totalSeconds));
  const hours = Math.floor(normalized / 3600);
  const minutes = Math.floor((normalized % 3600) / 60);
  const seconds = normalized % 60;
  return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

function durationMinutesToClock(minutes: number | null | undefined) {
  if (minutes == null) return "";
  const normalized = Math.max(0, Math.floor(minutes));
  const hours = Math.floor(normalized / 60);
  const remainingMinutes = normalized % 60;
  return `${String(hours).padStart(2, "0")}:${String(remainingMinutes).padStart(2, "0")}`;
}

function parseDurationClock(value: string) {
  const match = /^(\d+):([0-5]\d)(?::([0-5]\d))?$/.exec(value.trim());
  if (!match) return null;
  const [, rawHours, rawMinutes, rawSeconds = "0"] = match;
  const seconds = Number(rawHours) * 3600 + Number(rawMinutes) * 60 + Number(rawSeconds);
  return seconds > 0 ? seconds : null;
}

function durationClockToMinutes(value: string) {
  const seconds = parseDurationClock(value);
  return seconds == null ? null : Math.ceil(seconds / 60);
}

function createEmptyContestForm(siteTimezone: string): ContestFormState {
  const now = new Date();
  const later = new Date(Date.now() + 3 * 60 * 60_000);
  return {
    title: "",
    description: "",
    status: "draft",
    is_public: false,
    registration_enabled: false,
    registration_requires_approval: false,
    time_mode: "fixed",
    participation_mode: "individual",
    scoring_mode: "ioi",
    starts_at: toLocalInputValue(now.toISOString(), siteTimezone),
    ends_at: toLocalInputValue(later.toISOString(), siteTimezone),
    individual_duration_minutes: "03:00",
    scoreboard_freeze_at: "",
    scoreboard_unfrozen: false,
    scoreboard_visibility: "public",
    task_ids: [],
    participant_ids: [],
    team_ids: []
  };
}

function contestToForm(
  contest: Contest,
  taskIds: number[],
  participantIds: number[],
  teamIds: number[],
  siteTimezone: string
): ContestFormState {
  return {
    title: contest.title,
    description: contest.description,
    status: contest.status,
    is_public: contest.is_public,
    registration_enabled: contest.registration_enabled,
    registration_requires_approval: contest.registration_requires_approval,
    time_mode: contest.time_mode,
    participation_mode: contest.participation_mode,
    scoring_mode: contest.scoring_mode ?? "ioi",
    starts_at: toLocalInputValue(contest.starts_at, siteTimezone),
    ends_at: toLocalInputValue(contest.ends_at, siteTimezone),
    individual_duration_minutes: durationMinutesToClock(contest.individual_duration_minutes),
    scoreboard_freeze_at: contest.scoreboard_freeze_at ? toLocalInputValue(contest.scoreboard_freeze_at, siteTimezone) : "",
    scoreboard_unfrozen: contest.scoreboard_unfrozen,
    scoreboard_visibility: contest.scoreboard_visibility ?? "public",
    task_ids: taskIds,
    participant_ids: participantIds,
    team_ids: teamIds
  };
}

function PaginationControls({
  page,
  totalPages,
  pageSize,
  total,
  onPageChange,
  onPageSizeChange
}: {
  page: number;
  totalPages: number;
  pageSize: number;
  total: number;
  onPageChange: (page: number) => void;
  onPageSizeChange: (pageSize: number) => void;
}) {
  const { t } = useI18n();
  const firstItem = total ? (page - 1) * pageSize + 1 : 0;
  const lastItem = Math.min(total, page * pageSize);
  return (
    <div className="pagination-controls">
      <div className="row-actions">
        <button type="button" className="small" disabled={page <= 1} onClick={() => onPageChange(1)}>{t("pagination.first")}</button>
        <button type="button" className="small" disabled={page <= 1} onClick={() => onPageChange(page - 1)}>{t("pagination.previous")}</button>
        <span className="muted">{t("pagination.page", { page, total: totalPages })}</span>
        <button type="button" className="small" disabled={page >= totalPages} onClick={() => onPageChange(page + 1)}>{t("pagination.next")}</button>
        <button type="button" className="small" disabled={page >= totalPages} onClick={() => onPageChange(totalPages)}>{t("pagination.last")}</button>
      </div>
      <span className="muted">{t("pagination.range", { first: firstItem, last: lastItem, total })}</span>
      <label className="page-size">
        {t("pagination.pageSize")}
        <select value={pageSize} onChange={(event) => onPageSizeChange(Number(event.target.value))}>
          {[10, 25, 50, 100].map((value) => <option key={value} value={value}>{value}</option>)}
        </select>
      </label>
    </div>
  );
}

function StatusAdmin({ api, siteTimezone }: { api: ApiClient; siteTimezone: string }) {
  const { t } = useI18n();
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [judgers, setJudgers] = useState<JudgerWorker[]>([]);
  const [judgerEvents, setJudgerEvents] = useState<JudgerEvent[]>([]);
  const [flash, setFlash] = useState<Flash>(emptyFlash);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [nextStats, nextJudgers, nextJudgerEvents] = await Promise.all([
        api<AdminStats>("/api/admin/stats"),
        api<JudgerWorker[]>("/api/admin/judgers"),
        api<JudgerEvent[]>("/api/admin/judger-events?limit=20")
      ]);
      setStats(nextStats);
      setJudgers(nextJudgers);
      setJudgerEvents(nextJudgerEvents);
      setFlash(emptyFlash);
    } catch (error) {
      setFlash({ kind: "error", text: errorText(error) });
    } finally {
      setLoading(false);
    }
  }, [api]);

  useEffect(() => {
    load();
    const interval = window.setInterval(() => load().catch(console.error), 12000);
    return () => window.clearInterval(interval);
  }, [load]);

  const verdictRows = stats ? Object.entries(stats.submissions.by_verdict).filter(([, count]) => count > 0) : [];
  const languageRows = stats ? Object.entries(stats.submissions.by_language).filter(([, count]) => count > 0) : [];
  const runningJudgers = stats ? Object.entries(stats.judgers.running_by_judger_id) : [];
  const finishedJudgers = stats ? Object.entries(stats.judgers.recent_finished_by_judger_id) : [];
  const maxThroughput = stats ? Math.max(stats.submissions.finished_1h, stats.submissions.finished_24h, 1) : 1;
  const maxQueue = stats ? Math.max(stats.submissions.queue_depth, stats.submissions.running_count, stats.submissions.stale_running_count, 1) : 1;

  return (
    <section className="panel">
      <Header title={t("tab.status")} subtitle={stats ? t("status.lastUpdated", { time: formatDate(stats.system.server_time, siteTimezone) }) : t("status.loading")} />
      <div className="toolbar">
        <button onClick={load} disabled={loading}>{loading ? t("status.refreshing") : t("common.refresh")}</button>
        {stats ? (
          <span className={stats.system.database_ok ? "pill ok" : "pill warn"}>{stats.system.database_ok ? t("status.dbOk") : t("status.dbDown")}</span>
        ) : (
          <span className="pill">{t("status.dbUnknown")}</span>
        )}
        <span className="muted">{t("status.autoRefresh")}</span>
      </div>
      <FlashMessage flash={flash} />
      {stats && (
        <div className="status-grid">
          <div className="stat"><strong>{stats.users.total}</strong><span>{t("status.usersTotal")}</span></div>
          <div className="stat"><strong>{stats.users.active}</strong><span>{t("status.usersActive")}</span></div>
          <div className="stat"><strong>{stats.users.admin}</strong><span>{t("role.admin")}</span></div>
          <div className="stat"><strong>{stats.users.participant}</strong><span>{t("role.participant")}</span></div>
          <div className="stat"><strong>{stats.teams_total}</strong><span>{t("tab.teams")}</span></div>
          <div className="stat"><strong>{stats.contests.total}</strong><span>{t("tab.contests")}</span></div>
          <div className="stat"><strong>{stats.tasks_total}</strong><span>{t("tab.tasks")}</span></div>
          <div className="stat"><strong>{stats.tests_total}</strong><span>{t("tab.tests")}</span></div>
          <div className="stat"><strong>{stats.submissions.total}</strong><span>{t("tab.submissions")}</span></div>
          <div className="stat"><strong>{stats.submissions.queue_depth}</strong><span>{t("status.queueDepth")}</span></div>
          <div className="stat"><strong>{stats.submissions.running_count}</strong><span>{t("status.runningCount")}</span></div>
          <div className="stat"><strong>{stats.submissions.accepted_rate}%</strong><span>{t("status.acceptedRate")}</span></div>
          <div className="stat"><strong>{formatScore(stats.submissions.average_score)}</strong><span>{t("status.averageScore")}</span></div>
          <div className="stat"><strong>{stats.submissions.finished_1h}</strong><span>{t("status.finished1h")}</span></div>
          <div className="stat"><strong>{stats.submissions.finished_24h}</strong><span>{t("status.finished24h")}</span></div>
          <div className="stat"><strong>{stats.system.app_version}</strong><span>{t("status.appVersion")}</span></div>

          <div className="status-card">
            <h3>{t("status.queue")}</h3>
            <MetricBar label={t("status.queueDepth")} value={stats.submissions.queue_depth} max={maxQueue} />
            <MetricBar label={t("status.runningCount")} value={stats.submissions.running_count} max={maxQueue} />
            <MetricBar label={t("status.staleRunning")} value={stats.submissions.stale_running_count} max={maxQueue} tone={stats.submissions.stale_running_count ? "warn" : "ok"} />
            <div className="kv compact-kv status-kv">
              <span>{t("status.oldestQueued")}</span><strong>{formatDuration(stats.submissions.oldest_queued_age_seconds)}</strong>
            </div>
          </div>

          <div className="status-card">
            <h3>{t("status.throughput")}</h3>
            <MetricBar label={t("status.finished1h")} value={stats.submissions.finished_1h} max={maxThroughput} />
            <MetricBar label={t("status.finished24h")} value={stats.submissions.finished_24h} max={maxThroughput} />
            <div className="kv compact-kv status-kv">
              <span>{t("status.created1h")}</span><strong>{stats.submissions.recent_1h}</strong>
              <span>{t("status.created24h")}</span><strong>{stats.submissions.recent_24h}</strong>
            </div>
          </div>

          <div className="status-card">
            <h3>{t("status.latency")}</h3>
            <div className="latency-row"><span>{t("status.avgJudging")}</span><strong>{formatDuration(stats.submissions.average_judging_time_seconds)}</strong></div>
            <div className="latency-row"><span>{t("status.p95Judging")}</span><strong>{formatDuration(stats.submissions.p95_judging_time_seconds)}</strong></div>
          </div>

          <div className="status-card">
            <h3>{t("status.problems")}</h3>
            <div className="kv compact-kv status-kv">
              <span>{t("status.internalErrors")}</span><strong>{stats.submissions.internal_error_count}</strong>
              <span>{t("status.internalErrorRate")}</span><strong>{stats.submissions.internal_error_rate}%</strong>
              <span>{t("status.staleRunning")}</span><strong>{stats.submissions.stale_running_count}</strong>
            </div>
          </div>

          <div className="status-card">
            <h3>{t("status.contests")}</h3>
            <div className="kv compact-kv">
              <span>{t("contest.public")}</span><strong>{stats.contests.public}</strong>
              <span>{t("contest.private")}</span><strong>{stats.contests.private}</strong>
              <span>{t("common.individual")}</span><strong>{stats.contests.individual}</strong>
              <span>{t("common.team")}</span><strong>{stats.contests.team}</strong>
              {Object.entries(stats.contests.by_status).map(([status, count]) => (
                <React.Fragment key={status}><span>{t(`status.${status}`)}</span><strong>{count}</strong></React.Fragment>
              ))}
            </div>
          </div>

          <StatusTable title={t("status.byVerdict")} rows={verdictRows.map(([verdict, count]) => [t(`verdict.${verdict}`), count])} empty={t("common.empty")} />
          <StatusTable title={t("status.byLanguage")} rows={languageRows} empty={t("common.empty")} />
          {(stats.judgers.active > 0 || stats.judgers.stale > 0 || stats.judgers.offline > 0) && (
            <StatusTable title={t("status.judgerRegistry")} rows={[[t("status.judgerActive"), stats.judgers.active], [t("status.judgerStale"), stats.judgers.stale], [t("status.judgerOffline"), stats.judgers.offline]]} empty={t("common.empty")} />
          )}
          <JudgerWorkersTable judgers={judgers} siteTimezone={siteTimezone} />
          <JudgerEventsTable events={judgerEvents} siteTimezone={siteTimezone} />
          <StatusTable title={t("status.runningJudgers")} rows={runningJudgers} empty={t("common.empty")} />
          <StatusTable title={t("status.finishedJudgers24h")} rows={finishedJudgers} empty={t("common.empty")} />
        </div>
      )}
    </section>
  );
}

function JudgerWorkersTable({ judgers, siteTimezone }: { judgers: JudgerWorker[]; siteTimezone: string }) {
  const { t } = useI18n();
  return (
    <div className="status-card">
      <h3>{t("status.judgerWorkers")}</h3>
      <table>
        <thead>
          <tr>
            <th>{t("table.judger")}</th>
            <th>{t("table.health")}</th>
            <th>{t("table.status")}</th>
            <th>{t("table.currentSubmission")}</th>
            <th>{t("table.lastSeen")}</th>
            <th>{t("table.languages")}</th>
          </tr>
        </thead>
        <tbody>
          {judgers.length ? judgers.map((judger) => (
            <tr key={judger.id}>
              <td>{judger.judger_id}</td>
              <td><span className={judger.health === "active" ? "pill ok" : "pill warn"}>{t(`judger.health.${judger.health}`)}</span></td>
              <td>{t(`judger.status.${judger.status}`)}</td>
              <td>{judger.current_submission_id ?? t("common.none")}</td>
              <td>{formatDate(judger.last_seen_at, siteTimezone)}</td>
              <td>{judger.supported_languages.length}</td>
            </tr>
          )) : <tr><td colSpan={6} className="muted">{t("common.empty")}</td></tr>}
        </tbody>
      </table>
    </div>
  );
}

function JudgerEventsTable({ events, siteTimezone }: { events: JudgerEvent[]; siteTimezone: string }) {
  const { t } = useI18n();
  return (
    <div className="status-card status-card-wide">
      <h3>{t("status.judgerEvents")}</h3>
      <table>
        <thead>
          <tr>
            <th>{t("table.time")}</th>
            <th>{t("table.judger")}</th>
            <th>{t("table.event")}</th>
            <th>{t("table.submission")}</th>
            <th>{t("table.message")}</th>
          </tr>
        </thead>
        <tbody>
          {events.length ? events.map((event) => (
            <tr key={event.id}>
              <td>{formatDate(event.created_at, siteTimezone)}</td>
              <td>{event.judger_id}</td>
              <td>{event.event_type}</td>
              <td>{event.submission_id ?? t("common.none")}</td>
              <td>{event.message || "-"}</td>
            </tr>
          )) : <tr><td colSpan={5} className="muted">{t("common.empty")}</td></tr>}
        </tbody>
      </table>
    </div>
  );
}

function MetricBar({ label, value, max, tone = "default" }: { label: string; value: number; max: number; tone?: "default" | "ok" | "warn" }) {
  const width = max > 0 ? Math.max(4, Math.min(100, (value / max) * 100)) : 0;
  return (
    <div className={`metric-bar ${tone}`}>
      <div className="metric-bar-head"><span>{label}</span><strong>{value}</strong></div>
      <div className="metric-bar-track"><span style={{ width: `${width}%` }} /></div>
    </div>
  );
}

function formatDuration(seconds: number | null | undefined) {
  if (seconds === null || seconds === undefined) return "-";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const minutes = Math.floor(seconds / 60);
  const rest = Math.round(seconds % 60);
  if (minutes < 60) return rest ? `${minutes}m ${rest}s` : `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  const minuteRest = minutes % 60;
  return minuteRest ? `${hours}h ${minuteRest}m` : `${hours}h`;
}

function StatusTable({ title, rows, empty }: { title: string; rows: Array<[string, number]>; empty: string }) {
  const { t } = useI18n();
  return (
    <div className="status-card">
      <h3>{title}</h3>
      <table>
        <thead><tr><th>{t("table.name")}</th><th>{t("table.count")}</th></tr></thead>
        <tbody>
          {rows.length ? rows.map(([name, count]) => <tr key={name}><td>{name}</td><td>{count}</td></tr>) : <tr><td colSpan={2} className="muted">{empty}</td></tr>}
        </tbody>
      </table>
    </div>
  );
}

function ClarificationsAdmin({ api, siteTimezone }: { api: ApiClient; siteTimezone: string }) {
  const { t } = useI18n();
  const [clarifications, setClarifications] = useState<Clarification[]>([]);
  const [contests, setContests] = useState<Contest[]>([]);
  const [flash, setFlash] = useState<Flash>(emptyFlash);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [nextClarifications, nextContests] = await Promise.all([
        api<Clarification[]>("/api/admin/clarifications?status=open&limit=100"),
        api<Contest[]>("/api/contests")
      ]);
      setClarifications(nextClarifications);
      setContests(nextContests);
      setFlash(emptyFlash);
    } catch (error) {
      setFlash({ kind: "error", text: errorText(error) });
    } finally {
      setLoading(false);
    }
  }, [api]);

  useEffect(() => { load().catch((error) => setFlash({ kind: "error", text: errorText(error) })); }, [load]);

  async function updateClarification(clarification: Clarification, patch: { answer?: string; status?: ClarificationStatus; visibility?: ClarificationVisibility }) {
    setFlash(emptyFlash);
    try {
      await api<Clarification>(`/api/admin/clarifications/${clarification.id}`, {
        method: "PATCH",
        body: JSON.stringify(patch)
      });
      await load();
    } catch (error) {
      setFlash({ kind: "error", text: errorText(error) });
    }
  }

  return (
    <section className="panel">
      <Header title={t("tab.clarifications")} subtitle={t("clarification.adminSubtitle")} />
      <div className="toolbar">
        <button onClick={load} disabled={loading}>{loading ? t("status.refreshing") : t("common.refresh")}</button>
        <span className="muted">{t("clarification.openOnly")}</span>
      </div>
      <FlashMessage flash={flash} />
      {clarifications.length ? (
        <div className="clarification-list">
          {clarifications.map((clarification) => (
            <AdminClarificationCard
              key={clarification.id}
              clarification={clarification}
              contest={contests.find((contest) => contest.id === clarification.contest_id)}
              siteTimezone={siteTimezone}
              onUpdate={updateClarification}
            />
          ))}
        </div>
      ) : (
        <EmptyAdminState text={t("empty.clarificationsText")} />
      )}
    </section>
  );
}

function AdminClarificationCard({
  clarification,
  contest,
  siteTimezone,
  onUpdate
}: {
  clarification: Clarification;
  contest?: Contest;
  siteTimezone: string;
  onUpdate: (clarification: Clarification, patch: { answer?: string; status?: ClarificationStatus; visibility?: ClarificationVisibility }) => Promise<void>;
}) {
  const { t } = useI18n();
  const [answer, setAnswer] = useState(clarification.answer ?? "");
  const [visibility, setVisibility] = useState<ClarificationVisibility>(clarification.visibility);
  useEffect(() => {
    setAnswer(clarification.answer ?? "");
    setVisibility(clarification.visibility);
  }, [clarification]);

  return (
    <article className="clarification-card admin-clarification-card">
      <div className="clarification-head">
        <strong>{contest?.title || `#${clarification.contest_id}`} · {clarification.task_title || t("clarification.general")}</strong>
        <span className="meta-row">
          <span>{clarification.author_display_name}</span>
          <span className="pill">{t(`clarification.status.${clarification.status}`)}</span>
          <span>{formatDate(clarification.created_at, siteTimezone)}</span>
        </span>
      </div>
      <p>{clarification.question}</p>
      <div className="admin-answer-grid">
        <label>{t("clarification.answer")}<textarea className="short" value={answer} onChange={(event) => setAnswer(event.target.value)} /></label>
        <label>{t("clarification.visibilityLabel")}<select value={visibility} onChange={(event) => setVisibility(event.target.value as ClarificationVisibility)}>
          <option value="private">{t("clarification.visibility.private")}</option>
          <option value="broadcast">{t("clarification.visibility.broadcast")}</option>
        </select></label>
        <div className="toolbar">
          <button onClick={() => onUpdate(clarification, { answer, visibility })} disabled={!answer.trim()}>{t("clarification.answerAction")}</button>
          <button onClick={() => onUpdate(clarification, { status: "closed", visibility })}>{t("clarification.close")}</button>
          <button onClick={() => onUpdate(clarification, { visibility: "broadcast" })}>{t("clarification.broadcast")}</button>
        </div>
      </div>
    </article>
  );
}

function EmptyAdminState({ text }: { text: string }) {
  return <div className="empty-state"><span>{text}</span></div>;
}

function UsersAdmin({ api, siteTimezone }: { api: ApiClient; siteTimezone: string }) {
  const { t } = useI18n();
  const [users, setUsers] = useState<User[]>([]);
  const [flash, setFlash] = useState<Flash>(emptyFlash);
  const [query, setQuery] = useState("");
  const [form, setForm] = useState({ username: "", password: "", display_name: "", role: "participant" as Role });
  const filteredUsers = useMemo(
    () => users.filter((user) => matchesSearch([user.id, user.username, user.display_name, user.role, user.is_active], query)),
    [users, query]
  );

  const load = useCallback(() => api<User[]>("/api/users").then(setUsers), [api]);

  useEffect(() => {
    load().catch((error) => setFlash({ kind: "error", text: errorText(error) }));
  }, [load]);

  async function createUser(event: React.FormEvent) {
    event.preventDefault();
    setFlash(emptyFlash);
    try {
      await api<User>("/api/users", {
        method: "POST",
        body: JSON.stringify({ ...form, display_name: form.display_name || form.username })
      });
      setForm({ username: "", password: "", display_name: "", role: "participant" });
      await load();
      setFlash({ kind: "ok", text: t("user.created") });
    } catch (error) {
      setFlash({ kind: "error", text: errorText(error) });
    }
  }

  async function updateUser(user: User, patch: Partial<User> & { password?: string }) {
    setFlash(emptyFlash);
    try {
      await api<User>(`/api/users/${user.id}`, { method: "PATCH", body: JSON.stringify(patch) });
      await load();
    } catch (error) {
      setFlash({ kind: "error", text: errorText(error) });
    }
  }

  async function deleteUser(user: User) {
    if (!window.confirm(t("user.deleteConfirm", { name: user.username }))) return;
    setFlash(emptyFlash);
    try {
      await api<void>(`/api/users/${user.id}`, { method: "DELETE" });
      await load();
    } catch (error) {
      setFlash({ kind: "error", text: errorText(error) });
    }
  }

  return (
    <section className="panel">
      <Header title={t("tab.users")} subtitle={t("title.usersCount", { count: users.length })} />
      <form className="form-grid" onSubmit={createUser}>
        <label>{t("table.username")}<input value={form.username} onChange={(event) => setForm({ ...form, username: event.target.value })} required /></label>
        <label>{t("login.password")}<input value={form.password} onChange={(event) => setForm({ ...form, password: event.target.value })} required /></label>
        <label>{t("user.displayName")}<input value={form.display_name} onChange={(event) => setForm({ ...form, display_name: event.target.value })} /></label>
        <label>{t("table.role")}<select value={form.role} onChange={(event) => setForm({ ...form, role: event.target.value as Role })}><option value="participant">{t("role.participant")}</option><option value="admin">{t("role.admin")}</option></select></label>
        <button type="submit">{t("common.create")}</button>
      </form>
      <FlashMessage flash={flash} />
      <TableToolbar query={query} onQueryChange={setQuery} total={users.length} filtered={filteredUsers.length} placeholder={t("user.search")} />
      <div className="table-wrap">
        <table>
          <thead><tr><th>ID</th><th>{t("table.username")}</th><th>{t("table.name")}</th><th>{t("table.role")}</th><th>{t("table.active")}</th><th>{t("table.created")}</th><th></th></tr></thead>
          <tbody>
            {filteredUsers.map((user) => <UserRow key={user.id} user={user} siteTimezone={siteTimezone} onSave={updateUser} onDelete={deleteUser} />)}
            {!filteredUsers.length && <tr><td colSpan={7} className="muted">{t("empty.noMatchesText")}</td></tr>}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function UserRow({ user, siteTimezone, onSave, onDelete }: { user: User; siteTimezone: string; onSave: (user: User, patch: Partial<User> & { password?: string }) => void; onDelete: (user: User) => void }) {
  const { t } = useI18n();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState({ ...user, password: "" });

  useEffect(() => setDraft({ ...user, password: "" }), [user]);

  if (!editing) {
    return (
      <tr>
        <td>{user.id}</td><td>{user.username}</td><td>{user.display_name}</td><td>{t(`role.${user.role}`)}</td><td>{user.is_active ? t("common.yes") : t("common.no")}</td><td>{formatDate(user.created_at, siteTimezone)}</td>
        <td className="row-actions"><button onClick={() => setEditing(true)}>{t("common.edit")}</button><button className="danger" onClick={() => onDelete(user)}>{t("common.delete")}</button></td>
      </tr>
    );
  }

  return (
    <tr className="editing">
      <td>{user.id}</td>
      <td><input value={draft.username} onChange={(event) => setDraft({ ...draft, username: event.target.value })} /></td>
      <td><input value={draft.display_name} onChange={(event) => setDraft({ ...draft, display_name: event.target.value })} /></td>
      <td><select value={draft.role} onChange={(event) => setDraft({ ...draft, role: event.target.value as Role })}><option value="participant">{t("role.participant")}</option><option value="admin">{t("role.admin")}</option></select></td>
      <td><input className="check" type="checkbox" checked={draft.is_active} onChange={(event) => setDraft({ ...draft, is_active: event.target.checked })} /></td>
      <td><input placeholder={t("user.newPassword")} value={draft.password} onChange={(event) => setDraft({ ...draft, password: event.target.value })} /></td>
      <td className="row-actions">
        <button onClick={() => {
          const patch: Partial<User> & { password?: string } = { username: draft.username, display_name: draft.display_name, role: draft.role, is_active: draft.is_active };
          if (draft.password) patch.password = draft.password;
          onSave(user, patch);
          setEditing(false);
        }}>{t("common.save")}</button>
        <button onClick={() => setEditing(false)}>{t("common.cancel")}</button>
      </td>
    </tr>
  );
}

function ImportUsersAdmin({ api, token }: { api: ApiClient; token: string }) {
  const { t } = useI18n();
  const [report, setReport] = useState<ImportReport | null>(null);
  const [flash, setFlash] = useState<Flash>(emptyFlash);
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<UserImportPreview | null>(null);
  const [teams, setTeams] = useState<Team[]>([]);
  const [contests, setContests] = useState<Contest[]>([]);
  const [addToTeam, setAddToTeam] = useState(false);
  const [teamTarget, setTeamTarget] = useState<"existing" | "new">("existing");
  const [selectedTeamId, setSelectedTeamId] = useState("");
  const [newTeamName, setNewTeamName] = useState("");
  const [addToContest, setAddToContest] = useState(false);
  const [selectedContestId, setSelectedContestId] = useState("");

  const loadTargets = useCallback(async () => {
    const [nextTeams, nextContests] = await Promise.all([api<Team[]>("/api/teams"), api<Contest[]>("/api/contests")]);
    setTeams(nextTeams);
    setContests(nextContests);
  }, [api]);
  useEffect(() => { loadTargets().catch((error) => setFlash({ kind: "error", text: errorText(error) })); }, [loadTargets]);

  async function selectFile(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    setFlash(emptyFlash);
    setReport(null);
    setFile(file);
    try {
      setPreview(parseUserImportPreview(file.name, await file.text()));
    } catch (error) {
      setPreview(null);
      setFlash({ kind: "error", text: errorText(error) });
    } finally {
      event.target.value = "";
    }
  }

  async function importUsers() {
    if (!file) return;
    setFlash(emptyFlash);
    setReport(null);
    const body = new FormData();
    body.append("file", file);
    if (addToTeam) {
      if (teamTarget === "existing" && selectedTeamId) body.append("team_id", selectedTeamId);
      if (teamTarget === "new" && newTeamName.trim()) body.append("team_name", newTeamName.trim());
    }
    if (addToContest && selectedContestId) body.append("contest_id", selectedContestId);
    try {
      const response = await fetch(`${API_BASE}/api/users/import`, { method: "POST", headers: { Authorization: `Bearer ${token}` }, body });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || t("import.importFailed"));
      setReport(data);
      setFile(null);
      setPreview(null);
      await loadTargets();
    } catch (error) {
      setFlash({ kind: "error", text: errorText(error) });
    }
  }

  const canSubmitImport = Boolean(preview?.validCount)
    && (!addToTeam || (teamTarget === "existing" ? Boolean(selectedTeamId) : Boolean(newTeamName.trim())))
    && (!addToContest || Boolean(selectedContestId));

  return (
    <section className="panel">
      <Header title={t("tab.import")} subtitle="CSV, JSON, YAML" />
      <label className="file-field"><input type="file" accept=".csv,.json,.yml,.yaml" onChange={selectFile} /></label>
      <p className="muted">{t("import.expectedFields")}</p>
      <FlashMessage flash={flash} />
      {preview && (
        <div className="report import-preview">
          <div className="toolbar">
            <div>
              <strong>{file?.name}</strong>
              <p className="muted">{t("import.previewSummary", { valid: preview.validCount, total: preview.rows.length })}</p>
            </div>
            <div className="row-actions">
              <button type="button" onClick={importUsers} disabled={!canSubmitImport}>{t("import.submit")}</button>
              <button type="button" onClick={() => { setFile(null); setPreview(null); }}>{t("common.cancel")}</button>
            </div>
          </div>
          <div className="import-team-options">
            <label className="inline"><input className="check" type="checkbox" checked={addToTeam} onChange={(event) => setAddToTeam(event.target.checked)} /> {t("import.addToTeam")}</label>
            {addToTeam && (
              <div className="form-grid">
                <label>{t("import.teamTarget")}
                  <select value={teamTarget} onChange={(event) => setTeamTarget(event.target.value as "existing" | "new")}>
                    <option value="existing">{t("import.existingTeam")}</option>
                    <option value="new">{t("import.newTeam")}</option>
                  </select>
                </label>
                {teamTarget === "existing" ? (
                  <label>{t("table.team")}
                    <select value={selectedTeamId} onChange={(event) => setSelectedTeamId(event.target.value)}>
                      <option value="">{t("common.none")}</option>
                      {teams.map((team) => <option key={team.id} value={team.id}>{team.id}: {team.name}</option>)}
                    </select>
                  </label>
                ) : (
                  <label>{t("table.name")}<input value={newTeamName} onChange={(event) => setNewTeamName(event.target.value)} /></label>
                )}
              </div>
            )}
            <label className="inline"><input className="check" type="checkbox" checked={addToContest} onChange={(event) => setAddToContest(event.target.checked)} /> {t("import.addToContest")}</label>
            {addToContest && (
              <div className="form-grid">
                <label>{t("table.contest")}
                  <select value={selectedContestId} onChange={(event) => setSelectedContestId(event.target.value)}>
                    <option value="">{t("common.none")}</option>
                    {contests.map((contest) => <option key={contest.id} value={contest.id}>{contest.id}: {contest.title}</option>)}
                  </select>
                </label>
              </div>
            )}
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>{t("table.status")}</th><th>{t("table.username")}</th><th>{t("login.password")}</th><th>{t("user.displayName")}</th><th>{t("table.role")}</th><th>{t("common.errors")}</th></tr>
              </thead>
              <tbody>
                {preview.rows.map((row) => (
                  <tr key={row.index}>
                    <td><span className={row.errors.length ? "pill warn" : "pill ok"}>{row.errors.length ? t("import.invalid") : t("import.valid")}</span></td>
                    <td>{row.username || "-"}</td>
                    <td>{row.hasPassword ? t("import.passwordProvided") : t("import.passwordMissing")}</td>
                    <td>{row.display_name || row.username || "-"}</td>
                    <td>{row.role}</td>
                    <td>{row.errors.join("; ") || "-"}</td>
                  </tr>
                ))}
                {!preview.rows.length && <tr><td colSpan={6} className="muted">{t("common.empty")}</td></tr>}
              </tbody>
            </table>
          </div>
        </div>
      )}
      {report && (
        <div className="report">
          <div className="stat"><strong>{report.created}</strong><span>{t("common.created")}</span></div>
          <div className="stat"><strong>{report.skipped}</strong><span>{t("common.skipped")}</span></div>
          <div className="stat"><strong>{report.errors.length}</strong><span>{t("common.errors")}</span></div>
          {report.team_id && <div className="stat"><strong>{report.team_members_added ?? 0}</strong><span>{t("import.teamMembersAdded", { team: report.team_id })}</span></div>}
          {report.contest_id && <div className="stat"><strong>{report.contest_participants_added ?? 0}</strong><span>{t("import.contestParticipantsAdded", { contest: report.contest_id })}</span></div>}
          <table>
            <thead><tr><th>{t("table.status")}</th><th>{t("import.rowReport")}</th></tr></thead>
            <tbody>
              {report.created > 0 && <tr><td><span className="pill ok">{t("common.created")}</span></td><td>{t("import.success", { count: report.created })}</td></tr>}
              {report.errors.map((item, index) => <tr key={index}><td><span className="pill warn">{t("common.skipped")}/{t("common.errors")}</span></td><td>{item}</td></tr>)}
              {!report.errors.length && report.created === 0 && <tr><td><span className="pill">{t("common.empty")}</span></td><td>{t("import.acceptedNoRows")}</td></tr>}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

type UserImportPreviewRow = {
  index: number;
  username: string;
  display_name: string;
  role: Role;
  hasPassword: boolean;
  errors: string[];
};

type UserImportPreview = {
  rows: UserImportPreviewRow[];
  validCount: number;
};

function parseUserImportPreview(filename: string, text: string): UserImportPreview {
  const extension = filename.includes(".") ? filename.split(".").pop()?.toLowerCase() : "";
  let rows: Array<Record<string, unknown>>;
  if (extension === "csv") rows = parseCsvRows(text);
  else if (extension === "json") rows = parseJsonRows(text);
  else if (extension === "yml" || extension === "yaml") rows = parseSimpleYamlRows(text);
  else throw new Error("Unsupported import format");

  const previewRows = rows.map((row, index) => normalizePreviewRow(row, index + 1));
  return {
    rows: previewRows,
    validCount: previewRows.filter((row) => row.errors.length === 0).length
  };
}

function normalizePreviewRow(row: Record<string, unknown>, index: number): UserImportPreviewRow {
  const username = String(row.username ?? "").trim();
  const password = String(row.password ?? "");
  const displayName = String(row.display_name ?? "").trim();
  const rawRole = String(row.role ?? "participant").trim() || "participant";
  const role = rawRole === "admin" ? "admin" : "participant";
  const errors: string[] = [];
  if (!username) errors.push("username is required");
  if (!password) errors.push("password is required");
  if (rawRole !== "admin" && rawRole !== "participant") errors.push(`unknown role '${rawRole}'`);
  return { index, username, display_name: displayName, role, hasPassword: Boolean(password), errors };
}

function parseJsonRows(text: string): Array<Record<string, unknown>> {
  const data = JSON.parse(text);
  if (!Array.isArray(data)) throw new Error("JSON root must be an array");
  return data.map((item) => typeof item === "object" && item !== null ? item as Record<string, unknown> : {});
}

function parseCsvRows(text: string): Array<Record<string, unknown>> {
  const rows = parseCsvTable(text);
  if (!rows.length) return [];
  const headers = rows[0].map((header) => header.trim());
  return rows.slice(1).filter((row) => row.some((cell) => cell.trim())).map((row) => Object.fromEntries(headers.map((header, index) => [header, row[index] ?? ""])));
}

function parseCsvTable(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = "";
  let quoted = false;
  for (let index = 0; index < text.length; index += 1) {
    const char = text[index];
    const next = text[index + 1];
    if (quoted) {
      if (char === '"' && next === '"') {
        cell += '"';
        index += 1;
      } else if (char === '"') {
        quoted = false;
      } else {
        cell += char;
      }
    } else if (char === '"') {
      quoted = true;
    } else if (char === ",") {
      row.push(cell);
      cell = "";
    } else if (char === "\n") {
      row.push(cell);
      rows.push(row);
      row = [];
      cell = "";
    } else if (char !== "\r") {
      cell += char;
    }
  }
  row.push(cell);
  if (row.some((item) => item.trim())) rows.push(row);
  return rows;
}

function parseSimpleYamlRows(text: string): Array<Record<string, unknown>> {
  const rows: Array<Record<string, unknown>> = [];
  let current: Record<string, unknown> | null = null;
  for (const rawLine of text.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#")) continue;
    if (line.startsWith("- ")) {
      if (current) rows.push(current);
      current = {};
      const rest = line.slice(2).trim();
      if (rest) assignYamlPair(current, rest);
    } else if (current) {
      assignYamlPair(current, line);
    }
  }
  if (current) rows.push(current);
  return rows;
}

function assignYamlPair(target: Record<string, unknown>, line: string) {
  const separator = line.indexOf(":");
  if (separator < 0) return;
  const key = line.slice(0, separator).trim();
  const value = line.slice(separator + 1).trim().replace(/^['"]|['"]$/g, "");
  target[key] = value;
}

type PickerItem = {
  id: number;
  label: string;
  meta?: string;
};

function SearchPicker({
  label,
  items,
  selectedIds,
  onChange,
  placeholder,
  emptyText
}: {
  label: string;
  items: PickerItem[];
  selectedIds: number[];
  onChange: (ids: number[]) => void;
  placeholder: string;
  emptyText: string;
}) {
  const [query, setQuery] = useState("");
  const selected = new Set(selectedIds);
  const normalizedQuery = query.trim().toLowerCase();
  const selectedItems = selectedIds.map((id) => items.find((item) => item.id === id)).filter(Boolean) as PickerItem[];
  const filteredItems = items
    .filter((item) => {
      if (!normalizedQuery) return true;
      return `${item.id} ${item.label} ${item.meta ?? ""}`.toLowerCase().includes(normalizedQuery);
    })
    .slice(0, 20);

  function toggle(id: number) {
    onChange(selected.has(id) ? selectedIds.filter((current) => current !== id) : [...selectedIds, id]);
  }

  return (
    <div className="search-picker">
      <label>{label}<input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={placeholder} /></label>
      <div className="selected-chips">
        {selectedItems.length ? selectedItems.map((item) => (
          <button key={item.id} type="button" className="chip" onClick={() => toggle(item.id)}>
            {item.id}:{item.label} ×
          </button>
        )) : <span className="muted">{emptyText}</span>}
      </div>
      <div className="picker-options">
        {filteredItems.length ? filteredItems.map((item) => (
          <label key={item.id} className="picker-option">
            <input className="check" type="checkbox" checked={selected.has(item.id)} onChange={() => toggle(item.id)} />
            <span>{item.id}:{item.label}</span>
            {item.meta && <small>{item.meta}</small>}
          </label>
        )) : <span className="muted">{emptyText}</span>}
      </div>
    </div>
  );
}

function userPickerItems(users: User[]): PickerItem[] {
  return users.map((user) => ({ id: user.id, label: user.username, meta: user.display_name }));
}

function teamPickerItems(teams: Team[]): PickerItem[] {
  return teams.map((team) => ({ id: team.id, label: team.name, meta: `${team.member_ids.length}` }));
}

function formatUserIds(ids: number[], users: User[]) {
  return ids
    .map((id) => users.find((user) => user.id === id))
    .filter(Boolean)
    .map((user) => `${user?.id}:${user?.username}`)
    .join(", ");
}

function formatTeamIds(ids: number[], teams: Team[]) {
  return ids
    .map((id) => teams.find((team) => team.id === id))
    .filter(Boolean)
    .map((team) => `${team?.id}:${team?.name}`)
    .join(", ");
}

function TeamsAdmin({ api, siteTimezone }: { api: ApiClient; siteTimezone: string }) {
  const { t } = useI18n();
  const [teams, setTeams] = useState<Team[]>([]);
  const [users, setUsers] = useState<User[]>([]);
  const [flash, setFlash] = useState<Flash>(emptyFlash);
  const [query, setQuery] = useState("");
  const [form, setForm] = useState({ name: "", user_ids: [] as number[] });
  const filteredTeams = useMemo(
    () => teams.filter((team) => matchesSearch([team.id, team.name, team.member_ids.join(" "), formatUserIds(team.member_ids, users)], query)),
    [teams, users, query]
  );

  const load = useCallback(async () => {
    const [nextTeams, nextUsers] = await Promise.all([api<Team[]>("/api/teams"), api<User[]>("/api/users")]);
    setTeams(nextTeams);
    setUsers(nextUsers);
  }, [api]);

  useEffect(() => { load().catch((error) => setFlash({ kind: "error", text: errorText(error) })); }, [load]);

  async function createTeam(event: React.FormEvent) {
    event.preventDefault();
    setFlash(emptyFlash);
    try {
      await api<Team>("/api/teams", { method: "POST", body: JSON.stringify({ name: form.name, user_ids: form.user_ids }) });
      setForm({ name: "", user_ids: [] });
      await load();
    } catch (error) {
      setFlash({ kind: "error", text: errorText(error) });
    }
  }

  async function saveTeam(team: Team, patch: { name: string; user_ids: number[] }) {
    setFlash(emptyFlash);
    try {
      await api<Team>(`/api/teams/${team.id}`, { method: "PATCH", body: JSON.stringify(patch) });
      await load();
    } catch (error) {
      setFlash({ kind: "error", text: errorText(error) });
    }
  }

  async function deleteTeam(team: Team) {
    if (!window.confirm(t("team.deleteConfirm", { name: team.name }))) return;
    setFlash(emptyFlash);
    try {
      await api<void>(`/api/teams/${team.id}`, { method: "DELETE" });
      await load();
    } catch (error) {
      setFlash({ kind: "error", text: errorText(error) });
    }
  }

  return (
    <section className="panel">
      <Header title={t("tab.teams")} subtitle={t("title.teamsCount", { count: teams.length })} />
      <form className="task-form team-form" onSubmit={createTeam}>
        <label>{t("table.name")}<input value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} required /></label>
        <SearchPicker label={t("team.members")} items={userPickerItems(users.filter((user) => user.role === "participant"))} selectedIds={form.user_ids} onChange={(user_ids) => setForm({ ...form, user_ids })} placeholder={t("team.searchUsers")} emptyText={t("common.none")} />
        <button type="submit">{t("common.create")}</button>
      </form>
      <FlashMessage flash={flash} />
      <TableToolbar query={query} onQueryChange={setQuery} total={teams.length} filtered={filteredTeams.length} placeholder={t("team.search")} />
      <div className="table-wrap">
        <table>
          <thead><tr><th>{t("table.id")}</th><th>{t("table.name")}</th><th>{t("table.members")}</th><th>{t("table.created")}</th><th></th></tr></thead>
          <tbody>
            {filteredTeams.map((team) => <TeamRow key={team.id} team={team} users={users.filter((user) => user.role === "participant")} siteTimezone={siteTimezone} onSave={saveTeam} onDelete={deleteTeam} />)}
            {!filteredTeams.length && <tr><td colSpan={5} className="muted">{t("empty.noMatchesText")}</td></tr>}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function TeamRow({ team, users, siteTimezone, onSave, onDelete }: { team: Team; users: User[]; siteTimezone: string; onSave: (team: Team, patch: { name: string; user_ids: number[] }) => void; onDelete: (team: Team) => void }) {
  const { t } = useI18n();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState({ name: team.name, user_ids: team.member_ids });
  useEffect(() => setDraft({ name: team.name, user_ids: team.member_ids }), [team]);

  if (editing) {
    return (
      <tr className="editing">
        <td colSpan={5}>
          <form
            className="task-form team-form team-edit-form"
            onSubmit={(event) => {
              event.preventDefault();
              onSave(team, { name: draft.name, user_ids: draft.user_ids });
              setEditing(false);
            }}
          >
            <div className="section-title">
              <h3>{t("team.editTitle", { id: team.id })}</h3>
              <div className="row-actions">
                <button type="button" onClick={() => setEditing(false)}>{t("common.cancel")}</button>
                <button type="submit">{t("common.save")}</button>
              </div>
            </div>
            <label>{t("table.name")}<input value={draft.name} onChange={(event) => setDraft({ ...draft, name: event.target.value })} required /></label>
            <SearchPicker label={t("team.members")} items={userPickerItems(users)} selectedIds={draft.user_ids} onChange={(user_ids) => setDraft({ ...draft, user_ids })} placeholder={t("team.searchUsers")} emptyText={t("common.none")} />
          </form>
        </td>
      </tr>
    );
  }

  return (
    <tr>
      <td>{team.id}</td>
      <td>{team.name}</td>
      <td>{formatUserIds(team.member_ids, users) || "-"}</td>
      <td>{formatDate(team.created_at, siteTimezone)}</td>
      <td className="row-actions">
        <button onClick={() => setEditing(true)}>{t("common.edit")}</button>
        <button className="danger" onClick={() => onDelete(team)}>{t("common.delete")}</button>
      </td>
    </tr>
  );
}

function ContestsAdmin({ api, onChanged, siteTimezone }: { api: ApiClient; onChanged: () => void; siteTimezone: string }) {
  const { t } = useI18n();
  const [contests, setContests] = useState<Contest[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [users, setUsers] = useState<User[]>([]);
  const [teams, setTeams] = useState<Team[]>([]);
  const [contestTaskIds, setContestTaskIds] = useState<Record<number, number[]>>({});
  const [contestParticipantIds, setContestParticipantIds] = useState<Record<number, number[]>>({});
  const [contestTeamIds, setContestTeamIds] = useState<Record<number, number[]>>({});
  const [registrations, setRegistrations] = useState<ContestRegistration[]>([]);
  const [registrationFilter, setRegistrationFilter] = useState<"pending" | "all">("pending");
  const [flash, setFlash] = useState<Flash>(emptyFlash);
  const [query, setQuery] = useState("");
  const [view, setView] = useState<"list" | "form">("list");
  const [editingContestId, setEditingContestId] = useState<number | null>(null);
  const [form, setForm] = useState<ContestFormState>(() => createEmptyContestForm(siteTimezone));
  const editingContest = editingContestId ? contests.find((contest) => contest.id === editingContestId) ?? null : null;
  const filteredContests = useMemo(
    () => contests.filter((contest) => matchesSearch([
      contest.id,
      contest.title,
      contest.description,
      contest.status,
      contest.is_public ? t("contest.public") : t("contest.private"),
      contest.registration_enabled ? t("registration.enabledShort") : "",
      contest.participation_mode,
      t(`scoring.${contest.scoring_mode ?? "ioi"}`),
      contest.time_mode,
      t(`scoreboard.visibility.${contest.scoreboard_visibility ?? "public"}`),
      contestTaskIds[contest.id]?.join(" "),
      formatUserIds(contestParticipantIds[contest.id] ?? [], users),
      formatTeamIds(contestTeamIds[contest.id] ?? [], teams)
    ], query)),
    [contests, contestTaskIds, contestParticipantIds, contestTeamIds, users, teams, query, t]
  );

  const load = useCallback(async () => {
    const [nextContests, nextTasks, nextUsers, nextTeams, nextRegistrations] = await Promise.all([api<Contest[]>("/api/contests"), api<Task[]>("/api/tasks"), api<User[]>("/api/users"), api<Team[]>("/api/teams"), api<ContestRegistration[]>(`/api/admin/contest-registrations?status=${registrationFilter}`)]);
    const nextContestTaskEntries = await Promise.all(
      nextContests.map(async (contest) => {
        const contestTasks = await api<Task[]>(`/api/contests/${contest.id}/tasks`);
        return [contest.id, contestTasks.map((task) => task.id)] as const;
      })
    );
    const nextContestParticipantEntries = await Promise.all(
      nextContests.map(async (contest) => {
        const participants = await api<User[]>(`/api/contests/${contest.id}/participants`);
        return [contest.id, participants.map((participant) => participant.id)] as const;
      })
    );
    const nextContestTeamEntries = await Promise.all(
      nextContests.map(async (contest) => {
        const contestTeams = await api<Team[]>(`/api/contests/${contest.id}/teams`);
        return [contest.id, contestTeams.map((team) => team.id)] as const;
      })
    );
    setContests(nextContests);
    setTasks(nextTasks);
    setUsers(nextUsers.filter((user) => user.role === "participant"));
    setTeams(nextTeams);
    setContestTaskIds(Object.fromEntries(nextContestTaskEntries));
    setContestParticipantIds(Object.fromEntries(nextContestParticipantEntries));
    setContestTeamIds(Object.fromEntries(nextContestTeamEntries));
    setRegistrations(nextRegistrations);
  }, [api, registrationFilter]);
  useEffect(() => { load().catch((error) => setFlash({ kind: "error", text: errorText(error) })); }, [load]);

  function resetContestForm() {
    setEditingContestId(null);
    setForm(createEmptyContestForm(siteTimezone));
    setView("list");
  }

  function startContestCreate() {
    setEditingContestId(null);
    setForm(createEmptyContestForm(siteTimezone));
    setView("form");
  }

  function editContest(contest: Contest) {
    setEditingContestId(contest.id);
    setForm(contestToForm(
      contest,
      contestTaskIds[contest.id] ?? [],
      contestParticipantIds[contest.id] ?? [],
      contestTeamIds[contest.id] ?? [],
      siteTimezone
    ));
    setView("form");
  }

  async function submitContestForm(event: React.FormEvent) {
    event.preventDefault();
    setFlash(emptyFlash);
    try {
      const individualDurationMinutes = form.time_mode === "individual" ? durationClockToMinutes(form.individual_duration_minutes) : null;
      if (form.time_mode === "individual" && individualDurationMinutes == null) {
        throw new Error(t("contest.durationInvalid"));
      }
      const payload = {
        ...form,
        task_ids: undefined,
        participant_ids: undefined,
        team_ids: undefined,
        starts_at: fromLocalInputValue(form.starts_at, siteTimezone),
        ends_at: fromLocalInputValue(form.ends_at, siteTimezone),
        individual_duration_minutes: individualDurationMinutes,
        scoreboard_freeze_at: form.scoreboard_freeze_at ? fromLocalInputValue(form.scoreboard_freeze_at, siteTimezone) : null,
        scoreboard_unfrozen: form.scoreboard_unfrozen
      };
      const contest = editingContest
        ? await api<Contest>(`/api/contests/${editingContest.id}`, { method: "PATCH", body: JSON.stringify(payload) })
        : await api<Contest>("/api/contests", { method: "POST", body: JSON.stringify(payload) });
      if (form.task_ids.length) {
        await api<Task[]>(`/api/contests/${contest.id}/tasks`, { method: "PUT", body: JSON.stringify({ task_ids: form.task_ids }) });
      } else if (editingContest) {
        await api<Task[]>(`/api/contests/${contest.id}/tasks`, { method: "PUT", body: JSON.stringify({ task_ids: [] }) });
      }
      const participantIds = accessModeOf(form) === "private" ? form.participant_ids : [];
      if (participantIds.length || editingContest) {
        await api<User[]>(`/api/contests/${contest.id}/participants`, { method: "PUT", body: JSON.stringify({ user_ids: participantIds }) });
      }
      const teamIds = accessModeOf(form) === "private" ? form.team_ids : [];
      if (teamIds.length || editingContest) {
        await api<Team[]>(`/api/contests/${contest.id}/teams`, { method: "PUT", body: JSON.stringify({ team_ids: teamIds }) });
      }
      resetContestForm();
      await load();
      onChanged();
    } catch (error) {
      setFlash({ kind: "error", text: errorText(error) });
    }
  }

  async function deleteContest(contest: Contest) {
    if (!window.confirm(t("contest.deleteConfirm", { name: contest.title }))) return;
    setFlash(emptyFlash);
    try {
      await api<void>(`/api/contests/${contest.id}`, { method: "DELETE" });
      if (editingContestId === contest.id) resetContestForm();
      await load();
      onChanged();
    } catch (error) {
      setFlash({ kind: "error", text: errorText(error) });
    }
  }

  async function decideRegistration(registration: ContestRegistration, decision: "approved" | "rejected") {
    setFlash(emptyFlash);
    try {
      await api<ContestRegistration>(`/api/admin/contest-registrations/${registration.id}?decision=${decision}`, { method: "PATCH" });
      await load();
      onChanged();
    } catch (error) {
      setFlash({ kind: "error", text: errorText(error) });
    }
  }

  if (view === "form") {
    return (
      <section className="panel">
        <div className="section-title">
          <span className="muted">{t("tab.contests")}</span>
          <button type="button" onClick={resetContestForm}>{t("common.backToList")}</button>
        </div>
        <ContestForm
          form={form}
          mode={editingContest ? "edit" : "create"}
          tasks={tasks}
          users={users}
          teams={teams}
          onChange={setForm}
          onCancel={resetContestForm}
          onSubmit={submitContestForm}
        />
        <FlashMessage flash={flash} />
        {editingContest?.time_mode === "individual" && (
          <IndividualTimeAdmin
            api={api}
            contest={editingContest}
            users={users}
            siteTimezone={siteTimezone}
          />
        )}
      </section>
    );
  }

  return (
    <section className="panel">
      <div className="section-title">
        <div>
          <h3>{t("contest.listTitle")}</h3>
          <span className="muted">{t("title.contestsCount", { count: contests.length })}</span>
        </div>
        <button type="button" onClick={startContestCreate}>{t("common.create")}</button>
      </div>
      <FlashMessage flash={flash} />
      <PendingRegistrations registrations={registrations} filter={registrationFilter} onFilterChange={setRegistrationFilter} onDecide={decideRegistration} siteTimezone={siteTimezone} />
      <TableToolbar query={query} onQueryChange={setQuery} total={contests.length} filtered={filteredContests.length} placeholder={t("contest.search")} />
      <div className="table-wrap">
        <table>
          <thead><tr><th>{t("table.id")}</th><th>{t("table.title")}</th><th>{t("table.status")}</th><th>{t("table.access")}</th><th>{t("contest.participationMode")}</th><th>{t("scoring.mode")}</th><th>{t("table.mode")}</th><th>{t("table.starts")}</th><th>{t("table.ends")}</th><th>{t("contest.individualDurationShort")}</th><th>{t("scoreboard.freezeAt")}</th><th>{t("scoreboard.visibility")}</th><th>{t("scoreboard.unfrozenShort")}</th><th>{t("table.tasks")}</th><th>{t("table.participants")}</th><th>{t("table.teams")}</th><th></th></tr></thead>
          <tbody>
            {filteredContests.map((contest) => (
              <ContestTableRow
                key={contest.id}
                contest={contest}
                users={users}
                teams={teams}
                taskIds={contestTaskIds[contest.id] ?? []}
                participantIds={contestParticipantIds[contest.id] ?? []}
                teamIds={contestTeamIds[contest.id] ?? []}
                siteTimezone={siteTimezone}
                isSelected={contest.id === editingContestId}
                onEdit={editContest}
                onDelete={deleteContest}
              />
            ))}
            {!filteredContests.length && <tr><td colSpan={17} className="muted">{t("empty.noMatchesText")}</td></tr>}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function IndividualTimeAdmin({
  api,
  contest,
  users,
  siteTimezone
}: {
  api: ApiClient;
  contest: Contest;
  users: User[];
  siteTimezone: string;
}) {
  const { t } = useI18n();
  const [rows, setRows] = useState<ParticipantContestTime[]>([]);
  const [flash, setFlash] = useState<Flash>(emptyFlash);
  const [selectedUserId, setSelectedUserId] = useState("");
  const [deltaValues, setDeltaValues] = useState<Record<number, string>>({});
  const [durationValues, setDurationValues] = useState<Record<number, string>>({});
  const [startValues, setStartValues] = useState<Record<number, string>>({});
  const [deadlineValues, setDeadlineValues] = useState<Record<number, string>>({});

  const availableUsers = users.filter((user) => !rows.some((row) => row.user_id === user.id));

  const load = useCallback(async () => {
    const nextRows = await api<ParticipantContestTime[]>(`/api/admin/contests/${contest.id}/participant-times`);
    setRows(nextRows);
    setDeltaValues((current) => Object.fromEntries(nextRows.map((row) => [row.user_id, current[row.user_id] || "00:15"])));
    setDurationValues((current) => Object.fromEntries(nextRows.map((row) => [row.user_id, current[row.user_id] || durationMinutesToClock(row.duration_seconds == null ? null : Math.ceil(row.duration_seconds / 60))])));
    setStartValues(Object.fromEntries(nextRows.map((row) => [row.user_id, row.started_at ? toLocalInputValue(row.started_at, siteTimezone) : ""])));
    setDeadlineValues(Object.fromEntries(nextRows.map((row) => [row.user_id, row.deadline_at ? toLocalInputValue(row.deadline_at, siteTimezone) : ""])));
  }, [api, contest.id, siteTimezone]);

  useEffect(() => { load().catch((error) => setFlash({ kind: "error", text: errorText(error) })); }, [load]);

  async function patchUserTime(userId: number, payload: Record<string, unknown>) {
    setFlash(emptyFlash);
    try {
      await api<ParticipantContestTime>(`/api/admin/contests/${contest.id}/participant-times/${userId}`, {
        method: "PATCH",
        body: JSON.stringify(payload)
      });
      await load();
    } catch (error) {
      setFlash({ kind: "error", text: errorText(error) });
    }
  }

  async function addParticipantTime() {
    const userId = Number(selectedUserId);
    if (!userId) return;
    await patchUserTime(userId, { duration_seconds: (contest.individual_duration_minutes ?? 1) * 60 });
    setSelectedUserId("");
  }

  function adjustDeadline(row: ParticipantContestTime, sign: 1 | -1) {
    const seconds = parseDurationClock(deltaValues[row.user_id] || "");
    if (seconds == null) {
      setFlash({ kind: "error", text: t("contest.durationInvalid") });
      return;
    }
    void patchUserTime(row.user_id, { delta_seconds: seconds * sign });
  }

  function setDuration(row: ParticipantContestTime) {
    const seconds = parseDurationClock(durationValues[row.user_id] || "");
    if (seconds == null) {
      setFlash({ kind: "error", text: t("contest.durationInvalid") });
      return;
    }
    void patchUserTime(row.user_id, { duration_seconds: seconds });
  }

  function saveWindow(row: ParticipantContestTime) {
    const startedAt = startValues[row.user_id] ? fromLocalInputValue(startValues[row.user_id], siteTimezone) : null;
    const deadlineAt = deadlineValues[row.user_id] ? fromLocalInputValue(deadlineValues[row.user_id], siteTimezone) : null;
    void patchUserTime(row.user_id, { started_at: startedAt, deadline_at: deadlineAt });
  }

  return (
    <div className="status-card status-card-wide individual-time-panel">
      <div className="toolbar">
        <div>
          <h3>{t("contest.individualTimeTitle")}</h3>
          <p className="muted">{t("contest.individualTimeSubtitle")}</p>
        </div>
        <div className="inline-controls">
          <select value={selectedUserId} onChange={(event) => setSelectedUserId(event.target.value)}>
            <option value="">{t("contest.addParticipantTime")}</option>
            {availableUsers.map((user) => <option key={user.id} value={user.id}>#{user.id} {user.username}</option>)}
          </select>
          <button type="button" onClick={addParticipantTime} disabled={!selectedUserId}>{t("common.add")}</button>
        </div>
      </div>
      <FlashMessage flash={flash} />
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>{t("table.user")}</th>
              <th>{t("table.started")}</th>
              <th>{t("table.deadline")}</th>
              <th>{t("contest.spentTime")}</th>
              <th>{t("contest.remainingTime")}</th>
              <th>{t("contest.adjustTime")}</th>
              <th>{t("contest.setDuration")}</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.user_id}>
                <td><strong>{row.display_name || row.username}</strong><br /><span className="muted">#{row.user_id} {row.username}</span></td>
                <td><input type="datetime-local" value={startValues[row.user_id] || ""} onChange={(event) => setStartValues({ ...startValues, [row.user_id]: event.target.value })} /></td>
                <td><input type="datetime-local" value={deadlineValues[row.user_id] || ""} onChange={(event) => setDeadlineValues({ ...deadlineValues, [row.user_id]: event.target.value })} /></td>
                <td>{formatDurationClock(row.spent_seconds)}</td>
                <td>{formatDurationClock(row.remaining_seconds)}</td>
                <td>
                  <div className="inline-controls compact">
                    <input value={deltaValues[row.user_id] || ""} onChange={(event) => setDeltaValues({ ...deltaValues, [row.user_id]: event.target.value })} placeholder="HH:MM" />
                    <button type="button" onClick={() => adjustDeadline(row, 1)}>+</button>
                    <button type="button" onClick={() => adjustDeadline(row, -1)}>-</button>
                  </div>
                </td>
                <td>
                  <div className="inline-controls compact">
                    <input value={durationValues[row.user_id] || ""} onChange={(event) => setDurationValues({ ...durationValues, [row.user_id]: event.target.value })} placeholder="HH:MM" />
                    <button type="button" onClick={() => setDuration(row)}>{t("common.save")}</button>
                  </div>
                </td>
                <td className="row-actions">
                  <button type="button" onClick={() => saveWindow(row)}>{t("contest.saveWindow")}</button>
                  <button type="button" className="danger" onClick={() => patchUserTime(row.user_id, { reset: true })}>{t("contest.resetTime")}</button>
                </td>
              </tr>
            ))}
            {!rows.length && <tr><td colSpan={8} className="muted">{t("contest.noIndividualTimes")}</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function PendingRegistrations({
  registrations,
  filter,
  onFilterChange,
  onDecide,
  siteTimezone
}: {
  registrations: ContestRegistration[];
  filter: "pending" | "all";
  onFilterChange: (filter: "pending" | "all") => void;
  onDecide: (registration: ContestRegistration, decision: "approved" | "rejected") => void;
  siteTimezone: string;
}) {
  const { t } = useI18n();
  return (
    <div className="status-card status-card-wide">
      <div className="toolbar">
        <h3>{t("registration.pending")}</h3>
        <select value={filter} onChange={(event) => onFilterChange(event.target.value as "pending" | "all")}>
          <option value="pending">{t("registration.pendingOnly")}</option>
          <option value="all">{t("registration.all")}</option>
        </select>
      </div>
      <table>
        <thead>
          <tr><th>{t("table.contest")}</th><th>{t("table.user")}</th><th>{t("table.team")}</th><th>{t("table.status")}</th><th>{t("table.created")}</th><th></th></tr>
        </thead>
        <tbody>
          {registrations.length ? registrations.map((registration) => (
            <tr key={registration.id}>
              <td>{registration.contest_title || registration.contest_id}</td>
              <td>{registration.user_display_name || registration.username || t("common.none")}</td>
              <td>{registration.team_name || t("common.none")}</td>
              <td><span className={registration.status === "rejected" ? "pill warn" : "pill"}>{t(`registration.status.${registration.status}`)}</span></td>
              <td>{formatDate(registration.requested_at, siteTimezone)}</td>
              <td className="row-actions">
                {registration.status === "pending" ? (
                  <>
                    <button onClick={() => onDecide(registration, "approved")}>{t("registration.approve")}</button>
                    <button className="danger" onClick={() => onDecide(registration, "rejected")}>{t("registration.reject")}</button>
                  </>
                ) : (
                  <span className="muted">{registration.decided_at ? formatDate(registration.decided_at, siteTimezone) : t("common.none")}</span>
                )}
              </td>
            </tr>
          )) : <tr><td colSpan={6} className="muted">{t("common.empty")}</td></tr>}
        </tbody>
      </table>
    </div>
  );
}

const contestStatuses: ContestStatus[] = ["draft", "scheduled", "archived"];

function ContestForm({
  form,
  mode,
  tasks,
  users,
  teams,
  onChange,
  onCancel,
  onSubmit
}: {
  form: ContestFormState;
  mode: "create" | "edit";
  tasks: Task[];
  users: User[];
  teams: Team[];
  onChange: React.Dispatch<React.SetStateAction<ContestFormState>>;
  onCancel?: () => void;
  onSubmit: (event: React.FormEvent) => void;
}) {
  const { t } = useI18n();
  const accessMode = accessModeOf(form);
  const [scoringHelpOpen, setScoringHelpOpen] = useState(false);
  const [descriptionPreviewMode, setDescriptionPreviewMode] = useState<"edit" | "preview">("edit");

  function toggleTask(taskId: number) {
    onChange((current) => ({
      ...current,
      task_ids: current.task_ids.includes(taskId) ? current.task_ids.filter((id) => id !== taskId) : [...current.task_ids, taskId]
    }));
  }

  return (
    <form className="task-form contest-form" onSubmit={onSubmit}>
      <div className="section-title">
        <h3>{mode === "edit" ? t("contest.editTitle") : t("contest.createTitle")}</h3>
        <div className="row-actions">
          {onCancel && <button type="button" onClick={onCancel}>{t("common.cancel")}</button>}
          <button type="submit">{mode === "edit" ? t("common.save") : t("common.create")}</button>
        </div>
      </div>
      <fieldset>
        <legend>{t("contest.sectionBasic")}</legend>
        <div className="form-grid">
          <label>{t("table.title")}<input value={form.title} onChange={(event) => onChange({ ...form, title: event.target.value })} required /></label>
          <label>{t("table.status")}<select value={form.status} onChange={(event) => onChange({ ...form, status: event.target.value as ContestStatus })}>{contestStatuses.map((item) => <option key={item} value={item}>{t(`status.${item}`)}</option>)}</select></label>
          <label>{t("contest.participationMode")}<select value={form.participation_mode} onChange={(event) => onChange({ ...form, participation_mode: event.target.value as ParticipationMode })}><option value="individual">{t("common.individual")}</option><option value="team">{t("common.team")}</option></select></label>
          <label>
            <span className="label-row">{t("scoring.mode")}<button type="button" className="icon-button" aria-label={t("scoring.helpOpen")} onClick={() => setScoringHelpOpen(true)}>?</button></span>
            <select value={form.scoring_mode} onChange={(event) => onChange({ ...form, scoring_mode: event.target.value as ScoringMode })}>
              <option value="ioi">{t("scoring.ioi")}</option>
              <option value="ecoo">{t("scoring.ecoo")}</option>
              <option value="icpc">{t("scoring.icpc")}</option>
              <option value="atcoder">{t("scoring.atcoder")}</option>
            </select>
          </label>
          <div className="span-full markdown-field">
            <div className="label-row">
              <span>{t("table.description")}</span>
              <div className="segmented">
                <button type="button" className={descriptionPreviewMode === "edit" ? "active" : ""} onClick={() => setDescriptionPreviewMode("edit")}>{t("task.editMarkdown")}</button>
                <button type="button" className={descriptionPreviewMode === "preview" ? "active" : ""} onClick={() => setDescriptionPreviewMode("preview")}>{t("task.previewMarkdown")}</button>
              </div>
            </div>
            {descriptionPreviewMode === "edit" ? (
              <textarea className="contest-description-editor" value={form.description} onChange={(event) => onChange({ ...form, description: event.target.value })} />
            ) : (
              <MarkdownPreview value={form.description} />
            )}
          </div>
        </div>
      </fieldset>
      <fieldset>
        <legend>{t("contest.sectionSchedule")}</legend>
        <div className="form-grid">
          <label>{t("table.mode")}<select value={form.time_mode} onChange={(event) => onChange({ ...form, time_mode: event.target.value as TimeMode })}><option value="fixed">{t("common.fixed")}</option><option value="individual">{t("common.individual")}</option></select></label>
          <label>{t("table.starts")}<input type="datetime-local" value={form.starts_at} onChange={(event) => onChange({ ...form, starts_at: event.target.value })} required /></label>
          <label>{t("table.ends")}<input type="datetime-local" value={form.ends_at} onChange={(event) => onChange({ ...form, ends_at: event.target.value })} required /></label>
          <label>{t("contest.individualDuration")}<input type="time" step={60} value={form.individual_duration_minutes} disabled={form.time_mode === "fixed"} onChange={(event) => onChange({ ...form, individual_duration_minutes: event.target.value })} /></label>
          <label>{t("scoreboard.freezeAt")}<input type="datetime-local" value={form.scoreboard_freeze_at} onChange={(event) => onChange({ ...form, scoreboard_freeze_at: event.target.value })} /></label>
          <label>{t("scoreboard.visibility")}<select value={form.scoreboard_visibility} onChange={(event) => onChange({ ...form, scoreboard_visibility: event.target.value as ScoreboardVisibility })}><option value="public">{t("scoreboard.visibility.public")}</option><option value="anonymous">{t("scoreboard.visibility.anonymous")}</option><option value="hidden">{t("scoreboard.visibility.hidden")}</option></select></label>
          <label className="inline"><input className="check" type="checkbox" checked={form.scoreboard_unfrozen} onChange={(event) => onChange({ ...form, scoreboard_unfrozen: event.target.checked })} /> {t("scoreboard.unfrozen")}</label>
        </div>
      </fieldset>
      <fieldset>
        <legend>{t("contest.sectionTasks")}</legend>
        <div className="checklist">{tasks.map((task) => (
          <label key={task.id} className="inline"><input className="check" type="checkbox" checked={form.task_ids.includes(task.id)} onChange={() => toggleTask(task.id)} /> #{task.id} {task.title}</label>
        ))}</div>
      </fieldset>
      <fieldset>
        <legend>{t("contest.sectionAccess")}</legend>
        <div className="access-mode-grid" role="radiogroup" aria-label={t("contest.accessMode")}>
          <label className={`access-card ${accessMode === "public" ? "active" : ""}`}>
            <input className="check" type="radio" name="contest-access-mode" checked={accessMode === "public"} onChange={() => onChange((current) => applyContestAccessMode(current, "public"))} />
            <strong>{t("contest.publicAccess")}</strong>
            <span>{t("contest.accessPublicDescription")}</span>
          </label>
          <label className={`access-card ${accessMode === "registration" ? "active" : ""}`}>
            <input className="check" type="radio" name="contest-access-mode" checked={accessMode === "registration"} onChange={() => onChange((current) => applyContestAccessMode(current, "registration"))} />
            <strong>{t("registration.enabled")}</strong>
            <span>{t("contest.accessRegistrationDescription")}</span>
          </label>
          <label className={`access-card ${accessMode === "private" ? "active" : ""}`}>
            <input className="check" type="radio" name="contest-access-mode" checked={accessMode === "private"} onChange={() => onChange((current) => applyContestAccessMode(current, "private"))} />
            <strong>{t("contest.accessPrivate")}</strong>
            <span>{t("contest.accessPrivateDescription")}</span>
          </label>
        </div>
        {accessMode === "registration" && (
          <label className="inline access-suboption"><input className="check" type="checkbox" checked={form.registration_requires_approval} onChange={(event) => onChange({ ...form, registration_requires_approval: event.target.checked })} /> {t("registration.requiresApproval")}</label>
        )}
        {accessMode === "private" ? (
          <div className="access-grid">
            <SearchPicker label={t("contest.allowedParticipants")} items={userPickerItems(users)} selectedIds={form.participant_ids} onChange={(participant_ids) => onChange({ ...form, participant_ids })} placeholder={t("contest.searchParticipants")} emptyText={t("common.none")} />
            <SearchPicker label={t("contest.allowedTeams")} items={teamPickerItems(teams)} selectedIds={form.team_ids} onChange={(team_ids) => onChange({ ...form, team_ids })} placeholder={t("contest.searchTeams")} emptyText={t("common.none")} />
          </div>
        ) : (
          <p className="access-disabled-note">{t("contest.accessListsDisabled")}</p>
        )}
      </fieldset>
      {scoringHelpOpen && <ScoringHelpModal onClose={() => setScoringHelpOpen(false)} />}
    </form>
  );
}

function ScoringHelpModal({ onClose }: { onClose: () => void }) {
  const { t } = useI18n();
  const modes: ScoringMode[] = ["ioi", "ecoo", "icpc", "atcoder"];
  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={onClose}>
      <div className="modal-panel scoring-modal" role="dialog" aria-modal="true" aria-labelledby="scoring-help-title" onMouseDown={(event) => event.stopPropagation()}>
        <div className="section-title">
          <h3 id="scoring-help-title">{t("scoring.helpTitle")}</h3>
          <button type="button" onClick={onClose}>{t("common.close")}</button>
        </div>
        <div className="scoring-help-grid">
          {modes.map((mode) => (
            <section key={mode}>
              <h4>{t(`scoring.${mode}`)}</h4>
              <p>{t(`scoring.${mode}.description`)}</p>
              <p className="muted">{t(`scoring.${mode}.example`)}</p>
            </section>
          ))}
        </div>
      </div>
    </div>
  );
}

function ContestTableRow({
  contest,
  users,
  teams,
  taskIds,
  participantIds,
  teamIds,
  siteTimezone,
  isSelected,
  onEdit,
  onDelete
}: {
  contest: Contest;
  users: User[];
  teams: Team[];
  taskIds: number[];
  participantIds: number[];
  teamIds: number[];
  siteTimezone: string;
  isSelected: boolean;
  onEdit: (contest: Contest) => void;
  onDelete: (contest: Contest) => void;
}) {
  const { t } = useI18n();
  const participantNames = formatUserIds(participantIds, users);
  const teamNames = formatTeamIds(teamIds, teams);
  return (
    <tr className={isSelected ? "selected" : ""}>
      <td>{contest.id}</td><td>{contest.title}</td><td>{t(`status.${contest.status}`)}</td><td>{contest.is_public ? t("contest.public") : contest.registration_enabled ? t("registration.enabledShort") : t("contest.private")}</td><td>{t(`common.${contest.participation_mode}`)}</td><td>{t(`scoring.${contest.scoring_mode ?? "ioi"}`)}</td><td>{t(`common.${contest.time_mode}`)}</td>
      <td>{formatDate(contest.starts_at, siteTimezone)}</td><td>{formatDate(contest.ends_at, siteTimezone)}</td><td>{durationMinutesToClock(contest.individual_duration_minutes) || "-"}</td><td>{formatDate(contest.scoreboard_freeze_at, siteTimezone)}</td><td>{t(`scoreboard.visibility.${contest.scoreboard_visibility ?? "public"}`)}</td><td>{contest.scoreboard_unfrozen ? t("common.yes") : t("common.no")}</td>
      <td>{taskIds.length}</td><td>{participantNames || t("common.none")}</td><td>{teamNames || t("common.none")}</td>
      <td className="row-actions"><button onClick={() => onEdit(contest)}>{t("common.edit")}</button><button className="danger" onClick={() => onDelete(contest)}>{t("common.delete")}</button></td>
    </tr>
  );
}

type TaskFormState = {
  title: string;
  statement: string;
  input_format: string;
  output_format: string;
  samples: string;
  time_limit_ms: string;
  memory_limit_mb: string;
  points: string;
  partial_scoring: boolean;
  test_input: string;
  test_output: string;
  test_is_sample: boolean;
};

function createEmptyTaskForm(): TaskFormState {
  return {
    title: "",
    statement: "",
    input_format: "",
    output_format: "",
    samples: "[]",
    time_limit_ms: "2000",
    memory_limit_mb: "256",
    points: "100",
    partial_scoring: false,
    test_input: "",
    test_output: "",
    test_is_sample: true
  };
}

function taskToForm(task: Task): TaskFormState {
  return {
    title: task.title,
    statement: task.statement,
    input_format: task.input_format,
    output_format: task.output_format,
    samples: JSON.stringify(task.samples, null, 2),
    time_limit_ms: String(task.time_limit_ms),
    memory_limit_mb: String(task.memory_limit_mb),
    points: String(task.points),
    partial_scoring: task.partial_scoring,
    test_input: "",
    test_output: "",
    test_is_sample: true
  };
}

function TasksAdmin({ api }: { api: ApiClient }) {
  const { t } = useI18n();
  const [tasks, setTasks] = useState<Task[]>([]);
  const [flash, setFlash] = useState<Flash>(emptyFlash);
  const [query, setQuery] = useState("");
  const [view, setView] = useState<"list" | "form">("list");
  const [editingTask, setEditingTask] = useState<Task | null>(null);
  const [previewMode, setPreviewMode] = useState<"edit" | "preview">("edit");
  const [testArchive, setTestArchive] = useState<File | null>(null);
  const [testArchiveReport, setTestArchiveReport] = useState<TestArchiveImportReport | null>(null);
  const [form, setForm] = useState<TaskFormState>(() => createEmptyTaskForm());
  const filteredTasks = useMemo(
    () => tasks.filter((task) => matchesSearch([
      task.id,
      task.title,
      task.statement,
      task.input_format,
      task.output_format,
      task.contest_ids.join(" "),
      task.current_version_number,
      task.time_limit_ms,
      task.memory_limit_mb,
      task.points,
      task.test_count
    ], query)),
    [tasks, query]
  );

  const load = useCallback(async () => {
    setTasks(await api<Task[]>("/api/tasks"));
  }, [api]);

  useEffect(() => { load().catch((error) => setFlash({ kind: "error", text: errorText(error) })); }, [load]);

  function resetTaskForm() {
    setEditingTask(null);
    setForm(createEmptyTaskForm());
    setTestArchive(null);
    setPreviewMode("edit");
    setView("list");
  }

  function startTaskCreate() {
    setEditingTask(null);
    setForm(createEmptyTaskForm());
    setTestArchive(null);
    setTestArchiveReport(null);
    setPreviewMode("edit");
    setView("form");
  }

  function editTask(task: Task) {
    setEditingTask(task);
    setForm(taskToForm(task));
    setTestArchive(null);
    setPreviewMode("edit");
    setView("form");
  }

  async function submitTaskForm(event: React.FormEvent) {
    event.preventDefault();
    setFlash(emptyFlash);
    setTestArchiveReport(null);
    try {
      const payload = {
        title: form.title,
        statement: form.statement,
        input_format: form.input_format,
        output_format: form.output_format,
        samples: JSON.parse(form.samples || "[]"),
        time_limit_ms: Number(form.time_limit_ms),
        memory_limit_mb: Number(form.memory_limit_mb),
        points: Number(form.points),
        partial_scoring: form.partial_scoring
      };
      const task = editingTask
        ? await api<Task>(`/api/tasks/${editingTask.id}`, { method: "PATCH", body: JSON.stringify(payload) })
        : await api<Task>("/api/tasks", {
          method: "POST",
          body: JSON.stringify({
            ...payload,
            tests: form.test_input || form.test_output ? [{ input_data: form.test_input, output_data: form.test_output, is_sample: form.test_is_sample }] : []
          })
        });
      if (!editingTask && testArchive) {
        const body = new FormData();
        body.append("file", testArchive);
        setTestArchiveReport(await api<TestArchiveImportReport>(`/api/tasks/${task.id}/tests/import-archive`, { method: "POST", body }));
      }
      resetTaskForm();
      await load();
    } catch (error) {
      setFlash({ kind: "error", text: errorText(error) });
    }
  }

  async function deleteTask(task: Task) {
    if (!window.confirm(t("task.deleteConfirm", { name: task.title }))) return;
    setFlash(emptyFlash);
    try {
      await api<void>(`/api/tasks/${task.id}`, { method: "DELETE" });
      await load();
    } catch (error) {
      setFlash({ kind: "error", text: errorText(error) });
    }
  }

  if (view === "form") {
    return (
      <section className="panel">
        <div className="section-title">
          <span className="muted">{t("tab.tasks")}</span>
          <button type="button" onClick={resetTaskForm}>{t("common.backToList")}</button>
        </div>
        <TaskForm
          form={form}
          mode={editingTask ? "edit" : "create"}
          previewMode={previewMode}
          testArchive={testArchive}
          onChange={setForm}
          onPreviewModeChange={setPreviewMode}
          onTestArchiveChange={setTestArchive}
          onCancel={resetTaskForm}
          onSubmit={submitTaskForm}
        />
        <FlashMessage flash={flash} />
      </section>
    );
  }

  return (
    <section className="panel">
      <div className="section-title">
        <div>
          <h3>{t("task.listTitle")}</h3>
          <span className="muted">{t("title.tasksLibrary", { count: tasks.length })}</span>
        </div>
        <button type="button" onClick={startTaskCreate}>{t("common.create")}</button>
      </div>
      <FlashMessage flash={flash} />
      {testArchiveReport && <TestArchiveReportView report={testArchiveReport} />}
      <TableToolbar query={query} onQueryChange={setQuery} total={tasks.length} filtered={filteredTasks.length} placeholder={t("task.search")} />
      <div className="table-wrap">
        <table>
          <thead><tr><th>{t("table.id")}</th><th>{t("table.title")}</th><th>{t("task.version")}</th><th>{t("table.limits")}</th><th>{t("table.points")}</th><th>{t("table.tests")}</th><th></th></tr></thead>
          <tbody>
            {filteredTasks.map((task) => <TaskRow key={task.id} task={task} onEdit={editTask} onDelete={deleteTask} />)}
            {!filteredTasks.length && <tr><td colSpan={7} className="muted">{t("empty.noMatchesText")}</td></tr>}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function TaskForm({
  form,
  mode,
  previewMode,
  testArchive,
  onChange,
  onPreviewModeChange,
  onTestArchiveChange,
  onCancel,
  onSubmit
}: {
  form: TaskFormState;
  mode: "create" | "edit";
  previewMode: "edit" | "preview";
  testArchive: File | null;
  onChange: React.Dispatch<React.SetStateAction<TaskFormState>>;
  onPreviewModeChange: (mode: "edit" | "preview") => void;
  onTestArchiveChange: (file: File | null) => void;
  onCancel: () => void;
  onSubmit: (event: React.FormEvent) => void;
}) {
  const { t } = useI18n();

  return (
    <form className="task-form" onSubmit={onSubmit}>
      <div className="section-title">
        <h3>{mode === "edit" ? t("task.editTitle") : t("task.createTitle")}</h3>
        <div className="row-actions">
          <button type="button" onClick={onCancel}>{t("common.cancel")}</button>
          <button type="submit">{mode === "edit" ? t("common.save") : t("common.create")}</button>
        </div>
      </div>
      <fieldset>
        <legend>{t("task.sectionBasic")}</legend>
        <div className="form-grid">
          <label>{t("table.title")}<input value={form.title} onChange={(event) => onChange({ ...form, title: event.target.value })} required /></label>
          <label>{t("table.points")}<input type="number" step="0.01" value={form.points} onChange={(event) => onChange({ ...form, points: event.target.value })} /></label>
          <label>{t("task.timeLimitMs")}<input type="number" value={form.time_limit_ms} onChange={(event) => onChange({ ...form, time_limit_ms: event.target.value })} /></label>
          <label>{t("task.memoryMb")}<input type="number" value={form.memory_limit_mb} onChange={(event) => onChange({ ...form, memory_limit_mb: event.target.value })} /></label>
          <label className="inline"><input className="check" type="checkbox" checked={form.partial_scoring} onChange={(event) => onChange({ ...form, partial_scoring: event.target.checked })} /> {t("task.partialScoring")}</label>
        </div>
      </fieldset>
      <fieldset>
        <legend>{t("task.sectionStatement")}</legend>
        <div className="segmented">
          <button type="button" className={previewMode === "edit" ? "active" : ""} onClick={() => onPreviewModeChange("edit")}>{t("task.editMarkdown")}</button>
          <button type="button" className={previewMode === "preview" ? "active" : ""} onClick={() => onPreviewModeChange("preview")}>{t("task.previewMarkdown")}</button>
        </div>
        {previewMode === "edit" ? (
          <label>{t("task.statement")}<textarea value={form.statement} onChange={(event) => onChange({ ...form, statement: event.target.value })} required /></label>
        ) : (
          <MarkdownPreview value={form.statement} />
        )}
      </fieldset>
      <fieldset>
        <legend>{t("task.sectionFormats")}</legend>
        <div className="form-grid">
          <label>{t("task.inputFormat")}<textarea className="short" value={form.input_format} onChange={(event) => onChange({ ...form, input_format: event.target.value })} /></label>
          <label>{t("task.outputFormat")}<textarea className="short" value={form.output_format} onChange={(event) => onChange({ ...form, output_format: event.target.value })} /></label>
          <label className="span-2">{t("task.samplesJson")}<textarea className="short code" value={form.samples} onChange={(event) => onChange({ ...form, samples: event.target.value })} /></label>
        </div>
      </fieldset>
      {mode === "create" && (
        <>
          <fieldset>
            <legend>{t("task.sectionFirstTest")}</legend>
            <div className="form-grid">
              <label>{t("task.firstInput")}<textarea className="short code" value={form.test_input} onChange={(event) => onChange({ ...form, test_input: event.target.value })} /></label>
              <label>{t("task.firstOutput")}<textarea className="short code" value={form.test_output} onChange={(event) => onChange({ ...form, test_output: event.target.value })} /></label>
              <label className="inline"><input className="check" type="checkbox" checked={form.test_is_sample} onChange={(event) => onChange({ ...form, test_is_sample: event.target.checked })} /> {t("task.sampleTest")}</label>
            </div>
          </fieldset>
          <fieldset>
            <legend>{t("task.sectionTestArchive")}</legend>
            <label className="file-field">{t("test.archiveUpload")}<input type="file" accept=".zip" onChange={(event) => onTestArchiveChange(event.target.files?.[0] ?? null)} /></label>
            <p className="muted">{testArchive ? testArchive.name : t("task.archiveImportAfterCreate")}</p>
          </fieldset>
        </>
      )}
    </form>
  );
}

function TaskRow({ task, onEdit, onDelete }: { task: Task; onEdit: (task: Task) => void; onDelete: (task: Task) => void }) {
  const { t } = useI18n();
  return (
    <tr>
      <td>{task.id}</td>
      <td>{task.title}</td>
      <td>{task.current_version_number ? `v${task.current_version_number}` : "-"}</td>
      <td>{task.time_limit_ms} ms / {task.memory_limit_mb} MB</td>
      <td>{formatScore(task.points)}</td>
      <td>{task.test_count}{task.partial_scoring ? ` · ${t("task.partialScoring")}` : ""}</td>
      <td className="row-actions">
        <button type="button" onClick={() => onEdit(task)}>{t("common.edit")}</button>
        <button type="button" className="danger" onClick={() => onDelete(task)}>{t("common.delete")}</button>
      </td>
    </tr>
  );
}

function renderInlineMarkdown(text: string): React.ReactNode[] {
  const parts = text.split(/(`[^`]+`|\*\*[^*]+\*\*|\*[^*]+\*)/g).filter(Boolean);
  return parts.map((part, index) => {
    if (part.startsWith("`") && part.endsWith("`")) return <code key={index}>{part.slice(1, -1)}</code>;
    if (part.startsWith("**") && part.endsWith("**")) return <strong key={index}>{part.slice(2, -2)}</strong>;
    if (part.startsWith("*") && part.endsWith("*")) return <em key={index}>{part.slice(1, -1)}</em>;
    return <React.Fragment key={index}>{part}</React.Fragment>;
  });
}

function MarkdownPreview({ value }: { value: string }) {
  const blocks: React.ReactNode[] = [];
  const lines = value.split(/\r?\n/);
  let paragraph: string[] = [];
  let list: string[] = [];
  let code: string[] | null = null;

  function flushParagraph() {
    if (paragraph.length) {
      blocks.push(<p key={blocks.length}>{renderInlineMarkdown(paragraph.join(" "))}</p>);
      paragraph = [];
    }
  }

  function flushList() {
    if (list.length) {
      blocks.push(<ul key={blocks.length}>{list.map((item, index) => <li key={index}>{renderInlineMarkdown(item)}</li>)}</ul>);
      list = [];
    }
  }

  for (const line of lines) {
    if (line.startsWith("```")) {
      flushParagraph();
      flushList();
      if (code === null) {
        code = [];
      } else {
        blocks.push(<pre key={blocks.length}><code>{code.join("\n")}</code></pre>);
        code = null;
      }
      continue;
    }
    if (code !== null) {
      code.push(line);
      continue;
    }
    if (!line.trim()) {
      flushParagraph();
      flushList();
      continue;
    }
    const heading = /^(#{1,3})\s+(.+)$/.exec(line);
    if (heading) {
      flushParagraph();
      flushList();
      const level = heading[1].length;
      const children = renderInlineMarkdown(heading[2]);
      blocks.push(level === 1 ? <h1 key={blocks.length}>{children}</h1> : level === 2 ? <h2 key={blocks.length}>{children}</h2> : <h3 key={blocks.length}>{children}</h3>);
      continue;
    }
    const bullet = /^\s*[-*]\s+(.+)$/.exec(line);
    if (bullet) {
      flushParagraph();
      list.push(bullet[1]);
      continue;
    }
    flushList();
    paragraph.push(line.trim());
  }
  flushParagraph();
  flushList();
  if (code !== null) blocks.push(<pre key={blocks.length}><code>{code.join("\n")}</code></pre>);
  return <div className="markdown-preview">{blocks.length ? blocks : <p className="muted">Markdown</p>}</div>;
}

function TestArchiveReportView({ report }: { report: TestArchiveImportReport }) {
  const { t } = useI18n();
  return (
    <div className="report">
      <div className="stat"><strong>{report.created}</strong><span>{t("common.created")}</span></div>
      <div className="stat"><strong>{report.skipped.length}</strong><span>{t("common.skipped")}</span></div>
      <div className="stat"><strong>{report.errors.length}</strong><span>{t("common.errors")}</span></div>
      {(report.skipped.length > 0 || report.errors.length > 0) && (
        <table>
          <tbody>
            {report.skipped.map((item, index) => <tr key={`s-${index}`}><td><span className="pill warn">{t("common.skipped")}</span></td><td>{item}</td></tr>)}
            {report.errors.map((item, index) => <tr key={`e-${index}`}><td><span className="pill warn">{t("common.errors")}</span></td><td>{item}</td></tr>)}
          </tbody>
        </table>
      )}
    </div>
  );
}

function PackagesAdmin({ api, token, onChanged }: { api: ApiClient; token: string; onChanged: () => void }) {
  const { t } = useI18n();
  const [tasks, setTasks] = useState<Task[]>([]);
  const [contests, setContests] = useState<Contest[]>([]);
  const [selectedTaskId, setSelectedTaskId] = useState<number | null>(null);
  const [selectedContestId, setSelectedContestId] = useState<number | null>(null);
  const [taskReport, setTaskReport] = useState<PackageImportReport | null>(null);
  const [contestReport, setContestReport] = useState<PackageImportReport | null>(null);
  const [flash, setFlash] = useState<Flash>(emptyFlash);

  const load = useCallback(async () => {
    const [nextTasks, nextContests] = await Promise.all([api<Task[]>("/api/tasks"), api<Contest[]>("/api/contests")]);
    setTasks(nextTasks);
    setContests(nextContests);
    setSelectedTaskId((current) => current && nextTasks.some((task) => task.id === current) ? current : nextTasks[0]?.id ?? null);
    setSelectedContestId((current) => current && nextContests.some((contest) => contest.id === current) ? current : nextContests[0]?.id ?? null);
  }, [api]);

  useEffect(() => { load().catch((error) => setFlash({ kind: "error", text: errorText(error) })); }, [load]);

  async function downloadPackage(path: string) {
    setFlash(emptyFlash);
    try {
      const response = await fetch(`${API_BASE}${path}`, { headers: { Authorization: `Bearer ${token}` } });
      if (!response.ok) {
        const body = await response.json().catch(() => ({ detail: response.statusText }));
        throw new Error(body.detail || t("package.exportFailed"));
      }
      const blob = await response.blob();
      const disposition = response.headers.get("Content-Disposition") || "";
      const match = /filename="([^"]+)"/.exec(disposition);
      const filename = match?.[1] || "package.zip";
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      link.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      setFlash({ kind: "error", text: errorText(error) });
    }
  }

  async function importPackage(event: React.ChangeEvent<HTMLInputElement>, kind: "task" | "contest") {
    const file = event.target.files?.[0];
    if (!file) return;
    setFlash(emptyFlash);
    if (kind === "task") setTaskReport(null);
    if (kind === "contest") setContestReport(null);
    const body = new FormData();
    body.append("file", file);
    try {
      const path = kind === "task" ? "/api/tasks/import-package" : "/api/contests/import-package";
      const report = await api<PackageImportReport>(path, { method: "POST", body });
      if (kind === "task") setTaskReport(report);
      if (kind === "contest") setContestReport(report);
      await load();
      onChanged();
    } catch (error) {
      setFlash({ kind: "error", text: errorText(error) });
    } finally {
      event.target.value = "";
    }
  }

  return (
    <section className="panel">
      <Header title={t("tab.packages")} subtitle={t("package.subtitle")} />
      <div className="package-grid">
        <section>
          <h3>{t("package.tasks")}</h3>
          <div className="form-grid">
            <label>{t("table.task")}<select value={selectedTaskId ?? ""} onChange={(event) => setSelectedTaskId(Number(event.target.value) || null)}>{tasks.map((task) => <option key={task.id} value={task.id}>{task.id}: {task.title}</option>)}</select></label>
            <button type="button" disabled={!selectedTaskId} onClick={() => selectedTaskId && downloadPackage(`/api/tasks/${selectedTaskId}/package`)}>{t("package.exportTask")}</button>
            <label>{t("package.importTask")}<input type="file" accept=".zip" onChange={(event) => importPackage(event, "task")} /></label>
          </div>
          {taskReport && <PackageReport report={taskReport} />}
        </section>
        <section>
          <h3>{t("package.contests")}</h3>
          <div className="form-grid">
            <label>{t("table.contest")}<select value={selectedContestId ?? ""} onChange={(event) => setSelectedContestId(Number(event.target.value) || null)}>{contests.map((contest) => <option key={contest.id} value={contest.id}>{contest.id}: {contest.title}</option>)}</select></label>
            <button type="button" disabled={!selectedContestId} onClick={() => selectedContestId && downloadPackage(`/api/contests/${selectedContestId}/package`)}>{t("package.exportContest")}</button>
            <label>{t("package.importContest")}<input type="file" accept=".zip" onChange={(event) => importPackage(event, "contest")} /></label>
          </div>
          {contestReport && <PackageReport report={contestReport} />}
        </section>
      </div>
      <p className="muted">{t("package.note")}</p>
      <FlashMessage flash={flash} />
    </section>
  );
}

function PackageReport({ report }: { report: PackageImportReport }) {
  const { t } = useI18n();
  return (
    <div className="report package-report">
      <div className="stat"><strong>{report.created_tasks}</strong><span>{t("package.createdTasks")}</span></div>
      <div className="stat"><strong>{report.created_tests}</strong><span>{t("package.createdTests")}</span></div>
      <div className="stat"><strong>{report.contest_id ?? "-"}</strong><span>{t("package.contestId")}</span></div>
    </div>
  );
}

function TestsAdmin({ api }: { api: ApiClient }) {
  const { t } = useI18n();
  const [tasks, setTasks] = useState<Task[]>([]);
  const [tests, setTests] = useState<TaskTest[]>([]);
  const [selectedTaskId, setSelectedTaskId] = useState<number | null>(null);
  const [archiveReport, setArchiveReport] = useState<TestArchiveImportReport | null>(null);
  const [flash, setFlash] = useState<Flash>(emptyFlash);
  const [form, setForm] = useState({ input_data: "", output_data: "", is_sample: false, points: "", group_name: "" });

  const loadTasks = useCallback(async () => {
    const next = await api<Task[]>("/api/tasks");
    setTasks(next);
    setSelectedTaskId((current) => current && next.some((task) => task.id === current) ? current : next[0]?.id ?? null);
  }, [api]);
  const loadTests = useCallback(async (taskId: number | null) => {
    if (!taskId) {
      setTests([]);
      return;
    }
    setTests(await api<TaskTest[]>(`/api/tasks/${taskId}/tests`));
  }, [api]);

  useEffect(() => { loadTasks().catch((error) => setFlash({ kind: "error", text: errorText(error) })); }, [loadTasks]);
  useEffect(() => { loadTests(selectedTaskId).catch((error) => setFlash({ kind: "error", text: errorText(error) })); }, [loadTests, selectedTaskId]);

  async function createTest(event: React.FormEvent) {
    event.preventDefault();
    if (!selectedTaskId) return;
    setFlash(emptyFlash);
    try {
      await api<TaskTest>(`/api/tasks/${selectedTaskId}/tests`, {
        method: "POST",
        body: JSON.stringify({
          ...form,
          points: form.points.trim() ? Number(form.points) : null,
          group_name: form.group_name.trim() || null
        })
      });
      setForm({ input_data: "", output_data: "", is_sample: false, points: "", group_name: "" });
      await loadTests(selectedTaskId);
    } catch (error) {
      setFlash({ kind: "error", text: errorText(error) });
    }
  }

  async function saveTest(test: TaskTest, patch: Partial<TaskTest>) {
    setFlash(emptyFlash);
    try {
      await api<TaskTest>(`/api/tests/${test.id}`, { method: "PATCH", body: JSON.stringify(patch) });
      await loadTests(selectedTaskId);
    } catch (error) {
      setFlash({ kind: "error", text: errorText(error) });
    }
  }

  async function deleteTest(test: TaskTest) {
    if (!window.confirm(t("test.deleteConfirm", { id: test.id }))) return;
    setFlash(emptyFlash);
    try {
      await api<void>(`/api/tests/${test.id}`, { method: "DELETE" });
      await loadTests(selectedTaskId);
    } catch (error) {
      setFlash({ kind: "error", text: errorText(error) });
    }
  }

  async function importArchive(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file || !selectedTaskId) return;
    setFlash(emptyFlash);
    setArchiveReport(null);
    const body = new FormData();
    body.append("file", file);
    try {
      const report = await api<TestArchiveImportReport>(`/api/tasks/${selectedTaskId}/tests/import-archive`, { method: "POST", body });
      setArchiveReport(report);
      await loadTests(selectedTaskId);
      await loadTasks();
    } catch (error) {
      setFlash({ kind: "error", text: errorText(error) });
    } finally {
      event.target.value = "";
    }
  }

  return (
    <section className="panel">
      <Header title={t("tab.tests")} subtitle={t("title.testsInTask", { count: tests.length })} />
      <div className="form-grid">
        <label>{t("table.task")}<select value={selectedTaskId ?? ""} onChange={(event) => setSelectedTaskId(Number(event.target.value) || null)}>{tasks.map((task) => <option key={task.id} value={task.id}>{task.id}: {task.title}</option>)}</select></label>
        <label>{t("test.archiveUpload")}<input type="file" accept=".zip" disabled={!selectedTaskId} onChange={importArchive} /></label>
      </div>
      <form className="task-form test-form" onSubmit={createTest}>
        <label>{t("table.input")}<textarea className="short code" value={form.input_data} onChange={(event) => setForm({ ...form, input_data: event.target.value })} /></label>
        <label>{t("table.output")}<textarea className="short code" value={form.output_data} onChange={(event) => setForm({ ...form, output_data: event.target.value })} /></label>
        <label>{t("table.points")}<input type="number" step="0.01" value={form.points} onChange={(event) => setForm({ ...form, points: event.target.value })} placeholder={t("test.pointsAuto")} /></label>
        <label>{t("test.groupName")}<input value={form.group_name} onChange={(event) => setForm({ ...form, group_name: event.target.value })} /></label>
        <label className="inline"><input className="check" type="checkbox" checked={form.is_sample} onChange={(event) => setForm({ ...form, is_sample: event.target.checked })} /> {t("task.sample")}</label>
        <button type="submit" disabled={!selectedTaskId}>{t("common.create")}</button>
      </form>
      <FlashMessage flash={flash} />
      {archiveReport && <TestArchiveReportView report={archiveReport} />}
      <div className="table-wrap">
        <table>
          <thead><tr><th>{t("table.id")}</th><th>{t("table.sample")}</th><th>{t("table.points")}</th><th>{t("test.groupName")}</th><th>{t("table.input")}</th><th>{t("table.output")}</th><th></th></tr></thead>
          <tbody>{tests.map((test) => <TestRow key={test.id} test={test} onSave={saveTest} onDelete={deleteTest} />)}</tbody>
        </table>
      </div>
    </section>
  );
}

function TestRow({ test, onSave, onDelete }: { test: TaskTest; onSave: (test: TaskTest, patch: Partial<TaskTest>) => void; onDelete: (test: TaskTest) => void }) {
  const { t } = useI18n();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState({
    input_data: test.input_data,
    output_data: test.output_data,
    is_sample: test.is_sample,
    points: test.points === null ? "" : String(test.points),
    group_name: test.group_name ?? ""
  });
  useEffect(() => setDraft({
    input_data: test.input_data,
    output_data: test.output_data,
    is_sample: test.is_sample,
    points: test.points === null ? "" : String(test.points),
    group_name: test.group_name ?? ""
  }), [test]);

  return (
    <tr className={editing ? "editing" : ""}>
      <td>{test.id}</td>
      <td>{editing ? <input className="check" type="checkbox" checked={draft.is_sample} onChange={(event) => setDraft({ ...draft, is_sample: event.target.checked })} /> : test.is_sample ? t("common.yes") : t("common.no")}</td>
      <td>{editing ? <input type="number" step="0.01" value={draft.points} onChange={(event) => setDraft({ ...draft, points: event.target.value })} placeholder={t("test.pointsAuto")} /> : test.points ?? "-"}</td>
      <td>{editing ? <input value={draft.group_name} onChange={(event) => setDraft({ ...draft, group_name: event.target.value })} /> : test.group_name || "-"}</td>
      <td>{editing ? <textarea className="short code" value={draft.input_data} onChange={(event) => setDraft({ ...draft, input_data: event.target.value })} /> : <pre>{test.input_data}</pre>}</td>
      <td>{editing ? <textarea className="short code" value={draft.output_data} onChange={(event) => setDraft({ ...draft, output_data: event.target.value })} /> : <pre>{test.output_data}</pre>}</td>
      <td className="row-actions">
        {editing ? (
          <>
            <button onClick={() => {
              onSave(test, {
                input_data: draft.input_data,
                output_data: draft.output_data,
                is_sample: draft.is_sample,
                points: draft.points.trim() ? Number(draft.points) : null,
                group_name: draft.group_name.trim() || null
              });
              setEditing(false);
            }}>{t("common.save")}</button>
            <button onClick={() => setEditing(false)}>{t("common.cancel")}</button>
          </>
        ) : (
          <>
            <button onClick={() => setEditing(true)}>{t("common.edit")}</button>
            <button className="danger" onClick={() => onDelete(test)}>{t("common.delete")}</button>
          </>
        )}
      </td>
    </tr>
  );
}

function SubmissionsAdmin({ api, siteTimezone }: { api: ApiClient; siteTimezone: string }) {
  const { t } = useI18n();
  const [contests, setContests] = useState<Contest[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [users, setUsers] = useState<User[]>([]);
  const [submissions, setSubmissions] = useState<Submission[]>([]);
  const [selectedContestId, setSelectedContestId] = useState<number | "all">("all");
  const [selectedSubmissionId, setSelectedSubmissionId] = useState<number | null>(null);
  const [detail, setDetail] = useState<SubmissionDetail | null>(null);
  const [flash, setFlash] = useState<Flash>(emptyFlash);
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const filteredSubmissions = useMemo(
    () => submissions.filter((submission) => matchesSearch([
      submission.id,
      contestLabel(submission.contest_id),
      taskLabel(submission.task_id),
      userLabel(submission.user_id),
      submission.task_version_id,
      submission.team_id,
      submission.language,
      submission.verdict,
      t(`verdict.${submission.verdict}`),
      submission.score
    ], query)),
    [submissions, contests, tasks, users, query, t]
  );
  const totalPages = Math.max(1, Math.ceil(filteredSubmissions.length / pageSize));
  const currentPage = Math.min(page, totalPages);
  const paginatedSubmissions = filteredSubmissions.slice((currentPage - 1) * pageSize, currentPage * pageSize);

  const loadLookups = useCallback(async () => {
    const [nextContests, nextTasks, nextUsers] = await Promise.all([
      api<Contest[]>("/api/contests"),
      api<Task[]>("/api/tasks"),
      api<User[]>("/api/users")
    ]);
    setContests(nextContests);
    setTasks(nextTasks);
    setUsers(nextUsers);
  }, [api]);
  const loadSubmissions = useCallback(async () => {
    const query = selectedContestId === "all" ? "" : `?contest_id=${selectedContestId}`;
    setSubmissions(await api<Submission[]>(`/api/submissions${query}`));
  }, [api, selectedContestId]);

  function contestLabel(contestId: number) {
    const contest = contests.find((item) => item.id === contestId);
    return contest ? contest.title : `#${contestId}`;
  }

  function taskLabel(taskId: number) {
    const task = tasks.find((item) => item.id === taskId);
    return task ? task.title : `#${taskId}`;
  }

  function userLabel(userId: number) {
    const user = users.find((item) => item.id === userId);
    return user ? `${user.display_name || user.username} (${user.username})` : `#${userId}`;
  }

  useEffect(() => { loadLookups().catch((error) => setFlash({ kind: "error", text: errorText(error) })); }, [loadLookups]);
  useEffect(() => {
    loadSubmissions().catch((error) => setFlash({ kind: "error", text: errorText(error) }));
    const interval = window.setInterval(() => loadSubmissions().catch(console.error), 2000);
    return () => window.clearInterval(interval);
  }, [loadSubmissions]);
  useEffect(() => { setPage(1); }, [query, selectedContestId]);
  useEffect(() => { if (page > totalPages) setPage(totalPages); }, [page, totalPages]);
  useEffect(() => {
    if (!selectedSubmissionId) {
      setDetail(null);
      return;
    }
    api<SubmissionDetail>(`/api/admin/submissions/${selectedSubmissionId}`)
      .then(setDetail)
      .catch((error) => setFlash({ kind: "error", text: errorText(error) }));
  }, [api, selectedSubmissionId, submissions]);

  async function rejudgeSubmission(submissionId: number) {
    if (!window.confirm(t("submission.rejudgeConfirm", { id: submissionId }))) return;
    setFlash(emptyFlash);
    try {
      const nextDetail = await api<SubmissionDetail>(`/api/admin/submissions/${submissionId}/rejudge`, { method: "POST" });
      if (selectedSubmissionId === submissionId) setDetail(nextDetail);
      await loadSubmissions();
      setFlash({ kind: "ok", text: t("submission.rejudged", { id: submissionId }) });
    } catch (error) {
      setFlash({ kind: "error", text: errorText(error) });
    }
  }

  return (
    <section className="panel">
      <Header title={t("tab.submissions")} subtitle={t("title.submissionsPolling")} />
      <label className="selector">
        {t("table.contest")}
        <select value={selectedContestId} onChange={(event) => setSelectedContestId(event.target.value === "all" ? "all" : Number(event.target.value))}>
          <option value="all">{t("common.allContests")}</option>
          {contests.map((contest) => <option key={contest.id} value={contest.id}>{contest.id}: {contest.title}</option>)}
        </select>
      </label>
      <FlashMessage flash={flash} />
      <TableToolbar query={query} onQueryChange={setQuery} total={submissions.length} filtered={filteredSubmissions.length} placeholder={t("submission.search")} />
      <PaginationControls page={currentPage} totalPages={totalPages} pageSize={pageSize} total={filteredSubmissions.length} onPageChange={setPage} onPageSizeChange={(nextPageSize) => { setPageSize(nextPageSize); setPage(1); }} />
      <div className="split">
        <div className="table-wrap">
          <table>
            <thead><tr><th>{t("table.id")}</th><th></th><th>{t("table.contest")}</th><th>{t("table.task")}</th><th>{t("table.user")}</th><th>{t("table.lang")}</th><th>{t("table.verdict")}</th><th>{t("table.score")}</th><th>{t("table.created")}</th></tr></thead>
            <tbody>
              {paginatedSubmissions.map((submission) => (
                <tr key={submission.id} className={submission.id === selectedSubmissionId ? "selected" : ""} onClick={() => setSelectedSubmissionId(submission.id)}>
                  <td>#{submission.id}</td>
                  <td className="row-actions">
                    <button
                      type="button"
                      className="small icon-button"
                      title={t("submission.rejudge")}
                      aria-label={t("submission.rejudge")}
                      onClick={(event) => { event.stopPropagation(); rejudgeSubmission(submission.id); }}
                    >
                      {t("submission.rejudgeShort")}
                    </button>
                  </td>
                  <td>{contestLabel(submission.contest_id)}</td><td>{taskLabel(submission.task_id)}</td><td>{userLabel(submission.user_id)}</td><td>{submission.language}</td>
                  <td><span className={verdictClass(submission.verdict)}>{t(`verdict.${submission.verdict}`)}</span></td><td>{formatScore(submission.score)}</td><td>{formatDate(submission.created_at, siteTimezone)}</td>
                </tr>
              ))}
              {!filteredSubmissions.length && <tr><td colSpan={9} className="muted">{t("empty.noMatchesText")}</td></tr>}
            </tbody>
          </table>
        </div>
        <div className="detail-stack">
          {detail && (
            <button type="button" className="icon-button" title={t("submission.rejudge")} aria-label={t("submission.rejudge")} onClick={() => rejudgeSubmission(detail.id)}>
              {t("submission.rejudgeShort")}
            </button>
          )}
          <SubmissionDetailView
            detail={detail}
            siteTimezone={siteTimezone}
            labels={detail ? { contest: contestLabel(detail.contest_id), task: taskLabel(detail.task_id), user: userLabel(detail.user_id) } : undefined}
          />
        </div>
      </div>
    </section>
  );
}
