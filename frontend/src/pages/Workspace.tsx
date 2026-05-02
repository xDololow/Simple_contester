import { useCallback, useEffect, useState } from "react";
import { useI18n } from "../i18n";
import type { ApiClient, Contest, User } from "../types";
import { AdminDashboard } from "./admin/AdminDashboard";
import { ContestView } from "./contest/ContestView";

export function Workspace({ api, me, token }: { api: ApiClient; me: User; token: string }) {
  const { t } = useI18n();
  const [contests, setContests] = useState<Contest[]>([]);
  const [selectedContestId, setSelectedContestId] = useState<number | null>(null);
  const [view, setView] = useState<"contest" | "admin">("contest");
  const selectedContest = contests.find((contest) => contest.id === selectedContestId) || null;

  const loadContests = useCallback(async () => {
    const next = await api<Contest[]>("/api/contests");
    setContests(next);
    setSelectedContestId((current) => current ?? next[0]?.id ?? null);
  }, [api]);

  useEffect(() => {
    loadContests().catch(console.error);
    const interval = window.setInterval(() => loadContests().catch(console.error), 5000);
    return () => window.clearInterval(interval);
  }, [loadContests]);

  return (
    <div className="layout">
      <aside className="sidebar">
        <nav className="workspace-switcher" aria-label={t("nav.workspace")}>
          <button className={view === "contest" ? "active" : ""} onClick={() => setView("contest")} type="button">
            {t("nav.participantWorkspace")}
          </button>
          {me.role === "admin" && (
            <button className={view === "admin" ? "active" : ""} onClick={() => setView("admin")} type="button">
              {t("nav.adminWorkspace")}
            </button>
          )}
        </nav>
        <div className="section-title">
          <h2>{t("nav.contests")}</h2>
          <span className="muted">{contests.length}</span>
        </div>
        <div className="list">
          {contests.map((contest) => (
            <button
              key={contest.id}
              className={contest.id === selectedContestId && view === "contest" ? "active item" : "item"}
              onClick={() => {
                setSelectedContestId(contest.id);
                setView("contest");
              }}
            >
              <span>{contest.title}</span>
              <span className="pill">{t(`status.${contest.status}`)}</span>
            </button>
          ))}
          {!contests.length && <p className="muted">{t("nav.noContests")}</p>}
        </div>
      </aside>
      <section className="content">
        {view === "admin" && me.role === "admin" ? (
          <AdminDashboard api={api} token={token} reloadContests={loadContests} />
        ) : selectedContest ? (
          <ContestView api={api} contest={selectedContest} me={me} token={token} />
        ) : (
          <div className="panel">{t("nav.noContests")}</div>
        )}
      </section>
    </div>
  );
}
