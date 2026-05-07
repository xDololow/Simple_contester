import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import { API_BASE } from "../../api/client";
import { FlashMessage, Header, SubmissionDetailView } from "../../components/shared";
import { useI18n } from "../../i18n";
import type { ApiClient, Clarification, Contest, ContestLiveEvent, ContestRegistration, Flash, Language, ScoreboardRow, Submission, SubmissionDetail, Task, User } from "../../types";
import { emptyFlash, errorText, formatDate, formatScore, verdictClass } from "../../utils/format";

type ContestTab = "overview" | "tasks" | "submissions" | "scoreboard" | "clarifications";

const SUBMISSION_LANGUAGES: Array<{ value: Language; label: string }> = [
  { value: "python", label: "Python" },
  { value: "java", label: "Java" },
  { value: "javascript", label: "JavaScript" },
  { value: "typescript", label: "TypeScript" },
  { value: "c11", label: "C11" },
  { value: "cpp17", label: "C++17" },
  { value: "cpp20", label: "C++20" },
  { value: "csharp", label: "C# (Mono)" },
  { value: "object_pascal", label: "Object Pascal" },
  { value: "fortran", label: "Fortran" },
  { value: "go", label: "Go" },
  { value: "lua", label: "Lua" }
];

const SUBMIT_DRAFT_PREFIX = "simple-contester-submit-draft:v1";
const SUBMIT_LANGUAGE_PREFIX = "simple-contester-submit-language:v1";

