import { redirect } from "next/navigation";

import { BackendError, backendRequest } from "@/lib/workbench/backend";
import { getSessionToken, isMockMode } from "@/lib/workbench/server-session";

import { MediaMatrixAdmin } from "./media-matrix-admin";

// 后台必须读当前登录态，明确按阻塞路由处理。
export const instant = false;

export default async function MediaMatrixAdminPage() {
  if (isMockMode()) redirect("/workbench");
  const token = await getSessionToken();
  if (!token) redirect("/login?next=/media-matrix/admin");

  try {
    const me = await backendRequest<{ is_system_admin: boolean }>("/api/v1/auth/me", token);
    if (!me.data.is_system_admin) redirect("/workbench");
  } catch (error) {
    if (error instanceof BackendError && [401, 403].includes(error.status)) {
      redirect(`/login?next=/media-matrix/admin`);
    }
    throw error;
  }

  return <MediaMatrixAdmin />;
}
