// Thin fetch wrapper -- deliberately not axios (installed but unused so
// far; plain fetch + Vite's dev proxy to the FastAPI backend, see
// vite.config.ts, is enough for same-origin /api/* calls). Throws ApiClientError
// on any non-2xx response so TanStack Query's error handling works uniformly.

import type { ApiError } from "./types";
import {privateRequestScope} from './sessionEpoch.ts';

export class ApiClientError extends Error {
  status: number;
  constructor(status: number, detail: string) {
    super(detail);
    this.status = status;
  }
}

let csrfToken = "";
export function setCsrfToken(value: string) { csrfToken = value; }

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const auth = path.startsWith('/api/auth/');
  const scope = auth ? null : privateRequestScope();
  try {
  const res = await fetch(path, {
    ...init,
    credentials: "same-origin",
    signal: scope && init?.signal ? AbortSignal.any([scope.signal, init.signal]) : scope?.signal ?? init?.signal,
    headers: {
      ...(init?.body && !(init.body instanceof FormData) ? { "Content-Type": "application/json" } : {}),
      ...(init?.method && init.method !== "GET" ? {"X-CSRF-Token": csrfToken} : {}),
      ...init?.headers,
    },
  });
  scope?.assertCurrent();
  if (!res.ok) {
    // The identity probe owns its expected anonymous 401. Re-entering expiry
    // from /auth/me would create a probe/expiry loop.
    if(res.status === 401 && !auth) window.dispatchEvent(new Event("session-expired"));
    let detail = res.statusText;
    try {
      const body = (await res.json()) as ApiError;
      if (body.detail) detail = body.detail;
    } catch {
      // response body wasn't JSON -- keep statusText
    }
    scope?.assertCurrent();
    if (res.status === 405 && path.startsWith("/api/leads/web-runs")) {
      detail = "The running API does not support this research endpoint. Restart the project backend with python3 scripts/serve_local.py, then try again.";
    }
    throw new ApiClientError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  const body = (await res.json()) as T;
  scope?.assertCurrent();
  return body;
  } finally { scope?.finish(); }
}

export const api = {
  get: <T>(path: string, init?: RequestInit) => request<T>(path, init),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body: body !== undefined ? JSON.stringify(body) : undefined }),
  postForm: <T>(path: string, form: FormData) => request<T>(path, { method: "POST", body: form }),
};
