import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

/**
 * BFF 写接口的同源校验（CSRF 的第二道闸）。
 *
 * 会话 cookie 是 SameSite=Lax，已经挡住大部分跨站提交；这里再加一道「来源必须等于目标」
 * 的判定，覆盖 Lax 在特定浏览器/老版本上的行为差异。
 *
 * 判定依据只用浏览器自动写入的 Host 与 Origin：
 * - 不读 X-Forwarded-Host：它由代理决定，让它优先于 Host 会引入一条可被外部请求头影响的
 *   判定链（带该头 + 同值 Origin 即可自洽通过）；
 * - 不回退 Referer：按 Fetch 规范写请求必带 Origin，缺 Origin 才回退只会放宽、不会更准；
 * - 比较 host:port，而不是单独的 hostname：忽略端口会把同机不同端口的服务当成同源。
 * 协议不参与比较：TLS 在 nginx 终止，BFF 拿不到可靠的外部 scheme（nginx 目前只转发 Host）。
 */
const WRITE_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);

/** 规范化成 host（含端口，小写）：`Origin` 是完整 URL，`Host` 头是裸 host。 */
function hostOf(value: string | null): string | null {
  if (!value) return null;
  try {
    const url = new URL(value.includes("://") ? value : `http://${value}`);
    return url.host.toLowerCase();
  } catch {
    return null;
  }
}

/** 取 host 里的主机名部分，兼容 `[::1]:3000` 这种 IPv6 写法。 */
function nameOf(host: string): string {
  if (host.startsWith("[")) {
    const end = host.indexOf("]");
    return end > 0 ? host.slice(0, end + 1) : host;
  }
  return host.split(":")[0];
}

function isLoopback(host: string): boolean {
  const name = nameOf(host);
  return name === "localhost" || name === "127.0.0.1" || name === "::1" || name === "[::1]";
}

export function middleware(request: NextRequest) {
  // 未登录访问工作台时，把原始路径（含 task_id / section 查询）带到登录页，
  // 登录成功后原样跳回，避免深链接退化成默认工作台。
  if (request.nextUrl.pathname.startsWith("/workbench") && !request.cookies.get("geo_workbench_session")) {
    const loginUrl = request.nextUrl.clone();
    loginUrl.pathname = "/login";
    loginUrl.search = "";
    loginUrl.searchParams.set("next", `${request.nextUrl.pathname}${request.nextUrl.search}`);
    return NextResponse.redirect(loginUrl);
  }

  if (!WRITE_METHODS.has(request.method)) return NextResponse.next();

  const target = hostOf(request.headers.get("host"));
  const source = hostOf(request.headers.get("origin"));

  if (target && source) {
    if (source === target) return NextResponse.next();
    // 本地开发允许 localhost 与 127.0.0.1 互认（端口仍需一致），生产不做这个放宽。
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

export const config = { matcher: ["/workbench/:path*", "/internal/:path*"] };
