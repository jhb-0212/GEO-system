import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

/**
 * BFF 写接口的同源校验（CSRF 的第二道闸）。
 *
 * 会话 cookie 是 SameSite=Lax，已经挡住大部分跨站提交；这里再加一道「来源 host
 * 必须等于目标 host」的判定，避免 Lax 在特定浏览器/老版本上的行为差异被利用。
 *
 * 只校验写方法：GET 不改状态，且跨站 GET 常见于预取，不需要拦。
 * 无 Origin 也无 Referer 的写请求（脚本、curl）一律拒绝——BFF 只服务浏览器页面。
 */
const WRITE_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);

function hostOf(value: string | null): string | null {
  if (!value) return null;
  try {
    const url = new URL(value.includes("://") ? value : `http://${value}`);
    return url.hostname.toLowerCase();
  } catch {
    return null;
  }
}

function isLoopback(name: string): boolean {
  return name === "localhost" || name === "127.0.0.1" || name === "::1" || name === "[::1]";
}

export function middleware(request: NextRequest) {
  if (!WRITE_METHODS.has(request.method)) return NextResponse.next();

  const target = hostOf(request.headers.get("x-forwarded-host") ?? request.headers.get("host"));
  const origin = hostOf(request.headers.get("origin"));
  const referer = hostOf(request.headers.get("referer"));
  const source = origin ?? referer;

  if (target && source) {
    if (source === target) return NextResponse.next();
    // 本地开发允许 localhost 与 127.0.0.1 互认，生产不做这个放宽。
    if (process.env.NODE_ENV !== "production" && isLoopback(source) && isLoopback(target)) {
      return NextResponse.next();
    }
  }

  return NextResponse.json(
    {
      error: {
        code: "origin_mismatch",
        message: "写请求来源校验未通过：请从工作台页面发起，不允许跨站提交",
      },
    },
    { status: 403 },
  );
}

export const config = { matcher: ["/internal/:path*"] };
