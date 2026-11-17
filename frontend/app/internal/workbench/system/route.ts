import { NextResponse } from "next/server";

import { BackendError, backendRequest } from "@/lib/workbench/backend";
import { getSessionToken, isMockMode } from "@/lib/workbench/server-session";

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function failure(error: unknown) {
  if (error instanceof BackendError) {
    return NextResponse.json({ error: { code: error.code, message: error.message } }, { status: error.status });
  }
  return NextResponse.json({ error: { code: "backend_unavailable", message: "无法连接后端" } }, { status: 503 });
}

/**
 * 系统管理员动作：重置他人密码、解除登录限流。
 *
 * 权限由后端 `is_system_admin` 判定，这里只做参数校验与转发，
 * 避免把「谁能重置密码」的规则复制到前端。
 */
export async function POST(request: Request) {
  const token = await getSessionToken();
  if (!token) {
    return NextResponse.json({ error: { code: "unauthorized", message: "请先登录" } }, { status: 401 });
  }
  if (isMockMode()) {
    return NextResponse.json({ error: { code: "mock_only", message: "演示模式不调用真实接口" } }, { status: 400 });
  }

  const url = new URL(request.url);
  const kind = url.searchParams.get("kind");
  const body = await request.json().catch(() => null);
  if (!body || typeof body !== "object") {
    return NextResponse.json({ error: { code: "validation_error", message: "请求数据无效" } }, { status: 400 });
  }

  try {
    if (kind === "reset-password") {
      const userId = url.searchParams.get("user_id") ?? "";
      const newPassword = typeof body.new_password === "string" ? body.new_password : "";
      if (!uuid.test(userId)) {
        return NextResponse.json({ error: { code: "validation_error", message: "用户 ID 无效" } }, { status: 400 });
      }
      if (newPassword.length < 8 || newPassword.length > 128) {
        return NextResponse.json({ error: { code: "validation_error", message: "新密码长度需在 8–128 位之间" } }, { status: 400 });
      }
      return NextResponse.json(
        await backendRequest(`/api/v1/system/users/${userId}/reset-password`, token, {
          method: "POST",
          body: JSON.stringify({ new_password: newPassword }),
        }),
      );
    }
    if (kind === "throttle-reset") {
      const username = typeof body.username === "string" ? body.username.trim() : "";
      if (!username) {
        return NextResponse.json({ error: { code: "validation_error", message: "请输入要解除的账号" } }, { status: 400 });
      }
      return NextResponse.json(
        await backendRequest("/api/v1/system/login-throttle/reset", token, {
          method: "POST",
          body: JSON.stringify({
            username,
            client_ip: typeof body.client_ip === "string" && body.client_ip.trim() ? body.client_ip.trim() : null,
          }),
        }),
      );
    }
    return NextResponse.json({ error: { code: "unknown_kind", message: "不支持的系统操作" } }, { status: 400 });
  } catch (error) {
    return failure(error);
  }
}
