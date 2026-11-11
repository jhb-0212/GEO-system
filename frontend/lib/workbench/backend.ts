import type { ApiEnvelope, ApiErrorEnvelope } from "./types";

export class BackendError extends Error {
  constructor(public status: number, public code: string, message: string) {
    super(message);
  }
}

// Only server routes import this file. The browser always calls the same-origin frontend API.
export async function backendRequest<T>(
  path: `/api/v1/${string}`,
  token: string,
  init: RequestInit = {},
): Promise<ApiEnvelope<T>> {
  const base = process.env.GEO_API_URL ?? (process.env.NODE_ENV === "production" ? "http://api:8000" : "http://host.docker.internal:8000");
  const response = await fetch(new URL(path, base), {
    ...init,
    cache: "no-store",
    headers: {
      Accept: "application/json",
      ...(init.body ? { "Content-Type": "application/json" } : {}),
      Authorization: `Bearer ${token}`,
      ...init.headers,
    },
  });

  const payload: ApiEnvelope<T> | ApiErrorEnvelope = await response.json();
  if (!response.ok || "error" in payload) {
    const error = "error" in payload ? payload.error : { code: "upstream_error", message: "后端请求失败" };
    throw new BackendError(response.status, error.code, error.message);
  }
  return payload;
}
