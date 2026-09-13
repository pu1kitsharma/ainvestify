// Thin fetch wrapper -- deliberately not axios (installed but unused so
// far; plain fetch + Vite's dev proxy to the FastAPI backend, see
// vite.config.ts, is enough for same-origin /api/* calls). Throws ApiClientError
// on any non-2xx response so TanStack Query's error handling works uniformly.

import type { ApiError } from "./types";

export class ApiClientError extends Error {
  status: number;
  constructor(status: number, detail: string) {
    super(detail);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: {
      ...(init?.body && !(init.body instanceof FormData) ? { "Content-Type": "application/json" } : {}),
      ...init?.headers,
    },
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = (await res.json()) as ApiError;
      if (body.detail) detail = body.detail;
    } catch {
      // response body wasn't JSON -- keep statusText
    }
    throw new ApiClientError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body: body !== undefined ? JSON.stringify(body) : undefined }),
  postForm: <T>(path: string, form: FormData) => request<T>(path, { method: "POST", body: form }),
};
