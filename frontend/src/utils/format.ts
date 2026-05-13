import type { Flash } from "../types";

export const DEFAULT_SITE_TIMEZONE = "Asia/Krasnoyarsk";

export const emptyFlash: Flash = { kind: "ok", text: "" };

export function errorText(error: unknown) {
  return error instanceof Error ? error.message : "Request failed";
}

function safeTimeZone(timeZone = DEFAULT_SITE_TIMEZONE) {
  try {
    new Intl.DateTimeFormat("en-US", { timeZone }).format(new Date());
    return timeZone;
  } catch {
    return DEFAULT_SITE_TIMEZONE;
  }
}

export function browserTimeZone(fallback = DEFAULT_SITE_TIMEZONE) {
  return safeTimeZone(Intl.DateTimeFormat().resolvedOptions().timeZone || fallback);
}

function datePartsInTimeZone(date: Date, timeZone: string) {
  const formatter = new Intl.DateTimeFormat("en-CA", {
    timeZone: safeTimeZone(timeZone),
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23"
  });
  const parts = Object.fromEntries(formatter.formatToParts(date).map((part) => [part.type, part.value]));
  return {
    year: Number(parts.year),
    month: Number(parts.month),
    day: Number(parts.day),
    hour: Number(parts.hour),
    minute: Number(parts.minute),
    second: Number(parts.second)
  };
}

function pad(value: number) {
  return String(value).padStart(2, "0");
}

function timeZoneOffsetMs(date: Date, timeZone: string) {
  const parts = datePartsInTimeZone(date, timeZone);
  const asUTC = Date.UTC(parts.year, parts.month - 1, parts.day, parts.hour, parts.minute, parts.second);
  return asUTC - date.getTime();
}

export function parseApiDate(value: string) {
  const normalized = /(?:Z|[+-]\d{2}:?\d{2})$/.test(value) ? value : `${value}Z`;
  return new Date(normalized);
}

export function formatDate(value?: string | null, timeZone = DEFAULT_SITE_TIMEZONE) {
  if (!value) return "-";
  return parseApiDate(value).toLocaleString(undefined, { timeZone: safeTimeZone(timeZone) });
}

export function formatScore(value: number) {
  return value.toFixed(2);
}

export function toLocalInputValue(value: string, timeZone = DEFAULT_SITE_TIMEZONE) {
  const date = parseApiDate(value);
  if (Number.isNaN(date.getTime())) return "";
  const parts = datePartsInTimeZone(date, timeZone);
  return `${parts.year}-${pad(parts.month)}-${pad(parts.day)}T${pad(parts.hour)}:${pad(parts.minute)}`;
}

export function fromLocalInputValue(value: string, timeZone = DEFAULT_SITE_TIMEZONE) {
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/.exec(value);
  if (!match) return new Date(value).toISOString();
  const [, rawYear, rawMonth, rawDay, rawHour, rawMinute] = match;
  const year = Number(rawYear);
  const month = Number(rawMonth);
  const day = Number(rawDay);
  const hour = Number(rawHour);
  const minute = Number(rawMinute);
  const localAsUTC = Date.UTC(year, month - 1, day, hour, minute);
  let utcMs = localAsUTC;
  for (let index = 0; index < 3; index += 1) {
    const nextUtcMs = localAsUTC - timeZoneOffsetMs(new Date(utcMs), timeZone);
    if (Math.abs(nextUtcMs - utcMs) < 1000) break;
    utcMs = nextUtcMs;
  }
  return new Date(utcMs).toISOString();
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