export function ContestView({ api, contest, me, token }: { api: ApiClient; contest: Contest; me: User; token: string }) {
  const { t } = useI18n();
  const [now, setNow] = useState(() => Date.now());
  const [tasks, setTasks] = useState<Task[]>([]);
  const [submissions, setSubmissions] = useState<Submission[]>([]);
  const [scoreboard, setScoreboard] = useState<ScoreboardRow[]>([]);
  const [scoreboardFrozen, setScoreboardFrozen] = useState(
    me.role !== "admin" &&
      Boolean(contest.scoreboard_freeze_at) &&
      !contest.scoreboard_unfrozen &&
      Date.now() >= new Date(contest.scoreboard_freeze_at || "").getTime()
  );
  const [clarifications, setClarifications] = useState<Clarification[]>([]);
  const [registration, setRegistration] = useState<ContestRegistration | null>(null);
  const [hasContestAccess, setHasContestAccess] = useState(true);
  const [registrationLoading, setRegistrationLoading] = useState(false);
  const [tab, setTab] = useState<ContestTab>("tasks");
  const [selectedTaskId, setSelectedTaskId] = useState<number | null>(null);
  const [selectedSubmissionId, setSelectedSubmissionId] = useState<number | null>(null);
  const [detail, setDetail] = useState<SubmissionDetail | null>(null);
  const [flash, setFlash] = useState<Flash>(emptyFlash);
  const selectedTask = tasks.find((task) => task.id === selectedTaskId) || tasks[0] || null;
  const myScore = scoreboard.find((row) => contest.participation_mode !== "team" && row.user_id === me.id)?.score ?? null;

  const refreshRegistration = useCallback(async () => {
    if (!contest.registration_enabled || me.role === "admin") {
      setRegistration(null);
      return;
    }
    const nextRegistration = await api<ContestRegistration | null>(`/api/contests/${contest.id}/registration`);
    setRegistration(nextRegistration);
    if (nextRegistration?.can_access) {
      setHasContestAccess(true);
    }
  }, [api, contest.id, contest.registration_enabled, me.role]);

  const refresh = useCallback(async () => {
    const [nextTasks, live, nextClarifications] = await Promise.all([
      api<Task[]>(`/api/contests/${contest.id}/tasks`),
      api<ContestLiveEvent>(`/api/contests/${contest.id}/live-snapshot`),
      api<Clarification[]>(`/api/contests/${contest.id}/clarifications`)
    ]);
    setTasks(nextTasks);
    setSubmissions(live.submissions);
    setScoreboard(live.scoreboard);
    setScoreboardFrozen(Boolean(live.scoreboard_frozen));
    setClarifications(nextClarifications);
    setSelectedTaskId((current) => current ?? nextTasks[0]?.id ?? null);
    setHasContestAccess(true);
  }, [api, contest.id]);

  const refreshLiveData = useCallback(async () => {
    const live = await api<ContestLiveEvent>(`/api/contests/${contest.id}/live-snapshot`);
    setSubmissions(live.submissions);
    setScoreboard(live.scoreboard);
    setScoreboardFrozen(Boolean(live.scoreboard_frozen));
  }, [api, contest.id]);

  useEffect(() => {
    const interval = window.setInterval(() => setNow(Date.now()), 30000);
    return () => window.clearInterval(interval);
  }, []);

  useEffect(() => {
    let cancelled = false;
    if (hasContestAccess) {
      refresh()
        .then(() => refreshRegistration())
        .catch((error) => {
          if (cancelled) return;
          const message = errorText(error);
          if (contest.registration_enabled && message === "Contest is not available") {
            setHasContestAccess(false);
            refreshRegistration().catch((registrationError) => setFlash({ kind: "error", text: errorText(registrationError) }));
            return;
          }
          setFlash({ kind: "error", text: message });
        });
    } else {
      refreshRegistration().catch((registrationError) => setFlash({ kind: "error", text: errorText(registrationError) }));
    }

    let eventSource: EventSource | null = null;
    let fallbackInterval: number | null = null;
    const startFallback = () => {
      if (fallbackInterval !== null) return;
      fallbackInterval = window.setInterval(() => refreshLiveData().catch(console.error), 5000);
    };

    if (!hasContestAccess) {
      return () => {
        cancelled = true;
        if (fallbackInterval !== null) window.clearInterval(fallbackInterval);
      };
    }

    if (!token || typeof EventSource === "undefined") {
      startFallback();
      return () => {
        cancelled = true;
        if (fallbackInterval !== null) window.clearInterval(fallbackInterval);
      };
    }

    const eventsUrl = `${API_BASE}/api/contests/${contest.id}/events?token=${encodeURIComponent(token)}`;
    eventSource = new EventSource(eventsUrl);
    eventSource.addEventListener("contest", (event) => {
      const live = JSON.parse((event as MessageEvent).data) as ContestLiveEvent;
      setSubmissions(live.submissions);
      setScoreboard(live.scoreboard);
      setScoreboardFrozen(Boolean(live.scoreboard_frozen));
    });
    eventSource.onerror = () => {
      eventSource?.close();
      startFallback();
    };

    return () => {
      cancelled = true;
      eventSource?.close();
      if (fallbackInterval !== null) window.clearInterval(fallbackInterval);
    };
  }, [contest.id, contest.registration_enabled, hasContestAccess, refresh, refreshLiveData, refreshRegistration, token]);

  async function requestRegistration() {
    setRegistrationLoading(true);
    setFlash(emptyFlash);
    try {
      const nextRegistration = await api<ContestRegistration>(`/api/contests/${contest.id}/registration`, { method: "POST" });
      setRegistration(nextRegistration);
      if (nextRegistration.status === "approved") {
        setHasContestAccess(true);
        await refresh();
      }
    } catch (error) {
      setFlash({ kind: "error", text: errorText(error) });
    } finally {
      setRegistrationLoading(false);
    }
  }

  useEffect(() => {
    if (!selectedSubmissionId || me.role !== "admin") {
      setDetail(null);
      return;
    }
    api<SubmissionDetail>(`/api/admin/submissions/${selectedSubmissionId}`)
      .then(setDetail)
      .catch((error) => setFlash({ kind: "error", text: errorText(error) }));
  }, [api, me.role, selectedSubmissionId, submissions]);

  return (
    <div className="contest">
      <section className="panel contest-header">
        <div>
          <h2>{contest.title}</h2>
          <p>{contest.description || t("title.noDescription")}</p>
        </div>
        <div className="meta">
          <span className="pill">{t(`status.${contest.status}`)}</span>
          <span>{t(`common.${contest.participation_mode}`)}</span>
          <span>{contest.time_mode === "individual" ? `${contest.individual_duration_minutes} ${t("table.minutes").toLowerCase()}` : t("common.fixed")}</span>
          {scoreboardFrozen && <span className="pill warn">{t("scoreboard.frozenBadge")}</span>}
          <span>{formatDate(contest.starts_at)} - {formatDate(contest.ends_at)}</span>
        </div>
      </section>
      <FlashMessage flash={flash} />
      {!hasContestAccess && (
        <section className="panel">
          <Header title={t("registration.requestAccess")} subtitle={t("registration.participantSubtitle")} />
          <div className="toolbar">
            {registration ? <span className={registration.status === "rejected" ? "pill warn" : "pill"}>{t(`registration.status.${registration.status}`)}</span> : <span className="pill">{t("registration.notRequested")}</span>}
            {!registration && <button onClick={requestRegistration} disabled={registrationLoading}>{registrationLoading ? t("status.refreshing") : t("registration.requestAccess")}</button>}
          </div>
        </section>
      )}
      {!hasContestAccess ? null : (
      <>
      <nav className="tabs contest-tabs" aria-label={t("nav.contestSections")}>
        {[
          ["overview", t("tab.overview")],
          ["tasks", t("tab.tasks")],
          ["submissions", t("tab.submissions")],
          ["scoreboard", t("title.scoreboard")],
          ["clarifications", t("tab.clarifications")]
        ].map(([id, label]) => (
          <button key={id} className={tab === id ? "active" : ""} onClick={() => setTab(id as ContestTab)} type="button">
            {label}
          </button>
        ))}
      </nav>

      {tab === "overview" && (
        <section className="panel">
          <Header title={t("tab.overview")} subtitle={t("contest.summary")} />
          <div className="contest-summary-grid">
            <SummaryCard label={t("overview.remaining")} value={formatRemaining(contest, now, t)} detail={t("overview.deadline", { time: formatDate(contest.ends_at) })} />
            <SummaryCard label={t("overview.schedule")} value={formatContestWindow(contest, t)} detail={`${formatDate(contest.starts_at)} - ${formatDate(contest.ends_at)}`} />
            <SummaryCard
              label={t("overview.freeze")}
              value={formatFreezeStatus(contest, scoreboardFrozen, now, t)}
              detail={contest.scoreboard_freeze_at ? t("overview.freezeAt", { time: formatDate(contest.scoreboard_freeze_at) }) : t("overview.freezeNone")}
              warn={scoreboardFrozen}
            />
            <SummaryCard label={t("overview.registration")} value={formatRegistrationStatus(contest, registration, me, t)} detail={formatAccessStatus(contest, hasContestAccess, t)} />
          </div>
          <div className="overview-grid">
            <div className="stat"><strong>{tasks.length}</strong><span>{t("tab.tasks")}</span></div>
            <div className="stat"><strong>{submissions.length}</strong><span>{t("tab.submissions")}</span></div>
            <div className="stat"><strong>{scoreboard.length}</strong><span>{t("title.scoreboard")}</span></div>
            <div className="stat"><strong>{clarifications.length}</strong><span>{t("tab.clarifications")}</span></div>
            {myScore !== null && <div className="stat"><strong>{formatScore(myScore)}</strong><span>{t("overview.myScore")}</span></div>}
          </div>
        </section>
      )}

      {tab === "tasks" && (
        <section className="panel">
          <Header title={t("tab.tasks")} subtitle={t("task.available", { count: tasks.length })} />
          {tasks.length ? (
            <div className="contest-workspace">
              <div className="list task-list">
                {tasks.map((task) => (
                  <button key={task.id} className={task.id === selectedTask?.id ? "active item" : "item"} onClick={() => setSelectedTaskId(task.id)} type="button">
                    <span>{task.title}</span><span className="pill">{formatScore(task.points)}</span>
                  </button>
                ))}
              </div>
              {selectedTask && (
                <div className="task-detail">
                  <TaskStatement task={selectedTask} />
                  <SubmitBox api={api} contestId={contest.id} task={selectedTask} onSubmitted={refreshLiveData} />
                </div>
              )}
            </div>
          ) : (
            <EmptyState title={t("empty.tasksTitle")} text={t("empty.tasksText")} />
          )}
        </section>
      )}

      {tab === "submissions" && (
        <section className="panel">
          <Header title={t("tab.submissions")} subtitle={t("common.live")} />
          {submissions.length ? (
            <>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr><th>{t("table.id")}</th><th>{t("table.lang")}</th><th>{t("table.verdict")}</th><th>{t("table.score")}</th><th>{t("table.created")}</th></tr>
                  </thead>
                  <tbody>
                    {submissions.map((submission) => (
                      <tr key={submission.id} className={submission.id === selectedSubmissionId ? "selected" : ""} onClick={() => setSelectedSubmissionId(submission.id)}>
                        <td>#{submission.id}</td>
                        <td>{submission.language}</td>
                        <td><span className={verdictClass(submission.verdict)}>{t(`verdict.${submission.verdict}`)}</span></td>
                        <td>{formatScore(submission.score)}</td>
                        <td>{formatDate(submission.created_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {me.role === "admin" && <SubmissionDetailView detail={detail} compact />}
            </>
          ) : (
            <EmptyState title={t("empty.submissionsTitle")} text={t("empty.submissionsText")} />
          )}
        </section>
      )}

      {tab === "scoreboard" && (
        <section className="panel">
          <Header title={t("title.scoreboard")} subtitle={scoreboardFrozen ? t("scoreboard.frozenText") : t("common.live")} />
          {scoreboard.length ? (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr><th>{contest.participation_mode === "team" ? t("table.team") : t("table.user")}</th><th>{t("table.points")}</th><th>{t("table.penalty")}</th>{tasks.map((task) => <th key={task.id}>{task.title}</th>)}</tr>
                </thead>
                <tbody>
                  {scoreboard.map((row) => (
                    <tr key={row.user_id} className={contest.participation_mode !== "team" && row.user_id === me.id ? "self" : ""}>
                      <td>{contest.participation_mode === "team" ? row.team_name || row.display_name : row.display_name}</td>
                      <td>{formatScore(row.score)}</td>
                      <td>{row.penalty}</td>
                      {row.cells.map((cell) => <td key={cell.task_id}>{cell.solved ? `+${cell.attempts > 1 ? cell.attempts - 1 : ""}` : cell.attempts ? `-${cell.attempts}` : ""}</td>)}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <EmptyState title={t("empty.scoreboardTitle")} text={t("empty.scoreboardText")} />
          )}
        </section>
      )}

      {tab === "clarifications" && (
        <ClarificationsBox
          api={api}
          contestId={contest.id}
          tasks={tasks}
          clarifications={clarifications}
          onRefresh={async () => setClarifications(await api<Clarification[]>(`/api/contests/${contest.id}/clarifications`))}
        />
      )}
      </>
      )}
    </div>
  );
}

function EmptyState({ title, text }: { title: string; text: string }) {
  return (
    <div className="empty-state">
      <strong>{title}</strong>
      <span>{text}</span>
    </div>
  );
}

function SummaryCard({ label, value, detail, warn = false }: { label: string; value: string; detail: string; warn?: boolean }) {
  return (
    <div className={warn ? "summary-card warn" : "summary-card"}>
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{detail}</small>
    </div>
  );
}

function TaskStatement({ task }: { task: Task }) {
  const { t } = useI18n();
  return (
    <article className="task-statement">
      <div className="task-statement-head">
        <div>
          <h3>{task.title}</h3>
          <span className="limits">{task.time_limit_ms} ms · {task.memory_limit_mb} MB · {formatScore(task.points)} {t("common.points")}</span>
        </div>
        {task.partial_scoring && <span className="pill">{t("task.partialScoring")}</span>}
      </div>
      <div className="statement-text">{task.statement || t("task.noStatement")}</div>
      <div className="task-format-grid">
        <div>
          <strong>{t("task.inputFormat")}</strong>
          <p>{task.input_format || t("common.empty")}</p>
        </div>
        <div>
          <strong>{t("task.outputFormat")}</strong>
          <p>{task.output_format || t("common.empty")}</p>
        </div>
      </div>
    </article>
  );
}

function SubmitBox({ api, contestId, task, onSubmitted }: { api: ApiClient; contestId: number; task: Task; onSubmitted: () => void }) {
  const { t } = useI18n();
  const [language, setLanguageState] = useState<Language>(() => readStoredLanguage(contestId, task.id));
  const [sourceCode, setSourceCode] = useState(() => readDraft(contestId, task.id, readStoredLanguage(contestId, task.id)));
  const [message, setMessage] = useState("");

  useEffect(() => {
    const nextLanguage = readStoredLanguage(contestId, task.id);
    setLanguageState(nextLanguage);
    setSourceCode(readDraft(contestId, task.id, nextLanguage));
    setMessage("");
  }, [contestId, task.id]);

  function setLanguage(nextLanguage: Language) {
    setLanguageState(nextLanguage);
    writeStoredLanguage(contestId, task.id, nextLanguage);
    setSourceCode(readDraft(contestId, task.id, nextLanguage));
  }

  function updateSourceCode(nextSourceCode: string) {
    setSourceCode(nextSourceCode);
    writeDraft(contestId, task.id, language, nextSourceCode);
  }

  async function submit() {
    setMessage("");
    try {
      await api<Submission>(`/api/contests/${contestId}/tasks/${task.id}/submissions`, {
        method: "POST",
        body: JSON.stringify({ language, source_code: sourceCode })
      });
      setMessage(t("submission.submitted"));
      onSubmitted();
    } catch (error) {
      setMessage(errorText(error));
    }
  }

  return (
    <form className="submit" onSubmit={(event) => { event.preventDefault(); submit(); }}>
      <Header title={t("submission.solutionFor", { task: task.title })} subtitle={t("submission.draftSaved")} />
      <label>{t("table.lang")}
        <select value={language} onChange={(event) => setLanguage(event.target.value as Language)}>
          {SUBMISSION_LANGUAGES.map((item) => (
            <option key={item.value} value={item.value}>{item.label}</option>
          ))}
        </select>
      </label>
      <label>{t("submission.sourceCode")}
        <textarea className="code submit-code" value={sourceCode} onChange={(event) => updateSourceCode(event.target.value)} />
      </label>
      <div className="submit-actions">
        <button type="submit" disabled={!sourceCode.trim()}>{t("submission.submit")}</button>
        {message && <span className="muted">{message}</span>}
      </div>
    </form>
  );
}

function readStoredLanguage(contestId: number, taskId: number): Language {
  if (typeof localStorage === "undefined") return "python";
  const stored = localStorage.getItem(`${SUBMIT_LANGUAGE_PREFIX}:${contestId}:${taskId}`) as Language | null;
  return SUBMISSION_LANGUAGES.some((item) => item.value === stored) ? stored : "python";
}

function writeStoredLanguage(contestId: number, taskId: number, language: Language) {
  localStorage.setItem(`${SUBMIT_LANGUAGE_PREFIX}:${contestId}:${taskId}`, language);
}

function readDraft(contestId: number, taskId: number, language: Language) {
  if (typeof localStorage === "undefined") return defaultSource(language);
  return localStorage.getItem(draftKey(contestId, taskId, language)) ?? defaultSource(language);
}

function writeDraft(contestId: number, taskId: number, language: Language, sourceCode: string) {
  localStorage.setItem(draftKey(contestId, taskId, language), sourceCode);
}

function draftKey(contestId: number, taskId: number, language: Language) {
  return `${SUBMIT_DRAFT_PREFIX}:${contestId}:${taskId}:${language}`;
}

function defaultSource(language: Language) {
  if (language === "javascript") return "const fs = require('fs');\nconst input = fs.readFileSync(0, 'utf8').trim();\nconsole.log(input);";
  if (language === "typescript") return "const fs = require('fs');\nconst input = fs.readFileSync(0, 'utf8').trim();\nconsole.log(input);";
  if (language === "cpp17" || language === "cpp20") return "#include <bits/stdc++.h>\nusing namespace std;\n\nint main() {\n  ios::sync_with_stdio(false);\n  cin.tie(nullptr);\n  return 0;\n}";
  if (language === "c11") return "#include <stdio.h>\n\nint main(void) {\n  return 0;\n}";
  if (language === "java") return "import java.io.*;\nimport java.util.*;\n\npublic class Main {\n  public static void main(String[] args) throws Exception {\n  }\n}";
  if (language === "go") return "package main\n\nfunc main() {\n}";
  return "print(input())";
}

function formatContestWindow(contest: Contest, t: (key: string, vars?: Record<string, string | number>) => string) {
  if (contest.status === "running") return t("overview.runningNow");
  if (contest.status === "scheduled") return t("overview.startsAt", { time: formatDate(contest.starts_at) });
  if (contest.status === "finished") return t("status.finished");
  return t(`status.${contest.status}`);
}

function formatRemaining(contest: Contest, now: number, t: (key: string, vars?: Record<string, string | number>) => string) {
  const startsAt = new Date(contest.starts_at).getTime();
  const endsAt = new Date(contest.ends_at).getTime();
  if (now < startsAt) return t("overview.untilStart", { time: formatDuration(startsAt - now, t) });
  if (now >= endsAt || contest.status === "finished") return t("overview.ended");
  return formatDuration(endsAt - now, t);
}

function formatFreezeStatus(contest: Contest, frozen: boolean, now: number, t: (key: string, vars?: Record<string, string | number>) => string) {
  if (contest.scoreboard_unfrozen) return t("scoreboard.unfrozenShort");
  if (!contest.scoreboard_freeze_at) return t("overview.freezeNone");
  if (frozen) return t("scoreboard.frozenBadge");
  const freezeAt = new Date(contest.scoreboard_freeze_at).getTime();
  if (Number.isNaN(freezeAt)) return t("overview.freezeNone");
  return now < freezeAt ? t("overview.untilFreeze", { time: formatDuration(freezeAt - now, t) }) : t("scoreboard.frozenBadge");
}

function formatRegistrationStatus(contest: Contest, registration: ContestRegistration | null, me: User, t: (key: string, vars?: Record<string, string | number>) => string) {
  if (me.role === "admin") return t("common.admin");
  if (!contest.registration_enabled) return t("registration.disabled");
  if (registration) return t(`registration.status.${registration.status}`);
  return t("registration.notRequested");
}

function formatAccessStatus(contest: Contest, hasContestAccess: boolean, t: (key: string, vars?: Record<string, string | number>) => string) {
  if (hasContestAccess) return t("overview.accessGranted");
  if (contest.registration_requires_approval) return t("registration.requiresApproval");
  return t("overview.accessPending");
}

function formatDuration(ms: number, t: (key: string, vars?: Record<string, string | number>) => string) {
  const totalMinutes = Math.max(0, Math.ceil(ms / 60000));
  const days = Math.floor(totalMinutes / 1440);
  const hours = Math.floor((totalMinutes % 1440) / 60);
  const minutes = totalMinutes % 60;
  if (days > 0) return t("duration.daysHours", { days, hours });
  if (hours > 0) return t("duration.hoursMinutes", { hours, minutes });
  return t("duration.minutes", { minutes });
}

function ClarificationsBox({
  api,
  contestId,
  tasks,
  clarifications,
  onRefresh
}: {
  api: ApiClient;
  contestId: number;
  tasks: Task[];
  clarifications: Clarification[];
  onRefresh: () => Promise<void>;
}) {
  const { t } = useI18n();
  const [taskId, setTaskId] = useState("");
  const [question, setQuestion] = useState("");
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);

  async function ask(event: FormEvent) {
    event.preventDefault();
    setMessage("");
    setLoading(true);
    try {
      await api<Clarification>(`/api/contests/${contestId}/clarifications`, {
        method: "POST",
        body: JSON.stringify({ task_id: taskId ? Number(taskId) : null, question })
      });
      setQuestion("");
      setTaskId("");
      await onRefresh();
      setMessage(t("clarification.created"));
    } catch (error) {
      setMessage(errorText(error));
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="panel">
      <Header title={t("tab.clarifications")} subtitle={t("clarification.subtitle")} />
      <form className="clarification-form" onSubmit={ask}>
        <label>{t("table.task")}<select value={taskId} onChange={(event) => setTaskId(event.target.value)}>
          <option value="">{t("clarification.general")}</option>
          {tasks.map((task) => <option key={task.id} value={task.id}>{task.title}</option>)}
        </select></label>
        <label className="span-2">{t("clarification.question")}<textarea className="short" value={question} onChange={(event) => setQuestion(event.target.value)} required /></label>
        <div className="toolbar">
          <button type="submit" disabled={loading}>{loading ? t("status.refreshing") : t("clarification.ask")}</button>
          <button type="button" onClick={() => onRefresh().catch((error) => setMessage(errorText(error)))}>{t("common.refresh")}</button>
          {message && <span className="muted">{message}</span>}
        </div>
      </form>
      {clarifications.length ? (
        <div className="clarification-list">
          {clarifications.map((item) => <ClarificationCard key={item.id} item={item} />)}
        </div>
      ) : (
        <EmptyState title={t("empty.clarificationsTitle")} text={t("empty.clarificationsText")} />
      )}
    </section>
  );
}

function ClarificationCard({ item }: { item: Clarification }) {
  const { t } = useI18n();
  return (
    <article className="clarification-card">
      <div className="clarification-head">
        <strong>{item.task_title || t("clarification.general")}</strong>
        <span className="meta-row">
          <span className="pill">{t(`clarification.status.${item.status}`)}</span>
          <span className="pill">{t(`clarification.visibility.${item.visibility}`)}</span>
          <span>{formatDate(item.created_at)}</span>
        </span>
      </div>
      <p>{item.question}</p>
      {item.answer ? <div className="answer"><strong>{t("clarification.answer")}</strong><p>{item.answer}</p></div> : <span className="muted">{t("clarification.noAnswer")}</span>}
    </article>
  );
}
