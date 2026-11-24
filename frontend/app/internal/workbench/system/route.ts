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
 * 系统管理员动作：账号目录、建号、启停、重置他人密码、解除登录限流。
 *
 * 权限由后端 `is_system_admin` 判定，这里只做参数校验与转发，
 * 避免把「谁能建号/停用」的规则复制到前端。
 */
export async function GET(request: Request) {
  const token = await getSessionToken();
  if (!token) {
    return NextResponse.json({ error: { code: "unauthorized", message: "请先登录" } }, { status: 401 });
  }
  if (isMockMode()) {
    return NextResponse.json({ error: { code: "mock_only", message: "演示模式不调用真实接口" } }, { status: 400 });
  }
  const url = new URL(request.url);
  if (url.searchParams.get("kind") !== "users") {
    return NextResponse.json({ error: { code: "unknown_kind", message: "不支持的系统查询" } }, { status: 400 });
  }
  const q = (url.searchParams.get("q") ?? "").trim();
  const page = Math.max(1, Number(url.searchParams.get("page") ?? "1") || 1);
  const pageSize = Math.min(100, Math.max(1, Number(url.searchParams.get("page_size") ?? "20") || 20));
  try {
    return NextResponse.json(
      await backendRequest(
        `/api/v1/system/users?q=${encodeURIComponent(q)}&page=${page}&page_size=${pageSize}`,
        token,
      ),
    );
  } catch (error) {
    return failure(error);
  }
}

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
    if (kind === "user-create") {
      const username = typeof body.username === "string" ? body.username.trim() : "";
      const displayName = typeof body.display_name === "string" ? body.display_name.trim() : "";
      const email = typeof body.email === "string" ? body.email.trim() : "";
      const password = typeof body.password === "string" ? body.password : "";
      if (!/^[A-Za-z0-9_.-]{1,64}$/.test(username)) {
        return NextResponse.json({ error: { code: "validation_error", message: "账号只能用字母、数字、下划线、点或短横线" } }, { status: 400 });
      }
      if (!displayName || displayName.length > 64) {
        return NextResponse.json({ error: { code: "validation_error", message: "显示名不能为空且不超过 64 字" } }, { status: 400 });
      }
      if (password.length < 8 || password.length > 128) {
        return NextResponse.json({ error: { code: "validation_error", message: "密码长度需在 8–128 位之间" } }, { status: 400 });
      }
      return NextResponse.json(
        await backendRequest("/api/v1/system/users", token, {
          method: "POST",
          body: JSON.stringify({ username, display_name: displayName, email: email || null, password }),
        }),
      );
    }
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

export async function PATCH(request: Request) {
  const token = await getSessionToken();
  if (!token) {
    return NextResponse.json({ error: { code: "unauthorized", message: "请先登录" } }, { status: 401 });
  }
  if (isMockMode()) {
    return NextResponse.json({ error: { code: "mock_only", message: "演示模式不调用真实接口" } }, { status: 400 });
  }
  const url = new URL(request.url);
  const userId = url.searchParams.get("user_id") ?? "";
  if (url.searchParams.get("kind") !== "user-update" || !uuid.test(userId)) {
    return NextResponse.json({ error: { code: "validation_error", message: "账号更新参数无效" } }, { status: 400 });
  }
  const body = await request.json().catch(() => null);
  if (!body || typeof body !== "object") {
    return NextResponse.json({ error: { code: "validation_error", message: "请求数据无效" } }, { status: 400 });
  }
  const patch: Record<string, unknown> = {};
  if (typeof body.display_name === "string" && body.display_name.trim()) patch.display_name = body.display_name.trim();
  if (typeof body.email === "string") patch.email = body.email.trim() || null;
  if (typeof body.is_active === "boolean") patch.is_active = body.is_active;
  if (!Object.keys(patch).length) {
    return NextResponse.json({ error: { code: "validation_error", message: "没有需要更新的字段" } }, { status: 400 });
  }
  try {
    return NextResponse.json(
      await backendRequest(`/api/v1/system/users/${userId}`, token, {
        method: "PATCH",
        body: JSON.stringify(patch),
      }),
    );
  } catch (error) {
    return failure(error);
  }
}
