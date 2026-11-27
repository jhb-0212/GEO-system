/**
 * 资质证据图片：上传/删除/图片地址。
 *
 * 单独放一个模块而不是塞进 workbenchClient，是因为 evidence-image 走的是
 * multipart 与二进制代理，和普通 JSON 接口不是一套；顺带避免改动公共 client。
 */

import { WorkbenchApiError } from "@/lib/workbench/client";
import type { CertificationRecord } from "@/lib/workbench/types";

export interface CertificationImageRecord extends CertificationRecord {
  evidence_image_url?: string | null;
  evidence_image_name?: string | null;
}

const SESSION_CODES = new Set(["unauthorized", "token_expired", "token_invalid", "token_stale", "user_inactive"]);

function endpoint(projectId: string, id: string, version?: string | null): string {
  const query = new URLSearchParams({ project_id: projectId });
  if (version) query.set("v", version);
  return `/internal/workbench/certifications/${encodeURIComponent(id)}/evidence-image?${query.toString()}`;
}

async function readCertification(response: Response): Promise<CertificationImageRecord> {
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    const code = typeof payload?.error?.code === "string" ? payload.error.code : "upstream_error";
    if (response.status === 401 || SESSION_CODES.has(code)) {
      try { await fetch("/internal/session", { method: "DELETE" }); } catch { /* 继续跳登录 */ }
      window.location.replace("/login");
    }
    const message = typeof payload?.error?.message === "string" ? payload.error.message : "证据图片操作失败";
    throw new WorkbenchApiError(response.status, code, message);
  }
  return payload.data as CertificationImageRecord;
}

export function certificationImageUrl(projectId: string, id: string, version?: string | null): string {
  return endpoint(projectId, id, version);
}

export async function uploadCertificationImage(
  projectId: string,
  id: string,
  file: File,
): Promise<CertificationImageRecord> {
  const form = new FormData();
  form.append("file", file, file.name);
  return readCertification(await fetch(endpoint(projectId, id), { method: "POST", body: form }));
}

export async function deleteCertificationImage(
  projectId: string,
  id: string,
): Promise<CertificationImageRecord> {
  return readCertification(await fetch(endpoint(projectId, id), { method: "DELETE" }));
}
