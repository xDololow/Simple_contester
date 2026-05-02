import type { ApiClient } from "../types";

export const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";

export function createApiClient(token: string): ApiClient {
  return async (path, init = {}) => {
    const bodyHeaders = init.body instanceof FormData ? {} : { "Content-Type": "application/json" };
    const response = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: {
        ...bodyHeaders,
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(init.headers || {})
      }
    });
    if (!response.ok) {
      const body = await response.json().catch(() => ({ detail: response.statusText }));
      const detail = Array.isArray(body.detail) ? JSON.stringify(body.detail) : body.detail;
      throw new Error(detail || "Request failed");
    }
    if (response.status === 204) return undefined as never;
    return response.json();
  };
}
