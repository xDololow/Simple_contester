import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { API_BASE, createApiClient } from "../api/client";
import { FlashMessage, LanguageSwitcher } from "../components/shared";
import { useI18n } from "../i18n";
import type { ApiClient, AppConfig, Flash, User } from "../types";
import { DEFAULT_SITE_TIMEZONE, browserTimeZone, emptyFlash, errorText } from "../utils/format";
import { Login } from "./Login";
import { Workspace } from "./Workspace";

function useToken() {
  const [token, setTokenState] = useState(localStorage.getItem("token") || "");
  const setToken = useCallback((value: string) => {
    localStorage.setItem("token", value);
    setTokenState(value);
  }, []);
  const clearToken = useCallback(() => {
    localStorage.removeItem("token");
    setTokenState("");
  }, []);
  return { token, setToken, clearToken };
}

export function App() {
  const { token, setToken, clearToken } = useToken();
  const { t } = useI18n();
  const [me, setMe] = useState<User | null>(null);
  const [siteTimezone, setSiteTimezone] = useState(DEFAULT_SITE_TIMEZONE);
  const [loginError, setLoginError] = useState("");
  const api = useMemo(() => createApiClient(token), [token]);

  useEffect(() => {
    fetch(`${API_BASE}/api/config`)
      .then((response) => response.ok ? response.json() : Promise.reject(new Error(response.statusText)))
      .then((config: AppConfig) => setSiteTimezone(config.site_timezone || DEFAULT_SITE_TIMEZONE))
      .catch(() => setSiteTimezone(DEFAULT_SITE_TIMEZONE));
  }, []);

  useEffect(() => {
    if (!token) {
      setMe(null);
      return;
    }
    api<User>("/api/me")
      .then(setMe)
      .catch(() => clearToken());
  }, [api, clearToken, token]);

  if (!token || !me) {
    return <Login onLogin={setToken} error={loginError} setError={setLoginError} />;
  }
  const detectedTimezone = browserTimeZone(siteTimezone);
  const effectiveTimezone = me.timezone || detectedTimezone || siteTimezone;

  return (
    <main className="app">
      <header className="topbar">
        <div>
          <h1>Simple Contester</h1>
          <span>
            {me.display_name} · {t(`role.${me.role}`)}
          </span>
        </div>
        <div className="topbar-actions">
          <LanguageSwitcher />
          <AccountPanel api={api} me={me} siteTimezone={siteTimezone} detectedTimezone={detectedTimezone} onUserChanged={setMe} />
          <button onClick={clearToken}>{t("login.logout")}</button>
        </div>
      </header>
      <Workspace api={api} me={me} token={token} siteTimezone={effectiveTimezone} />
    </main>
  );
}

function AccountPanel({
  api,
  me,
  siteTimezone,
  detectedTimezone,
  onUserChanged
}: {
  api: ApiClient;
  me: User;
  siteTimezone: string;
  detectedTimezone: string;
  onUserChanged: (user: User) => void;
}) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const [oldPassword, setOldPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [timezone, setTimezone] = useState(me.timezone || "");
  const [flash, setFlash] = useState<Flash>(emptyFlash);
  const [saving, setSaving] = useState(false);
  const [savingTimezone, setSavingTimezone] = useState(false);

  useEffect(() => {
    setTimezone(me.timezone || "");
  }, [me.timezone]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setFlash(emptyFlash);
    try {
      await api<User>("/api/me/password", {
        method: "POST",
        body: JSON.stringify({ old_password: oldPassword, new_password: newPassword })
      });
      setOldPassword("");
      setNewPassword("");
      setFlash({ kind: "ok", text: t("account.passwordChanged") });
    } catch (error) {
      setFlash({ kind: "error", text: errorText(error) });
    } finally {
      setSaving(false);
    }
  }

  async function submitTimezone(event: FormEvent) {
    event.preventDefault();
    setSavingTimezone(true);
    setFlash(emptyFlash);
    try {
      const nextUser = await api<User>("/api/me/preferences", {
        method: "PATCH",
        body: JSON.stringify({ timezone: timezone.trim() || null })
      });
      onUserChanged(nextUser);
      setFlash({ kind: "ok", text: t("account.timezoneChanged") });
    } catch (error) {
      setFlash({ kind: "error", text: errorText(error) });
    } finally {
      setSavingTimezone(false);
    }
  }

  return (
    <div className="account-menu">
      <button type="button" onClick={() => setOpen((value) => !value)}>{t("account.account")}</button>
      {open && (
        <div className="account-popover">
          <form onSubmit={submitTimezone}>
            <h3>{t("account.preferences")}</h3>
            <label>
              {t("account.timezone")}
              <input
                list="timezone-options"
                value={timezone}
                onChange={(event) => setTimezone(event.target.value)}
                placeholder={t("account.autoTimezone", { timezone: detectedTimezone })}
              />
              <datalist id="timezone-options">
                {timezoneOptions(siteTimezone, detectedTimezone).map((item) => <option key={item} value={item} />)}
              </datalist>
            </label>
            <p className="muted">{timezone ? t("account.customTimezone") : t("account.autoTimezoneDetail", { timezone: detectedTimezone, site: siteTimezone })}</p>
            <div className="row-actions">
              <button type="submit" disabled={savingTimezone}>{savingTimezone ? t("common.save") : t("account.saveTimezone")}</button>
              <button type="button" onClick={() => setTimezone("")}>{t("account.useAutoTimezone")}</button>
            </div>
          </form>
          <form onSubmit={submit}>
            <h3>{t("account.changePassword")}</h3>
            <label>
              {t("account.currentPassword")}
              <input type="password" value={oldPassword} onChange={(event) => setOldPassword(event.target.value)} required />
            </label>
            <label>
              {t("account.newPassword")}
              <input type="password" minLength={3} value={newPassword} onChange={(event) => setNewPassword(event.target.value)} required />
            </label>
            <div className="row-actions">
              <button type="submit" disabled={saving}>{saving ? t("common.save") : t("account.changePassword")}</button>
              <button type="button" onClick={() => setOpen(false)}>{t("common.cancel")}</button>
            </div>
          </form>
          <FlashMessage flash={flash} />
        </div>
      )}
    </div>
  );
}

function timezoneOptions(siteTimezone: string, detectedTimezone: string) {
  const supportedValuesOf = (Intl as unknown as { supportedValuesOf?: (key: string) => string[] }).supportedValuesOf;
  const values = supportedValuesOf ? supportedValuesOf("timeZone") : [
    "UTC",
    "Europe/Moscow",
    "Asia/Krasnoyarsk",
    "Asia/Novosibirsk",
    "Asia/Yekaterinburg",
    "Asia/Irkutsk",
    "Asia/Vladivostok",
    "Europe/London",
    "Europe/Berlin",
    "America/New_York",
    "America/Los_Angeles"
  ];
  return Array.from(new Set([siteTimezone, detectedTimezone, ...values].filter(Boolean))).sort();
}
