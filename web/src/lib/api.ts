// The one way the app talks to the API.
//
// Tokens: the access token lives only in memory (10 minutes). The refresh token is kept in
// sessionStorage on a shared device, so it dies with the tab, or in localStorage when the
// citizen says this is their own device: the same two trust modes the API gives sessions.
// A 401 triggers one refresh and one retry; concurrent callers share that refresh.

import type { Lang, Tokens } from "./types";

const API = "/api/v1";
const REFRESH_KEY = "grs.refresh";
const DEVICE_KEY = "grs.device";

export type TrustMode = "PERSONAL" | "SHARED";

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public fields: Record<string, unknown> = {},
    public requestId = "",
    public retryAfter: number | null = null,
  ) {
    super(message);
  }

  /** The first message for a form field, if the API flagged it. */
  field(name: string): string | undefined {
    const v = this.fields[name];
    if (Array.isArray(v)) return typeof v[0] === "string" ? v[0] : undefined;
    return typeof v === "string" ? v : undefined;
  }
}

let access: string | null = null;
let language: Lang = "bn";
let refreshing: Promise<boolean> | null = null;
const listeners = new Set<() => void>();

function safe<T>(fn: () => T, fallback: T): T {
  try {
    return fn();
  } catch {
    return fallback;
  }
}

function readRefresh(): string | null {
  return safe(
    () => sessionStorage.getItem(REFRESH_KEY) ?? localStorage.getItem(REFRESH_KEY),
    null,
  );
}

export function trustMode(): TrustMode {
  return safe(() => (localStorage.getItem(REFRESH_KEY) ? "PERSONAL" : "SHARED"), "SHARED");
}

export function setLanguage(lang: Lang) {
  language = lang;
}

export function deviceToken(): string | undefined {
  return safe(() => localStorage.getItem(DEVICE_KEY) ?? undefined, undefined);
}

export function rememberDevice(token: string) {
  safe(() => localStorage.setItem(DEVICE_KEY, token), undefined);
}

export function hasSession(): boolean {
  return access !== null || readRefresh() !== null;
}

/** Called when the session ends (logout, expiry, or another tab logged out). */
export function onSessionEnd(fn: () => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export function startSession(tokens: Tokens, mode: TrustMode) {
  access = tokens.access;
  safe(() => {
    sessionStorage.removeItem(REFRESH_KEY);
    localStorage.removeItem(REFRESH_KEY);
    (mode === "PERSONAL" ? localStorage : sessionStorage).setItem(REFRESH_KEY, tokens.refresh);
  }, undefined);
}

export function endSession() {
  access = null;
  safe(() => {
    sessionStorage.removeItem(REFRESH_KEY);
    localStorage.removeItem(REFRESH_KEY);
  }, undefined);
  listeners.forEach((fn) => fn());
}

// Another tab logged out on this device: follow it.
if (typeof window !== "undefined") {
  window.addEventListener("storage", (e) => {
    if (e.key === REFRESH_KEY && e.newValue === null && access !== null) endSession();
  });
}

async function refresh(): Promise<boolean> {
  const token = readRefresh();
  if (!token) return false;
  refreshing ??= (async () => {
    try {
      const res = await fetch(`${API}/auth/token/refresh`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "Accept-Language": language },
        body: JSON.stringify({ refresh: token }),
      });
      if (!res.ok) {
        // A network failure keeps the session; only the API saying no ends it.
        if (res.status === 401 || res.status === 400) endSession();
        return false;
      }
      startSession((await res.json()) as Tokens, trustMode());
      return true;
    } catch {
      return false;
    } finally {
      refreshing = null;
    }
  })();
  return refreshing;
}

/** Make sure there is an access token, refreshing if this tab has none yet. */
export async function resume(): Promise<boolean> {
  if (access) return true;
  return refresh();
}

// A 401 with one of these means the access token is missing or stale. Other 401s (a wrong
// current password, say) are answers about the request, not the session.
const SESSION_CODES = new Set(["NOT_AUTHENTICATED", "AUTHENTICATION_FAILED", "SESSION_EXPIRED"]);

async function sessionRefused(res: Response): Promise<boolean> {
  if (res.status !== 401) return false;
  try {
    const body = (await res.clone().json()) as { error?: { code?: string } };
    return SESSION_CODES.has(body.error?.code ?? "");
  } catch {
    return false;
  }
}

export interface Options {
  method?: string;
  body?: unknown;
  headers?: Record<string, string>;
  /** Default true; false for calls made before login. */
  auth?: boolean;
}

export interface Answer<T> {
  data: T;
  status: number;
  etag: string | null;
}

export async function call<T>(path: string, opts: Options = {}): Promise<Answer<T>> {
  const auth = opts.auth ?? true;
  const send = () => {
    const headers: Record<string, string> = {
      Accept: "application/json",
      "Accept-Language": language,
      ...opts.headers,
    };
    if (opts.body !== undefined) headers["Content-Type"] = "application/json";
    if (auth && access) headers.Authorization = `Bearer ${access}`;
    const url = path.startsWith("http") || path.startsWith("/") ? path : `${API}/${path}`;
    return fetch(url, {
      method: opts.method ?? (opts.body === undefined ? "GET" : "POST"),
      headers,
      body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
    });
  };

  let res: Response;
  try {
    if (auth && !access) await refresh();
    res = await send();
    if (auth && (await sessionRefused(res)) && (await refresh())) res = await send();
  } catch {
    throw new ApiError(0, "NETWORK", "");
  }

  const etag = res.headers.get("ETag");
  if (res.status === 204 || res.status === 304) {
    return { data: undefined as T, status: res.status, etag };
  }
  const text = await res.text();
  let body: unknown = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = null;
  }
  if (!res.ok) {
    const err = (body as { error?: Record<string, unknown> } | null)?.error;
    const retry = Number(res.headers.get("Retry-After"));
    if (auth && SESSION_CODES.has(err?.code as string)) endSession();
    throw new ApiError(
      res.status,
      (err?.code as string) ?? `HTTP_${res.status}`,
      (err?.message as string) ?? "",
      (err?.fields as Record<string, unknown>) ?? {},
      (err?.request_id as string) ?? res.headers.get("X-Request-ID") ?? "",
      Number.isFinite(retry) && retry > 0 ? retry : null,
    );
  }
  return { data: body as T, status: res.status, etag };
}

export async function get<T>(path: string, opts: Options = {}): Promise<T> {
  return (await call<T>(path, opts)).data;
}

export async function post<T>(path: string, body: unknown = {}, opts: Options = {}): Promise<T> {
  return (await call<T>(path, { ...opts, method: "POST", body })).data;
}

export async function patch<T>(path: string, body: unknown, opts: Options = {}): Promise<T> {
  return (await call<T>(path, { ...opts, method: "PATCH", body })).data;
}

export async function del(path: string, opts: Options = {}): Promise<void> {
  await call<void>(path, { ...opts, method: "DELETE" });
}

/** A key for one logical attempt: keep it across retries of the same submit. */
export function idempotencyKey(): string {
  return crypto.randomUUID();
}

/** Query string from the defined values only. */
export function qs(params: Record<string, string | number | boolean | undefined | null>): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") q.set(k, String(v));
  }
  const s = q.toString();
  return s ? `?${s}` : "";
}
