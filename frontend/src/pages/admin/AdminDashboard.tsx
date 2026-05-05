import React, { useCallback, useEffect, useState } from "react";
import { API_BASE } from "../../api/client";
import { FlashMessage, Header, SubmissionDetailView } from "../../components/shared";
import { useI18n } from "../../i18n";
import type { AdminStats, ApiClient, Clarification, ClarificationStatus, ClarificationVisibility, Contest, ContestStatus, Flash, ImportReport, JudgerEvent, JudgerWorker, PackageImportReport, ParticipationMode, Role, Submission, SubmissionDetail, Task, TaskTest, Team, TestArchiveImportReport, TimeMode, User } from "../../types";
import { emptyFlash, errorText, formatDate, formatScore, fromLocalInputValue, toLocalInputValue, verdictClass } from "../../utils/format";

export function AdminDashboard({ api, token, reloadContests }: { api: ApiClient; token: string; reloadContests: () => void }) {
  const { t } = useI18n();
  const [tab, setTab] = useState<"status" | "users" | "import" | "teams" | "contests" | "tasks" | "packages" | "tests" | "submissions" | "clarifications">("status");

  return (
    <div className="admin-shell">
      <nav className="tabs">
        {[
          ["status", t("tab.status")],
          ["users", t("tab.users")],
          ["import", t("tab.import")],
          ["teams", t("tab.teams")],
          ["contests", t("tab.contests")],
          ["tasks", t("tab.tasks")],
          ["packages", t("tab.packages")],
          ["tests", t("tab.tests")],
          ["submissions", t("tab.submissions")],
          ["clarifications", t("tab.clarifications")]
        ].map(([id, label]) => (
          <button key={id} className={tab === id ? "active" : ""} onClick={() => setTab(id as typeof tab)}>
            {label}
          </button>
        ))}
      </nav>
      {tab === "status" && <StatusAdmin api={api} />}
      {tab === "users" && <UsersAdmin api={api} />}
      {tab === "import" && <ImportUsersAdmin token={token} />}
      {tab === "teams" && <TeamsAdmin api={api} />}
      {tab === "contests" && <ContestsAdmin api={api} onChanged={reloadContests} />}
      {tab === "tasks" && <TasksAdmin api={api} />}
      {tab === "packages" && <PackagesAdmin api={api} token={token} onChanged={reloadContests} />}
      {tab === "tests" && <TestsAdmin api={api} />}
      {tab === "submissions" && <SubmissionsAdmin api={api} />}
      {tab === "clarifications" && <ClarificationsAdmin api={api} />}
    </div>
  );
}

function StatusAdmin({ api }: { api: ApiClient }) {
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
      <Header title={t("tab.status")} subtitle={stats ? t("status.lastUpdated", { time: formatDate(stats.system.server_time) }) : t("status.loading")} />
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
          <JudgerWorkersTable judgers={judgers} />
          <JudgerEventsTable events={judgerEvents} />
          <StatusTable title={t("status.runningJudgers")} rows={runningJudgers} empty={t("common.empty")} />
          <StatusTable title={t("status.finishedJudgers24h")} rows={finishedJudgers} empty={t("common.empty")} />
        </div>
      )}
    </section>
  );
}

function JudgerWorkersTable({ judgers }: { judgers: JudgerWorker[] }) {
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
              <td>{formatDate(judger.last_seen_at)}</td>
              <td>{judger.supported_languages.length}</td>
            </tr>
          )) : <tr><td colSpan={6} className="muted">{t("common.empty")}</td></tr>}
        </tbody>
      </table>
    </div>
  );
}

