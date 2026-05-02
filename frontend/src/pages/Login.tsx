import React, { useState } from "react";
import { API_BASE } from "../api/client";
import { useI18n } from "../i18n";

export function Login({
  onLogin,
  error,
  setError
}: {
  onLogin: (token: string) => void;
  error: string;
  setError: (value: string) => void;
}) {
  const { t } = useI18n();
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("admin");

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setError("");
    const response = await fetch(`${API_BASE}/api/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password })
    });
    if (!response.ok) {
      setError(t("login.invalid"));
      return;
    }
    const data = await response.json();
    onLogin(data.access_token);
  }

  return (
    <main className="login">
      <form onSubmit={submit} className="panel login-panel">
        <h1>Simple Contester</h1>
        <label>
          {t("login.username")}
          <input value={username} onChange={(event) => setUsername(event.target.value)} />
        </label>
        <label>
          {t("login.password")}
          <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} />
        </label>
        {error && <p className="error">{error}</p>}
        <button type="submit">{t("login.login")}</button>
      </form>
    </main>
  );
}
