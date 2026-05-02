import { useCallback, useEffect, useState } from "react";
import { FlashMessage, Header, SubmissionDetailView } from "../../components/shared";
import { useI18n } from "../../i18n";
import type { ApiClient, Contest, Flash, Language, ScoreboardRow, Submission, SubmissionDetail, Task, User } from "../../types";
import { emptyFlash, errorText, formatDate, formatScore, verdictClass } from "../../utils/format";

type ContestTab = "overview" | "tasks" | "submissions" | "scoreboard";

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

export function ContestView({ api, contest, me }: { api: ApiClient; contest: Contest; me: User }) {
  const { t } = useI18n();
  const [tasks, setTasks] = useState<Task[]>([]);
  const [submissions, setSubmissions] = useState<Submission[]>([]);
  const [scoreboard, setScoreboard] = useState<ScoreboardRow[]>([]);
  const [tab, setTab] = useState<ContestTab>("tasks");
  const [selectedTaskId, setSelectedTaskId] = useState<number | null>(null);
  const [selectedSubmissionId, setSelectedSubmissionId] = useState<number | null>(null);
  const [detail, setDetail] = useState<SubmissionDetail | null>(null);
  const [flash, setFlash] = useState<Flash>(emptyFlash);
  const selectedTask = tasks.find((task) => task.id === selectedTaskId) || tasks[0] || null;

  const refresh = useCallback(async () => {
    const [nextTasks, nextSubmissions, nextScoreboard] = await Promise.all([
      api<Task[]>(`/api/contests/${contest.id}/tasks`),
      api<Submission[]>(`/api/submissions?contest_id=${contest.id}`),
      api<ScoreboardRow[]>(`/api/contests/${contest.id}/scoreboard`)
    ]);
    setTasks(nextTasks);
    setSubmissions(nextSubmissions);
    setScoreboard(nextScoreboard);
    setSelectedTaskId((current) => current ?? nextTasks[0]?.id ?? null);
  }, [api, contest.id]);

  useEffect(() => {
    refresh().catch((error) => setFlash({ kind: "error", text: errorText(error) }));
    const interval = window.setInterval(() => refresh().catch(console.error), 2000);
    return () => window.clearInterval(interval);
  }, [refresh]);

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
          <span>{contest.time_mode === "individual" ? `${contest.individual_duration_minutes} ${t("table.minutes").toLowerCase()}` : t("common.fixed")}</span>
          <span>{formatDate(contest.starts_at)} - {formatDate(contest.ends_at)}</span>
        </div>
      </section>
      <FlashMessage flash={flash} />
      <nav className="tabs contest-tabs" aria-label={t("nav.contestSections")}>
        {[
          ["overview", t("tab.overview")],
          ["tasks", t("tab.tasks")],
          ["submissions", t("tab.submissions")],
          ["scoreboard", t("title.scoreboard")]
        ].map(([id, label]) => (
          <button key={id} className={tab === id ? "active" : ""} onClick={() => setTab(id as ContestTab)} type="button">
            {label}
          </button>
        ))}
      </nav>

      {tab === "overview" && (
        <section className="panel">
          <Header title={t("tab.overview")} subtitle={t("contest.summary")} />
          <div className="overview-grid">
            <div className="stat"><strong>{tasks.length}</strong><span>{t("tab.tasks")}</span></div>
            <div className="stat"><strong>{submissions.length}</strong><span>{t("tab.submissions")}</span></div>
            <div className="stat"><strong>{scoreboard.length}</strong><span>{t("title.scoreboard")}</span></div>
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
              {selectedTask && <SubmitBox api={api} contestId={contest.id} task={selectedTask} onSubmitted={refresh} />}
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
          <Header title={t("title.scoreboard")} subtitle={t("common.live")} />
          {scoreboard.length ? (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr><th>{t("table.user")}</th><th>{t("table.points")}</th><th>{t("table.penalty")}</th>{tasks.map((task) => <th key={task.id}>{task.title}</th>)}</tr>
                </thead>
                <tbody>
                  {scoreboard.map((row) => (
                    <tr key={row.user_id} className={row.user_id === me.id ? "self" : ""}>
                      <td>{row.display_name}</td>
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

function SubmitBox({ api, contestId, task, onSubmitted }: { api: ApiClient; contestId: number; task: Task; onSubmitted: () => void }) {
  const { t } = useI18n();
  const [language, setLanguage] = useState<Language>("python");
  const [sourceCode, setSourceCode] = useState("print(input())");
  const [message, setMessage] = useState("");

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
    <div className="submit">
      <h3>{task.title}</h3>
      <p>{task.statement}</p>
      <div className="limits">{task.time_limit_ms} ms · {task.memory_limit_mb} MB · {formatScore(task.points)} {t("common.points")}</div>
      <select value={language} onChange={(event) => setLanguage(event.target.value as Language)}>
        {SUBMISSION_LANGUAGES.map((item) => (
          <option key={item.value} value={item.value}>{item.label}</option>
        ))}
      </select>
      <textarea className="code" value={sourceCode} onChange={(event) => setSourceCode(event.target.value)} />
      <button onClick={submit}>{t("submission.submit")}</button>
      {message && <span className="muted">{message}</span>}
    </div>
  );
}