function JudgerEventsTable({ events }: { events: JudgerEvent[] }) {
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
              <td>{formatDate(event.created_at)}</td>
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

function ClarificationsAdmin({ api }: { api: ApiClient }) {
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
  onUpdate
}: {
  clarification: Clarification;
  contest?: Contest;
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
          <span>{formatDate(clarification.created_at)}</span>
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

function UsersAdmin({ api }: { api: ApiClient }) {
  const { t } = useI18n();
  const [users, setUsers] = useState<User[]>([]);
  const [flash, setFlash] = useState<Flash>(emptyFlash);
  const [form, setForm] = useState({ username: "", password: "", display_name: "", role: "participant" as Role });

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
      <div className="table-wrap">
        <table>
          <thead><tr><th>ID</th><th>{t("table.username")}</th><th>{t("table.name")}</th><th>{t("table.role")}</th><th>{t("table.active")}</th><th>{t("table.created")}</th><th></th></tr></thead>
          <tbody>{users.map((user) => <UserRow key={user.id} user={user} onSave={updateUser} onDelete={deleteUser} />)}</tbody>
        </table>
      </div>
    </section>
  );
}

function UserRow({ user, onSave, onDelete }: { user: User; onSave: (user: User, patch: Partial<User> & { password?: string }) => void; onDelete: (user: User) => void }) {
  const { t } = useI18n();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState({ ...user, password: "" });

  useEffect(() => setDraft({ ...user, password: "" }), [user]);

  if (!editing) {
    return (
      <tr>
        <td>{user.id}</td><td>{user.username}</td><td>{user.display_name}</td><td>{t(`role.${user.role}`)}</td><td>{user.is_active ? t("common.yes") : t("common.no")}</td><td>{formatDate(user.created_at)}</td>
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

function ImportUsersAdmin({ token }: { token: string }) {
  const { t } = useI18n();
  const [report, setReport] = useState<ImportReport | null>(null);
  const [flash, setFlash] = useState<Flash>(emptyFlash);

  async function importUsers(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    setFlash(emptyFlash);
    setReport(null);
    const body = new FormData();
    body.append("file", file);
    try {
      const response = await fetch(`${API_BASE}/api/users/import`, { method: "POST", headers: { Authorization: `Bearer ${token}` }, body });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || t("import.importFailed"));
      setReport(data);
    } catch (error) {
      setFlash({ kind: "error", text: errorText(error) });
    } finally {
      event.target.value = "";
    }
  }

  return (
    <section className="panel">
      <Header title={t("tab.import")} subtitle="CSV, JSON, YAML" />
      <label className="file-field"><input type="file" accept=".csv,.json,.yml,.yaml" onChange={importUsers} /></label>
      <p className="muted">{t("import.expectedFields")}</p>
      <FlashMessage flash={flash} />
      {report && (
        <div className="report">
          <div className="stat"><strong>{report.created}</strong><span>{t("common.created")}</span></div>
          <div className="stat"><strong>{report.skipped}</strong><span>{t("common.skipped")}</span></div>
          <div className="stat"><strong>{report.errors.length}</strong><span>{t("common.errors")}</span></div>
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

function TeamsAdmin({ api }: { api: ApiClient }) {
  const { t } = useI18n();
  const [teams, setTeams] = useState<Team[]>([]);
  const [users, setUsers] = useState<User[]>([]);
  const [flash, setFlash] = useState<Flash>(emptyFlash);
  const [form, setForm] = useState({ name: "", user_ids: [] as number[] });

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
      <form className="form-grid" onSubmit={createTeam}>
        <label>{t("table.name")}<input value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} required /></label>
        <div className="span-2">
          <SearchPicker label={t("team.members")} items={userPickerItems(users.filter((user) => user.role === "participant"))} selectedIds={form.user_ids} onChange={(user_ids) => setForm({ ...form, user_ids })} placeholder={t("team.searchUsers")} emptyText={t("common.none")} />
        </div>
        <button type="submit">{t("common.create")}</button>
      </form>
      <FlashMessage flash={flash} />
      <div className="table-wrap">
        <table>
          <thead><tr><th>{t("table.id")}</th><th>{t("table.name")}</th><th>{t("table.members")}</th><th>{t("table.created")}</th><th></th></tr></thead>
          <tbody>{teams.map((team) => <TeamRow key={team.id} team={team} users={users.filter((user) => user.role === "participant")} onSave={saveTeam} onDelete={deleteTeam} />)}</tbody>
        </table>
      </div>
    </section>
  );
}

function TeamRow({ team, users, onSave, onDelete }: { team: Team; users: User[]; onSave: (team: Team, patch: { name: string; user_ids: number[] }) => void; onDelete: (team: Team) => void }) {
  const { t } = useI18n();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState({ name: team.name, user_ids: team.member_ids });
  useEffect(() => setDraft({ name: team.name, user_ids: team.member_ids }), [team]);

  return (
    <tr className={editing ? "editing" : ""}>
      <td>{team.id}</td>
      <td>{editing ? <input value={draft.name} onChange={(event) => setDraft({ ...draft, name: event.target.value })} /> : team.name}</td>
      <td>{editing ? <SearchPicker label={t("team.members")} items={userPickerItems(users)} selectedIds={draft.user_ids} onChange={(user_ids) => setDraft({ ...draft, user_ids })} placeholder={t("team.searchUsers")} emptyText={t("common.none")} /> : formatUserIds(team.member_ids, users) || "-"}</td>
      <td>{formatDate(team.created_at)}</td>
      <td className="row-actions">
        {editing ? (
          <>
            <button onClick={() => { onSave(team, { name: draft.name, user_ids: draft.user_ids }); setEditing(false); }}>{t("common.save")}</button>
            <button onClick={() => setEditing(false)}>{t("common.cancel")}</button>
          </>
        ) : (
          <>
            <button onClick={() => setEditing(true)}>{t("common.edit")}</button>
            <button className="danger" onClick={() => onDelete(team)}>{t("common.delete")}</button>
          </>
        )}
      </td>
    </tr>
  );
}

function ContestsAdmin({ api, onChanged }: { api: ApiClient; onChanged: () => void }) {
  const { t } = useI18n();
  const [contests, setContests] = useState<Contest[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [users, setUsers] = useState<User[]>([]);
  const [teams, setTeams] = useState<Team[]>([]);
  const [contestTaskIds, setContestTaskIds] = useState<Record<number, number[]>>({});
  const [contestParticipantIds, setContestParticipantIds] = useState<Record<number, number[]>>({});
  const [contestTeamIds, setContestTeamIds] = useState<Record<number, number[]>>({});
  const [flash, setFlash] = useState<Flash>(emptyFlash);
  const now = new Date();
  const later = new Date(Date.now() + 3 * 60 * 60_000);
  const [form, setForm] = useState({
    title: "",
    description: "",
    status: "draft" as ContestStatus,
    is_public: false,
    time_mode: "fixed" as TimeMode,
    participation_mode: "individual" as ParticipationMode,
    starts_at: toLocalInputValue(now.toISOString()),
    ends_at: toLocalInputValue(later.toISOString()),
    individual_duration_minutes: "180",
    task_ids: [] as number[],
    participant_ids: [] as number[],
    team_ids: [] as number[]
  });

  const load = useCallback(async () => {
    const [nextContests, nextTasks, nextUsers, nextTeams] = await Promise.all([api<Contest[]>("/api/contests"), api<Task[]>("/api/tasks"), api<User[]>("/api/users"), api<Team[]>("/api/teams")]);
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
  }, [api]);
  useEffect(() => { load().catch((error) => setFlash({ kind: "error", text: errorText(error) })); }, [load]);

  async function createContest(event: React.FormEvent) {
    event.preventDefault();
    setFlash(emptyFlash);
    try {
      const contest = await api<Contest>("/api/contests", {
        method: "POST",
        body: JSON.stringify({
          ...form,
          task_ids: undefined,
          participant_ids: undefined,
          team_ids: undefined,
          starts_at: fromLocalInputValue(form.starts_at),
          ends_at: fromLocalInputValue(form.ends_at),
          individual_duration_minutes: form.time_mode === "individual" ? Number(form.individual_duration_minutes) : null
        })
      });
      if (form.task_ids.length) {
        await api<Task[]>(`/api/contests/${contest.id}/tasks`, { method: "PUT", body: JSON.stringify({ task_ids: form.task_ids }) });
      }
      const participantIds = form.participant_ids;
      if (participantIds.length) {
        await api<User[]>(`/api/contests/${contest.id}/participants`, { method: "PUT", body: JSON.stringify({ user_ids: participantIds }) });
      }
      const teamIds = form.team_ids;
      if (teamIds.length) {
        await api<Team[]>(`/api/contests/${contest.id}/teams`, { method: "PUT", body: JSON.stringify({ team_ids: teamIds }) });
      }
      setForm({ ...form, title: "", description: "", task_ids: [], participant_ids: [], team_ids: [] });
      await load();
      onChanged();
    } catch (error) {
      setFlash({ kind: "error", text: errorText(error) });
    }
  }

  async function saveContest(contest: Contest, patch: Partial<Contest>) {
    setFlash(emptyFlash);
    try {
      await api<Contest>(`/api/contests/${contest.id}`, { method: "PATCH", body: JSON.stringify(patch) });
      await load();
      onChanged();
    } catch (error) {
      setFlash({ kind: "error", text: errorText(error) });
    }
  }

  async function saveContestTasks(contest: Contest, taskIds: number[]) {
    setFlash(emptyFlash);
    try {
      await api<Task[]>(`/api/contests/${contest.id}/tasks`, { method: "PUT", body: JSON.stringify({ task_ids: taskIds }) });
      await load();
      onChanged();
    } catch (error) {
      setFlash({ kind: "error", text: errorText(error) });
    }
  }

  async function saveContestParticipants(contest: Contest, participantIds: number[]) {
    setFlash(emptyFlash);
    try {
      await api<User[]>(`/api/contests/${contest.id}/participants`, { method: "PUT", body: JSON.stringify({ user_ids: participantIds }) });
      await load();
      onChanged();
    } catch (error) {
      setFlash({ kind: "error", text: errorText(error) });
    }
  }

  async function saveContestTeams(contest: Contest, teamIds: number[]) {
    setFlash(emptyFlash);
    try {
      await api<Team[]>(`/api/contests/${contest.id}/teams`, { method: "PUT", body: JSON.stringify({ team_ids: teamIds }) });
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
      await load();
      onChanged();
    } catch (error) {
      setFlash({ kind: "error", text: errorText(error) });
    }
  }

  function toggleFormTask(taskId: number) {
    setForm((current) => ({
      ...current,
      task_ids: current.task_ids.includes(taskId) ? current.task_ids.filter((id) => id !== taskId) : [...current.task_ids, taskId]
    }));
  }

  return (
    <section className="panel">
      <Header title={t("tab.contests")} subtitle={t("title.contestsCount", { count: contests.length })} />
      <form className="task-form" onSubmit={createContest}>
        <fieldset>
          <legend>{t("contest.sectionBasic")}</legend>
          <div className="form-grid">
            <label>{t("table.title")}<input value={form.title} onChange={(event) => setForm({ ...form, title: event.target.value })} required /></label>
            <label>{t("table.status")}<select value={form.status} onChange={(event) => setForm({ ...form, status: event.target.value as ContestStatus })}>{contestStatuses.map((item) => <option key={item} value={item}>{t(`status.${item}`)}</option>)}</select></label>
            <label>{t("contest.participationMode")}<select value={form.participation_mode} onChange={(event) => setForm({ ...form, participation_mode: event.target.value as ParticipationMode })}><option value="individual">{t("common.individual")}</option><option value="team">{t("common.team")}</option></select></label>
            <label className="span-2">{t("table.description")}<textarea className="short" value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} /></label>
          </div>
        </fieldset>
        <fieldset>
          <legend>{t("contest.sectionSchedule")}</legend>
          <div className="form-grid">
            <label>{t("table.mode")}<select value={form.time_mode} onChange={(event) => setForm({ ...form, time_mode: event.target.value as TimeMode })}><option value="fixed">{t("common.fixed")}</option><option value="individual">{t("common.individual")}</option></select></label>
            <label>{t("table.starts")}<input type="datetime-local" value={form.starts_at} onChange={(event) => setForm({ ...form, starts_at: event.target.value })} required /></label>
            <label>{t("table.ends")}<input type="datetime-local" value={form.ends_at} onChange={(event) => setForm({ ...form, ends_at: event.target.value })} required /></label>
            <label>{t("table.minutes")}<input type="number" value={form.individual_duration_minutes} onChange={(event) => setForm({ ...form, individual_duration_minutes: event.target.value })} /></label>
          </div>
        </fieldset>
        <fieldset>
          <legend>{t("contest.sectionTasks")}</legend>
          <div className="checklist">{tasks.map((task) => (
            <label key={task.id} className="inline"><input className="check" type="checkbox" checked={form.task_ids.includes(task.id)} onChange={() => toggleFormTask(task.id)} /> #{task.id} {task.title}</label>
          ))}</div>
        </fieldset>
        <fieldset>
          <legend>{t("contest.sectionAccess")}</legend>
          <label className="inline"><input className="check" type="checkbox" checked={form.is_public} onChange={(event) => setForm({ ...form, is_public: event.target.checked })} /> {t("contest.publicAccess")}</label>
          <div className="access-grid">
            <SearchPicker label={t("contest.allowedParticipants")} items={userPickerItems(users)} selectedIds={form.participant_ids} onChange={(participant_ids) => setForm({ ...form, participant_ids })} placeholder={t("contest.searchParticipants")} emptyText={t("common.none")} />
            <SearchPicker label={t("contest.allowedTeams")} items={teamPickerItems(teams)} selectedIds={form.team_ids} onChange={(team_ids) => setForm({ ...form, team_ids })} placeholder={t("contest.searchTeams")} emptyText={t("common.none")} />
          </div>
        </fieldset>
        <button type="submit">{t("common.create")}</button>
      </form>
      <FlashMessage flash={flash} />
      <div className="table-wrap">
        <table>
          <thead><tr><th>{t("table.id")}</th><th>{t("table.title")}</th><th>{t("table.status")}</th><th>{t("table.access")}</th><th>{t("contest.participationMode")}</th><th>{t("table.mode")}</th><th>{t("table.starts")}</th><th>{t("table.ends")}</th><th>{t("table.minutes")}</th><th>{t("table.tasks")}</th><th>{t("table.participants")}</th><th>{t("table.teams")}</th><th></th></tr></thead>
          <tbody>{contests.map((contest) => <ContestRow key={contest.id} contest={contest} tasks={tasks} users={users} teams={teams} taskIds={contestTaskIds[contest.id] ?? []} participantIds={contestParticipantIds[contest.id] ?? []} teamIds={contestTeamIds[contest.id] ?? []} onSave={saveContest} onSaveTasks={saveContestTasks} onSaveParticipants={saveContestParticipants} onSaveTeams={saveContestTeams} onDelete={deleteContest} />)}</tbody>
        </table>
      </div>
    </section>
  );
}

const contestStatuses: ContestStatus[] = ["draft", "scheduled", "running", "finished", "archived"];

function ContestRow({
  contest,
  tasks,
  users,
  teams,
  taskIds,
  participantIds,
  teamIds,
  onSave,
  onSaveTasks,
  onSaveParticipants,
  onSaveTeams,
  onDelete
}: {
  contest: Contest;
  tasks: Task[];
  users: User[];
  teams: Team[];
  taskIds: number[];
  participantIds: number[];
  teamIds: number[];
  onSave: (contest: Contest, patch: Partial<Contest>) => Promise<void>;
  onSaveTasks: (contest: Contest, taskIds: number[]) => Promise<void>;
  onSaveParticipants: (contest: Contest, participantIds: number[]) => Promise<void>;
  onSaveTeams: (contest: Contest, teamIds: number[]) => Promise<void>;
  onDelete: (contest: Contest) => void;
}) {
  const { t } = useI18n();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState({
    title: contest.title,
    status: contest.status,
    is_public: contest.is_public,
    time_mode: contest.time_mode,
    participation_mode: contest.participation_mode,
    starts_at: toLocalInputValue(contest.starts_at),
    ends_at: toLocalInputValue(contest.ends_at),
    individual_duration_minutes: String(contest.individual_duration_minutes ?? ""),
    description: contest.description,
    task_ids: taskIds,
    participant_ids: participantIds,
    team_ids: teamIds
  });
  useEffect(() => setDraft({
    title: contest.title,
    status: contest.status,
    is_public: contest.is_public,
    time_mode: contest.time_mode,
    participation_mode: contest.participation_mode,
    starts_at: toLocalInputValue(contest.starts_at),
    ends_at: toLocalInputValue(contest.ends_at),
    individual_duration_minutes: String(contest.individual_duration_minutes ?? ""),
    description: contest.description,
    task_ids: taskIds,
    participant_ids: participantIds,
    team_ids: teamIds
  }), [contest, taskIds, participantIds, teamIds]);

  function toggleDraftTask(taskId: number) {
    setDraft((current) => ({
      ...current,
      task_ids: current.task_ids.includes(taskId) ? current.task_ids.filter((id) => id !== taskId) : [...current.task_ids, taskId]
    }));
  }

  if (!editing) {
    const participantNames = formatUserIds(participantIds, users);
    const teamNames = formatTeamIds(teamIds, teams);
    return (
      <tr>
        <td>{contest.id}</td><td>{contest.title}</td><td>{t(`status.${contest.status}`)}</td><td>{contest.is_public ? t("contest.public") : t("contest.private")}</td><td>{t(`common.${contest.participation_mode}`)}</td><td>{t(`common.${contest.time_mode}`)}</td>
        <td>{formatDate(contest.starts_at)}</td><td>{formatDate(contest.ends_at)}</td><td>{contest.individual_duration_minutes ?? "-"}</td>
        <td>{taskIds.length}</td><td>{participantNames || t("common.none")}</td><td>{teamNames || t("common.none")}</td>
        <td className="row-actions"><button onClick={() => setEditing(true)}>{t("common.edit")}</button><button className="danger" onClick={() => onDelete(contest)}>{t("common.delete")}</button></td>
      </tr>
    );
  }

  return (
    <>
      <tr className="editing">
        <td>{contest.id}</td>
        <td><input value={draft.title} onChange={(event) => setDraft({ ...draft, title: event.target.value })} /></td>
        <td><select value={draft.status} onChange={(event) => setDraft({ ...draft, status: event.target.value as ContestStatus })}>{contestStatuses.map((item) => <option key={item} value={item}>{t(`status.${item}`)}</option>)}</select></td>
        <td><label className="inline"><input className="check" type="checkbox" checked={draft.is_public} onChange={(event) => setDraft({ ...draft, is_public: event.target.checked })} /> {t("contest.public")}</label></td>
        <td><select value={draft.participation_mode} onChange={(event) => setDraft({ ...draft, participation_mode: event.target.value as ParticipationMode })}><option value="individual">{t("common.individual")}</option><option value="team">{t("common.team")}</option></select></td>
        <td><select value={draft.time_mode} onChange={(event) => setDraft({ ...draft, time_mode: event.target.value as TimeMode })}><option value="fixed">{t("common.fixed")}</option><option value="individual">{t("common.individual")}</option></select></td>
        <td><input type="datetime-local" value={draft.starts_at} onChange={(event) => setDraft({ ...draft, starts_at: event.target.value })} /></td>
        <td><input type="datetime-local" value={draft.ends_at} onChange={(event) => setDraft({ ...draft, ends_at: event.target.value })} /></td>
        <td><input type="number" value={draft.individual_duration_minutes} onChange={(event) => setDraft({ ...draft, individual_duration_minutes: event.target.value })} /></td>
        <td>{draft.task_ids.length}</td>
        <td>{draft.participant_ids.length}</td>
        <td>{draft.team_ids.length}</td>
        <td className="row-actions">
          <button onClick={async () => {
            await onSave(contest, {
              title: draft.title,
              status: draft.status,
              is_public: draft.is_public,
              participation_mode: draft.participation_mode,
              time_mode: draft.time_mode,
              starts_at: fromLocalInputValue(draft.starts_at),
              ends_at: fromLocalInputValue(draft.ends_at),
              individual_duration_minutes: draft.time_mode === "individual" ? Number(draft.individual_duration_minutes) : null,
              description: draft.description
            });
            await onSaveTasks(contest, draft.task_ids);
            await onSaveParticipants(contest, draft.participant_ids);
            await onSaveTeams(contest, draft.team_ids);
            setEditing(false);
          }}>{t("common.save")}</button>
          <button onClick={() => setEditing(false)}>{t("common.cancel")}</button>
        </td>
      </tr>
      <tr className="editing">
        <td></td>
        <td colSpan={12}>
          <div className="nested-edit">
            <label>{t("table.description")}<textarea className="short" value={draft.description} onChange={(event) => setDraft({ ...draft, description: event.target.value })} /></label>
            <label>{t("table.tasks")}
              <span className="checklist">{tasks.map((task) => (
                <span key={task.id} className="inline"><input className="check" type="checkbox" checked={draft.task_ids.includes(task.id)} onChange={() => toggleDraftTask(task.id)} /> #{task.id} {task.title}</span>
              ))}</span>
            </label>
            <div className="access-grid">
              <SearchPicker label={t("contest.allowedParticipants")} items={userPickerItems(users)} selectedIds={draft.participant_ids} onChange={(participant_ids) => setDraft({ ...draft, participant_ids })} placeholder={t("contest.searchParticipants")} emptyText={t("common.none")} />
              <SearchPicker label={t("contest.allowedTeams")} items={teamPickerItems(teams)} selectedIds={draft.team_ids} onChange={(team_ids) => setDraft({ ...draft, team_ids })} placeholder={t("contest.searchTeams")} emptyText={t("common.none")} />
            </div>
          </div>
        </td>
      </tr>
    </>
  );
}

function TasksAdmin({ api }: { api: ApiClient }) {
  const { t } = useI18n();
  const [tasks, setTasks] = useState<Task[]>([]);
  const [flash, setFlash] = useState<Flash>(emptyFlash);
  const [previewMode, setPreviewMode] = useState<"edit" | "preview">("edit");
  const [form, setForm] = useState({
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
  });

  const load = useCallback(async () => {
    setTasks(await api<Task[]>("/api/tasks"));
  }, [api]);

  useEffect(() => { load().catch((error) => setFlash({ kind: "error", text: errorText(error) })); }, [load]);

  async function createTask(event: React.FormEvent) {
    event.preventDefault();
    setFlash(emptyFlash);
    try {
      const tests = form.test_input || form.test_output ? [{ input_data: form.test_input, output_data: form.test_output, is_sample: form.test_is_sample }] : [];
      await api<Task>("/api/tasks", {
        method: "POST",
        body: JSON.stringify({
          title: form.title,
          statement: form.statement,
          input_format: form.input_format,
          output_format: form.output_format,
          samples: JSON.parse(form.samples || "[]"),
          time_limit_ms: Number(form.time_limit_ms),
          memory_limit_mb: Number(form.memory_limit_mb),
          points: Number(form.points),
          partial_scoring: form.partial_scoring,
          tests
        })
      });
      setForm({ ...form, title: "", statement: "", input_format: "", output_format: "", samples: "[]", partial_scoring: false, test_input: "", test_output: "" });
      await load();
    } catch (error) {
      setFlash({ kind: "error", text: errorText(error) });
    }
  }

  async function saveTask(task: Task, patch: Partial<Task>) {
    setFlash(emptyFlash);
    try {
      await api<Task>(`/api/tasks/${task.id}`, { method: "PATCH", body: JSON.stringify(patch) });
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

  return (
    <section className="panel">
      <Header title={t("tab.tasks")} subtitle={t("title.tasksLibrary", { count: tasks.length })} />
      <form className="task-form" onSubmit={createTask}>
        <fieldset>
          <legend>{t("task.sectionBasic")}</legend>
          <div className="form-grid">
            <label>{t("table.title")}<input value={form.title} onChange={(event) => setForm({ ...form, title: event.target.value })} required /></label>
            <label>{t("table.points")}<input type="number" step="0.01" value={form.points} onChange={(event) => setForm({ ...form, points: event.target.value })} /></label>
            <label>{t("task.timeLimitMs")}<input type="number" value={form.time_limit_ms} onChange={(event) => setForm({ ...form, time_limit_ms: event.target.value })} /></label>
            <label>{t("task.memoryMb")}<input type="number" value={form.memory_limit_mb} onChange={(event) => setForm({ ...form, memory_limit_mb: event.target.value })} /></label>
            <label className="inline"><input className="check" type="checkbox" checked={form.partial_scoring} onChange={(event) => setForm({ ...form, partial_scoring: event.target.checked })} /> {t("task.partialScoring")}</label>
          </div>
        </fieldset>
        <fieldset>
          <legend>{t("task.sectionStatement")}</legend>
          <div className="segmented">
            <button type="button" className={previewMode === "edit" ? "active" : ""} onClick={() => setPreviewMode("edit")}>{t("task.editMarkdown")}</button>
            <button type="button" className={previewMode === "preview" ? "active" : ""} onClick={() => setPreviewMode("preview")}>{t("task.previewMarkdown")}</button>
          </div>
          {previewMode === "edit" ? (
            <label>{t("task.statement")}<textarea value={form.statement} onChange={(event) => setForm({ ...form, statement: event.target.value })} required /></label>
          ) : (
            <MarkdownPreview value={form.statement} />
          )}
        </fieldset>
        <fieldset>
          <legend>{t("task.sectionFormats")}</legend>
          <div className="form-grid">
            <label>{t("task.inputFormat")}<textarea className="short" value={form.input_format} onChange={(event) => setForm({ ...form, input_format: event.target.value })} /></label>
            <label>{t("task.outputFormat")}<textarea className="short" value={form.output_format} onChange={(event) => setForm({ ...form, output_format: event.target.value })} /></label>
            <label className="span-2">{t("task.samplesJson")}<textarea className="short code" value={form.samples} onChange={(event) => setForm({ ...form, samples: event.target.value })} /></label>
          </div>
        </fieldset>
        <fieldset>
          <legend>{t("task.sectionFirstTest")}</legend>
          <div className="form-grid">
            <label>{t("task.firstInput")}<textarea className="short code" value={form.test_input} onChange={(event) => setForm({ ...form, test_input: event.target.value })} /></label>
            <label>{t("task.firstOutput")}<textarea className="short code" value={form.test_output} onChange={(event) => setForm({ ...form, test_output: event.target.value })} /></label>
            <label className="inline"><input className="check" type="checkbox" checked={form.test_is_sample} onChange={(event) => setForm({ ...form, test_is_sample: event.target.checked })} /> {t("task.sampleTest")}</label>
          </div>
        </fieldset>
        <button type="submit">{t("common.create")}</button>
      </form>
      <FlashMessage flash={flash} />
      <div className="table-wrap">
        <table>
          <thead><tr><th>{t("table.id")}</th><th>{t("table.title")}</th><th>{t("table.limits")}</th><th>{t("table.points")}</th><th>{t("table.tests")}</th><th></th></tr></thead>
          <tbody>{tasks.map((task) => <TaskRow key={task.id} task={task} onSave={saveTask} onDelete={deleteTask} />)}</tbody>
        </table>
      </div>
    </section>
  );
}

function TaskRow({ task, onSave, onDelete }: { task: Task; onSave: (task: Task, patch: Partial<Task>) => void; onDelete: (task: Task) => void }) {
  const { t } = useI18n();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState({
    title: task.title,
    statement: task.statement,
    input_format: task.input_format,
    output_format: task.output_format,
    samples: JSON.stringify(task.samples, null, 2),
    time_limit_ms: String(task.time_limit_ms),
    memory_limit_mb: String(task.memory_limit_mb),
    points: String(task.points),
    partial_scoring: task.partial_scoring
  });
  useEffect(() => setDraft({
    title: task.title,
    statement: task.statement,
    input_format: task.input_format,
    output_format: task.output_format,
    samples: JSON.stringify(task.samples, null, 2),
    time_limit_ms: String(task.time_limit_ms),
    memory_limit_mb: String(task.memory_limit_mb),
    points: String(task.points),
    partial_scoring: task.partial_scoring
  }), [task]);

  return (
    <>
      <tr className={editing ? "editing" : ""}>
        <td>{task.id}</td>
        <td>{editing ? <input value={draft.title} onChange={(event) => setDraft({ ...draft, title: event.target.value })} /> : task.title}</td>
        <td>{editing ? <><input type="number" value={draft.time_limit_ms} onChange={(event) => setDraft({ ...draft, time_limit_ms: event.target.value })} /><input type="number" value={draft.memory_limit_mb} onChange={(event) => setDraft({ ...draft, memory_limit_mb: event.target.value })} /></> : `${task.time_limit_ms} ms / ${task.memory_limit_mb} MB`}</td>
        <td>{editing ? <input type="number" step="0.01" value={draft.points} onChange={(event) => setDraft({ ...draft, points: event.target.value })} /> : formatScore(task.points)}</td>
        <td>{task.test_count}{task.partial_scoring ? ` · ${t("task.partialScoring")}` : ""}</td>
        <td className="row-actions">
          {editing ? (
            <>
              <button onClick={() => {
                onSave(task, {
                  title: draft.title,
                  statement: draft.statement,
                  input_format: draft.input_format,
                  output_format: draft.output_format,
                  samples: JSON.parse(draft.samples || "[]") as Task["samples"],
                  time_limit_ms: Number(draft.time_limit_ms),
                  memory_limit_mb: Number(draft.memory_limit_mb),
                  points: Number(draft.points),
                  partial_scoring: draft.partial_scoring
                });
                setEditing(false);
              }}>{t("common.save")}</button>
              <button onClick={() => setEditing(false)}>{t("common.cancel")}</button>
            </>
          ) : (
            <>
              <button onClick={() => setEditing(true)}>{t("common.edit")}</button>
              <button className="danger" onClick={() => onDelete(task)}>{t("common.delete")}</button>
            </>
          )}
        </td>
      </tr>
      {editing && (
        <tr className="editing">
          <td></td>
          <td colSpan={5}>
            <div className="nested-edit">
              <label>{t("task.statement")}<textarea value={draft.statement} onChange={(event) => setDraft({ ...draft, statement: event.target.value })} /></label>
              <label>{t("task.inputFormat")}<textarea className="short" value={draft.input_format} onChange={(event) => setDraft({ ...draft, input_format: event.target.value })} /></label>
              <label>{t("task.outputFormat")}<textarea className="short" value={draft.output_format} onChange={(event) => setDraft({ ...draft, output_format: event.target.value })} /></label>
              <label>{t("task.samplesJson")}<textarea className="short code" value={draft.samples} onChange={(event) => setDraft({ ...draft, samples: event.target.value })} /></label>
              <label className="inline"><input className="check" type="checkbox" checked={draft.partial_scoring} onChange={(event) => setDraft({ ...draft, partial_scoring: event.target.checked })} /> {t("task.partialScoring")}</label>
            </div>
          </td>
        </tr>
      )}
    </>
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
  const [form, setForm] = useState({ input_data: "", output_data: "", is_sample: false });

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
      await api<TaskTest>(`/api/tasks/${selectedTaskId}/tests`, { method: "POST", body: JSON.stringify(form) });
      setForm({ input_data: "", output_data: "", is_sample: false });
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
      <form className="form-grid" onSubmit={createTest}>
        <label>{t("table.input")}<textarea className="short code" value={form.input_data} onChange={(event) => setForm({ ...form, input_data: event.target.value })} /></label>
        <label>{t("table.output")}<textarea className="short code" value={form.output_data} onChange={(event) => setForm({ ...form, output_data: event.target.value })} /></label>
        <label className="inline"><input className="check" type="checkbox" checked={form.is_sample} onChange={(event) => setForm({ ...form, is_sample: event.target.checked })} /> {t("task.sample")}</label>
        <button type="submit" disabled={!selectedTaskId}>{t("common.create")}</button>
      </form>
      <FlashMessage flash={flash} />
      {archiveReport && (
        <div className="report">
          <div className="stat"><strong>{archiveReport.created}</strong><span>{t("common.created")}</span></div>
          <div className="stat"><strong>{archiveReport.skipped.length}</strong><span>{t("common.skipped")}</span></div>
          <div className="stat"><strong>{archiveReport.errors.length}</strong><span>{t("common.errors")}</span></div>
          {(archiveReport.skipped.length > 0 || archiveReport.errors.length > 0) && (
            <table>
              <tbody>
                {archiveReport.skipped.map((item, index) => <tr key={`s-${index}`}><td><span className="pill warn">{t("common.skipped")}</span></td><td>{item}</td></tr>)}
                {archiveReport.errors.map((item, index) => <tr key={`e-${index}`}><td><span className="pill warn">{t("common.errors")}</span></td><td>{item}</td></tr>)}
              </tbody>
            </table>
          )}
        </div>
      )}
      <div className="table-wrap">
        <table>
          <thead><tr><th>{t("table.id")}</th><th>{t("table.sample")}</th><th>{t("table.input")}</th><th>{t("table.output")}</th><th></th></tr></thead>
          <tbody>{tests.map((test) => <TestRow key={test.id} test={test} onSave={saveTest} onDelete={deleteTest} />)}</tbody>
        </table>
      </div>
    </section>
  );
}

function TestRow({ test, onSave, onDelete }: { test: TaskTest; onSave: (test: TaskTest, patch: Partial<TaskTest>) => void; onDelete: (test: TaskTest) => void }) {
  const { t } = useI18n();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(test);
  useEffect(() => setDraft(test), [test]);

  return (
    <tr className={editing ? "editing" : ""}>
      <td>{test.id}</td>
      <td>{editing ? <input className="check" type="checkbox" checked={draft.is_sample} onChange={(event) => setDraft({ ...draft, is_sample: event.target.checked })} /> : test.is_sample ? t("common.yes") : t("common.no")}</td>
      <td>{editing ? <textarea className="short code" value={draft.input_data} onChange={(event) => setDraft({ ...draft, input_data: event.target.value })} /> : <pre>{test.input_data}</pre>}</td>
      <td>{editing ? <textarea className="short code" value={draft.output_data} onChange={(event) => setDraft({ ...draft, output_data: event.target.value })} /> : <pre>{test.output_data}</pre>}</td>
      <td className="row-actions">
        {editing ? (
          <>
            <button onClick={() => { onSave(test, { input_data: draft.input_data, output_data: draft.output_data, is_sample: draft.is_sample }); setEditing(false); }}>{t("common.save")}</button>
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

function SubmissionsAdmin({ api }: { api: ApiClient }) {
  const { t } = useI18n();
  const [contests, setContests] = useState<Contest[]>([]);
  const [submissions, setSubmissions] = useState<Submission[]>([]);
  const [selectedContestId, setSelectedContestId] = useState<number | "all">("all");
  const [selectedSubmissionId, setSelectedSubmissionId] = useState<number | null>(null);
  const [detail, setDetail] = useState<SubmissionDetail | null>(null);
  const [flash, setFlash] = useState<Flash>(emptyFlash);

  const loadContests = useCallback(() => api<Contest[]>("/api/contests").then(setContests), [api]);
  const loadSubmissions = useCallback(async () => {
    const query = selectedContestId === "all" ? "" : `?contest_id=${selectedContestId}`;
    setSubmissions(await api<Submission[]>(`/api/submissions${query}`));
  }, [api, selectedContestId]);

  useEffect(() => { loadContests().catch((error) => setFlash({ kind: "error", text: errorText(error) })); }, [loadContests]);
  useEffect(() => {
    loadSubmissions().catch((error) => setFlash({ kind: "error", text: errorText(error) }));
    const interval = window.setInterval(() => loadSubmissions().catch(console.error), 2000);
    return () => window.clearInterval(interval);
  }, [loadSubmissions]);
  useEffect(() => {
    if (!selectedSubmissionId) {
      setDetail(null);
      return;
    }
    api<SubmissionDetail>(`/api/admin/submissions/${selectedSubmissionId}`)
      .then(setDetail)
      .catch((error) => setFlash({ kind: "error", text: errorText(error) }));
  }, [api, selectedSubmissionId, submissions]);

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
      <div className="split">
        <div className="table-wrap">
          <table>
            <thead><tr><th>{t("table.id")}</th><th>{t("table.contest")}</th><th>{t("table.task")}</th><th>{t("table.user")}</th><th>{t("table.lang")}</th><th>{t("table.verdict")}</th><th>{t("table.score")}</th><th>{t("table.created")}</th></tr></thead>
            <tbody>
              {submissions.map((submission) => (
                <tr key={submission.id} className={submission.id === selectedSubmissionId ? "selected" : ""} onClick={() => setSelectedSubmissionId(submission.id)}>
                  <td>#{submission.id}</td><td>{submission.contest_id}</td><td>{submission.task_id}</td><td>{submission.user_id}</td><td>{submission.language}</td>
                  <td><span className={verdictClass(submission.verdict)}>{t(`verdict.${submission.verdict}`)}</span></td><td>{formatScore(submission.score)}</td><td>{formatDate(submission.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <SubmissionDetailView detail={detail} />
      </div>
    </section>
  );
}
