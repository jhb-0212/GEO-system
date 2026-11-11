import type { Lead, ReviewItem, WorkbenchSnapshot } from "./types";

async function readResponse<T>(response: Response): Promise<T> {
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error?.message ?? "请求失败，请稍后再试");
  }
  return payload.data as T;
}

export const workbenchClient = {
  async snapshot(projectId?: string): Promise<WorkbenchSnapshot> {
    const query = projectId && projectId !== "all" ? `?project_id=${encodeURIComponent(projectId)}` : "";
    return readResponse<WorkbenchSnapshot>(await fetch(`/api/workbench${query}`, { cache: "no-store" }));
  },
  async createLead(input: Pick<Lead, "contactName" | "phone" | "interest" | "source" | "projectId">): Promise<Lead> {
    return readResponse<Lead>(await fetch("/api/workbench/leads", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    }));
  },
  async review(id: string, status: "已通过" | "已驳回"): Promise<ReviewItem> {
    return readResponse<ReviewItem>(await fetch(`/api/workbench/reviews/${encodeURIComponent(id)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status }),
    }));
  },
  async logout(): Promise<void> {
    await fetch("/api/session", { method: "DELETE" });
  },
};
