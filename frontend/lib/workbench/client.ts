import type { Lead, ReviewItem, WorkbenchSnapshot } from "./types";

export class WorkbenchApiError extends Error {
  constructor(public status: number, public code: string, message: string) {
    super(message);
  }
}

const sessionCodes = new Set(["unauthorized", "token_expired", "token_invalid", "user_inactive"]);

function errorMessage(status: number, code: string, fallback?: string): string {
  if (status === 401 || sessionCodes.has(code)) return "登录已失效，请重新登录";
  if (code === "project_forbidden") return "你没有访问该项目的权限";
  if (code === "insufficient_role") return "当前角色没有执行此操作的权限";
  if (code === "system_admin_only") return "此操作仅限系统管理员";
  if (status === 403) return "没有执行此操作的权限";
  return fallback || "请求失败，请稍后再试";
}

async function readResponse<T>(response: Response): Promise<T> {
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    const code = typeof payload?.error?.code === "string" ? payload.error.code : "upstream_error";
    if (response.status === 401 || sessionCodes.has(code)) {
      try { await fetch("/internal/session", { method: "DELETE" }); } catch { /* Continue to login. */ }
      window.location.replace("/login");
    }
    throw new WorkbenchApiError(response.status, code, errorMessage(response.status, code, payload?.error?.message));
  }
  return payload.data as T;
}

export const workbenchClient = {
  async snapshot(projectId?: string): Promise<WorkbenchSnapshot> {
    const query = projectId && projectId !== "all" ? `?project_id=${encodeURIComponent(projectId)}` : "";
    return readResponse<WorkbenchSnapshot>(await fetch(`/internal/workbench${query}`, { cache: "no-store" }));
  },
  async createLead(input: Pick<Lead, "contactName" | "phone" | "interest" | "source" | "projectId">): Promise<Lead> {
    return readResponse<Lead>(await fetch("/internal/workbench/leads", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    }));
  },
  async review(id: string, status: "已通过" | "已驳回"): Promise<ReviewItem> {
    return readResponse<ReviewItem>(await fetch(`/internal/workbench/reviews/${encodeURIComponent(id)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status }),
    }));
  },
  async logout(): Promise<void> {
    await fetch("/internal/session", { method: "DELETE" });
  },
};
