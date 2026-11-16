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
  const base = process.env.GEO_API_URL ?? (process.env.NODE_ENV === "production" ? "http://api:8000" : "http://localhost:8000");
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

  const payload: ApiEnvelope<T> | ApiErrorEnvelope = await response.json().catch(() => ({
    error: { code: "invalid_response", message: "后端响应格式不正确" },
  }));
  if (!response.ok || "error" in payload) {
    const error = "error" in payload ? payload.error : { code: "upstream_error", message: "后端请求失败" };
    throw new BackendError(response.ok ? 502 : response.status, error.code, error.message);
  }
  if (!payload || typeof payload !== "object" || !("data" in payload)) {
    throw new BackendError(502, "invalid_response", "后端响应缺少 data 字段");
  }
  return payload;
}
