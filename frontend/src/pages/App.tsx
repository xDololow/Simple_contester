import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { createApiClient } from "../api/client";
import { FlashMessage, LanguageSwitcher } from "../components/shared";
import { useI18n } from "../i18n";
import type { ApiClient, Flash, User } from "../types";
import { emptyFlash, errorText } from "../utils/format";
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
  const [loginError, setLoginError] = useState("");
  const api = useMemo(() => createApiClient(token), [token]);

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
          <AccountPanel api={api} />
          <button onClick={clearToken}>{t("login.logout")}</button>
        </div>
      </header>
      <Workspace api={api} me={me} token={token} />
    </main>
  );
}

function AccountPanel({ api }: { api: ApiClient }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const [oldPassword, setOldPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [flash, setFlash] = useState<Flash>(emptyFlash);
  const [saving, setSaving] = useState(false);

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

  return (
    <div className="account-menu">
      <button type="button" onClick={() => setOpen((value) => !value)}>{t("account.account")}</button>
      {open && (
        <form className="account-popover" onSubmit={submit}>
          <h3>{t("account.changePassword")}</h3>
          <label>
            {t("account.currentPassword")}
            <input type="password" value={oldPassword} onChange={(event) => setOldPassword(event.target.value)} required />
          </label>
          <label>
            {t("account.newPassword")}
            <input type="password" minLength={3} value={newPassword} onChange={(event) => setNewPassword(event.target.value)} required />
          </label>
          <FlashMessage flash={flash} />
          <div className="row-actions">
            <button type="submit" disabled={saving}>{saving ? t("common.save") : t("account.changePassword")}</button>
            <button type="button" onClick={() => setOpen(false)}>{t("common.cancel")}</button>
          </div>
        </form>
      )}
    </div>
  );
}
