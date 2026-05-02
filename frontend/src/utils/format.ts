import type { Flash } from "../types";

export const emptyFlash: Flash = { kind: "ok", text: "" };

export function errorText(error: unknown) {
  return error instanceof Error ? error.message : "Request failed";
}

export function formatDate(value?: string | null) {
  if (!value) return "-";
  return new Date(value).toLocaleString();
}

export function formatScore(value: number) {
  return value.toFixed(2);
}

export function toLocalInputValue(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return new Date(date.getTime() - date.getTimezoneOffset() * 60_000).toISOString().slice(0, 16);
}

export function fromLocalInputValue(value: string) {
  return new Date(value).toISOString();
}

export function joinIds(ids: number[]) {
  return ids.join(", ");
}

export function parseIds(value: string) {
  if (!value.trim()) return [];
  return value
    .split(/[,\s]+/)
    .map((item) => Number(item))
    .filter((item) => Number.isInteger(item) && item > 0);
}

export function verdictClass(verdict: string) {
  return `verdict ${verdict.replaceAll(" ", "-")}`;
}
