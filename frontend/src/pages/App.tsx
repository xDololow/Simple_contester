import { useCallback, useEffect, useMemo, useState } from "react";
import { createApiClient } from "../api/client";
import { LanguageSwitcher } from "../components/shared";
import { useI18n } from "../i18n";
import type { User } from "../types";
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
          <button onClick={clearToken}>{t("login.logout")}</button>
        </div>
      </header>
      <Workspace api={api} me={me} token={token} />
    </main>
  );
}
