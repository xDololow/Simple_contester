import { useI18n, type UiLanguage } from "../i18n";
import type { Flash, SubmissionDetail } from "../types";
import { formatDate, formatScore, verdictClass } from "../utils/format";

export function LanguageSwitcher() {
  const { language, setLanguage } = useI18n();
  const languages: UiLanguage[] = ["ru", "en"];
  return (
    <div className="language-switcher" aria-label="Language">
      {languages.map((item) => (
        <button key={item} className={language === item ? "active" : ""} onClick={() => setLanguage(item)} type="button">
          {item.toUpperCase()}
        </button>
      ))}
    </div>
  );
}

export function Header({ title, subtitle }: { title: string; subtitle?: string }) {
  return (
    <div className="section-title">
      <h3>{title}</h3>
      {subtitle && <span className="muted">{subtitle}</span>}
    </div>
  );
}

export function FlashMessage({ flash }: { flash: Flash }) {
  if (!flash.text) return null;
  return <p className={flash.kind === "error" ? "error" : "success"}>{flash.text}</p>;
}

export function SubmissionDetailView({ detail, compact = false }: { detail: SubmissionDetail | null; compact?: boolean }) {
  const { t } = useI18n();
  if (!detail) return <div className={compact ? "detail compact-detail" : "detail"}><p className="muted">{t("submission.select")}</p></div>;
  return (
    <div className={compact ? "detail compact-detail" : "detail"}>
      <Header title={t("title.submission", { id: detail.id })} subtitle={`${detail.language} · ${formatScore(detail.score)} ${t("common.points")}`} />
      <div className="kv">
        <span>{t("table.contest")}</span><strong>{detail.contest_id}</strong>
        <span>{t("table.task")}</span><strong>{detail.task_id}</strong>
        <span>{t("table.user")}</span><strong>{detail.user_id}</strong>
        <span>{t("table.judger")}</span><strong>{detail.judger_id || "-"}</strong>
        <span>{t("table.started")}</span><strong>{formatDate(detail.started_at)}</strong>
        <span>{t("table.finished")}</span><strong>{formatDate(detail.finished_at)}</strong>
      </div>
      {detail.compile_output && <pre className="output">{detail.compile_output}</pre>}
      <pre className="source">{detail.source_code}</pre>
      <table>
        <thead><tr><th>{t("table.test")}</th><th>{t("table.verdict")}</th><th>{t("table.time")}</th><th>{t("common.outputError")}</th></tr></thead>
        <tbody>
          {detail.results.map((result) => (
            <tr key={result.id}>
              <td>{result.task_test_id}</td>
              <td><span className={verdictClass(result.verdict)}>{t(`verdict.${result.verdict}`)}</span></td>
              <td>{result.time_ms} ms</td>
              <td><pre>{result.error || result.output || "-"}</pre></td>
            </tr>
          ))}
          {!detail.results.length && <tr><td colSpan={4}>{t("submission.noResults")}</td></tr>}
        </tbody>
      </table>
    </div>
  );
}
