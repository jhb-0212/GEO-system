"""DeepSeek 网页版联网搜索采集桥。

为什么需要桥：
- DeepSeek 官方 API 没有联网搜索能力（`supports_search=false`），要拿 DeepSeek 自己的
  检索行为与引用来源，只能走 chat.deepseek.com 的「智能搜索」；
- 后端 API / Celery Worker 不适合直接跑浏览器，所以把浏览器自动化隔离在这个独立进程里，
  用 HTTP 暴露 `/health` 与 `/collect`，后端适配器
  （`app/services/deepseek_websearch_adapter.py`）只走 httpx 调用。

用法（在 backend 目录、用项目 venv）：
    # 1) 首次：人工登录一次，登录态写进持久化 profile
    ./.venv/Scripts/python.exe scripts/deepseek_websearch_bridge.py login --channel msedge
    # 2) 起服务（默认 headless、127.0.0.1:8099）
    ./.venv/Scripts/python.exe scripts/deepseek_websearch_bridge.py serve --channel msedge

约束：
- 同一份 profile 同时只能被一个进程占用；跑 serve 前先退出 login 模式。
- 不读取、不导出 cookie；登录只由人在可见浏览器里完成。
- 不做并发：单浏览器 + 全局锁 + 最小间隔，避免触发平台风控；宁可排队也不批量轰。
- 未登录返回 409 + error=login_required，采集侧据此落 `login_blocked`，不伪造回答。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

BASE_URL = "https://chat.deepseek.com/"
BACKEND_DIR = Path(__file__).resolve().parents[1]
DEFAULT_PROFILE = BACKEND_DIR / "var" / "browser" / "deepseek-profile"
TOKEN_ENV = "DEEPSEEK_WEBSEARCH_TOKEN"
MIN_ANSWER_CHARS = 40
_ELAPSED_RE = re.compile(r"搜索到\s*(\d+)\s*个网页")


class LoginRequired(Exception):
    """网页端停在登录页，需要人工登录。"""


class CollectTimeout(Exception):
    """等待回答超时。"""


class BrowserCollector:
    """持久化 profile 的浏览器采集器；一次只处理一个请求。"""

    def __init__(
        self,
        *,
        channel: str = "msedge",
        profile_dir: Path = DEFAULT_PROFILE,
        headless: bool = True,
        min_interval_seconds: float = 15.0,
    ) -> None:
        self.channel = channel
        self.profile_dir = profile_dir
        self.headless = headless
        self.min_interval = min_interval_seconds
        self._lock = threading.Lock()
        self._pw = None
        self._context = None
        self._last_collect_at = 0.0
        self._last_state: dict[str, Any] = {}

    # ---------- 浏览器生命周期 ----------
    def _ensure_context(self):
        if self._context is not None:
            return self._context
        from playwright.sync_api import sync_playwright

        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self._pw = sync_playwright().start()
        self._context = self._pw.chromium.launch_persistent_context(
            str(self.profile_dir),
            channel=self.channel,
            headless=self.headless,
            viewport={"width": 1280, "height": 900},
            locale="zh-CN",
        )
        return self._context

    def _page(self):
        context = self._ensure_context()
        page = context.pages[0] if context.pages else context.new_page()
        return page

    def close(self) -> None:
        try:
            if self._context is not None:
                self._context.close()
        finally:
            self._context = None
        try:
            if self._pw is not None:
                self._pw.stop()
        finally:
            self._pw = None

    # ---------- 登录与开关 ----------
    def _is_login_page(self, page) -> bool:
        return "/sign_in" in (page.url or "")

    def _ensure_smart_search(self, page) -> bool:
        """确保「智能搜索」是选中态；返回是否开启。"""
        for _ in range(3):
            state = page.evaluate(
                """(() => {
                  const hits = [...document.querySelectorAll('*')].filter(
                    e => e.children.length === 0 && e.textContent.trim() === '智能搜索'
                  );
                  const btn = hits.length ? hits[0].parentElement : null;
                  if (!btn) return 'missing';
                  return btn.className.includes('ds-toggle-button--selected') ? 'on' : 'off';
                })()"""
            )
            if state == "on":
                return True
            if state == "off":
                page.evaluate(
                    """(() => {
                      const hits = [...document.querySelectorAll('*')].filter(
                        e => e.children.length === 0 && e.textContent.trim() === '智能搜索'
                      );
                      const btn = hits.length ? hits[0].parentElement : null;
                      if (btn) btn.click();
                    })()"""
                )
                time.sleep(0.6)
                continue
            return False
        return False

    def _wait_for_login(self, page, timeout_seconds: float) -> None:
        """阻塞等人工登录（仅 login 模式用）。"""
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            if not self._is_login_page(page) and page.query_selector("textarea"):
                return
            time.sleep(2)
        raise LoginRequired("等待登录超时")

    def login(self, timeout_seconds: float = 300.0) -> dict[str, Any]:
        with self._lock:
            page = self._page()
            page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30_000)
            print("请在弹出的浏览器里完成 DeepSeek 登录（扫码/验证码/密码均可）……", flush=True)
            self._wait_for_login(page, timeout_seconds)
            print(f"登录成功，profile 已保存在 {self.profile_dir}", flush=True)
            return {"logged_in": True, "profile": str(self.profile_dir), "channel": self.channel}

    # ---------- 采集 ----------
    def _throttle(self) -> None:
        gap = time.time() - self._last_collect_at
        if self._last_collect_at and gap < self.min_interval:
            time.sleep(self.min_interval - gap)

    def _wait_answer(self, page, timeout_seconds: float) -> str:
        deadline = time.time() + timeout_seconds
        last = ""
        stable = 0
        while time.time() < deadline:
            time.sleep(2.5)
            try:
                current = page.evaluate(
                    """(() => {
                      const blocks = [...document.querySelectorAll('.ds-markdown')]
                        .map(x => x.innerText)
                        .sort((a, b) => b.length - a.length);
                      return blocks[0] || '';
                    })()"""
                )
            except Exception:
                current = ""
            if current and current == last and len(current) > MIN_ANSWER_CHARS:
                stable += 1
                if stable >= 2:
                    return current
            else:
                stable = 0
            if current:
                last = current
        raise CollectTimeout(f"等待回答超过 {int(timeout_seconds)} 秒")

    def _citations(self, page) -> list[dict[str, str]]:
        links = page.evaluate(
            """(() => {
              const seen = new Set(), out = [];
              document.querySelectorAll('a[href^="http"]').forEach(a => {
                const href = a.href;
                if (!href.includes('deepseek.com') && !seen.has(href)) {
                  seen.add(href);
                  out.push({url: href, title: (a.textContent || '').trim().slice(0, 120)});
                }
              });
              return out;
            })()"""
        )
        return [item for item in links if isinstance(item, dict) and item.get("url")]

    def collect(self, question: str, timeout_seconds: float = 120.0) -> dict[str, Any]:
        question = (question or "").strip()
        if not question:
            raise ValueError("question 不能为空")
        with self._lock:
            self._throttle()
            started = time.time()
            page = self._page()
            page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30_000)
            time.sleep(1.5)
            if self._is_login_page(page):
                self._last_state = {"logged_in": False, "checked_at": _now_iso()}
                raise LoginRequired("DeepSeek 网页版未登录")
            search_on = self._ensure_smart_search(page)

            textarea = page.wait_for_selector("textarea", timeout=20_000)
            textarea.click()
            textarea.fill(question)
            textarea.press("Enter")

            answer = self._wait_answer(page, timeout_seconds)
            citations = self._citations(page)
            page_text = page.inner_text("body")[:4000]
            match = _ELAPSED_RE.search(page_text)
            self._last_collect_at = time.time()
            self._last_state = {"logged_in": True, "checked_at": _now_iso()}
            return {
                "logged_in": True,
                "model_name": "deepseek-websearch",
                "answer": answer,
                "citations": citations,
                "searched_page_count": int(match.group(1)) if match else None,
                "smart_search_on": search_on,
                "session_url": page.url,
                "elapsed_ms": int((time.time() - started) * 1000),
            }

    def health(self, probe_login: bool = True) -> dict[str, Any]:
        base = {
            "ok": True,
            "profile": str(self.profile_dir),
            "browser_channel": self.channel,
            "browser_started": self._context is not None,
            "last_collect": self._last_state,
        }
        if not probe_login:
            base["logged_in"] = None
            return base
        try:
            page = self._page()
            page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30_000)
            time.sleep(1.0)
            base["logged_in"] = not self._is_login_page(page)
        except Exception as exc:  # 健康检查不抛 500，返回可诊断信息
            base["ok"] = False
            base["logged_in"] = False
            base["message"] = f"浏览器探测失败: {exc}"
        return base


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class BridgeHandler(BaseHTTPRequestHandler):
    collector: BrowserCollector
    token: str = ""

    server_version = "GeoDeepseekBridge/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:  # 简化访问日志
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _send(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        if not self.token:
            return True
        header = self.headers.get("Authorization", "")
        return header == f"Bearer {self.token}"

    def do_GET(self) -> None:
        if self.path.split("?")[0] != "/health":
            self._send(404, {"error": "not_found"})
            return
        if not self._authorized():
            self._send(401, {"error": "unauthorized"})
            return
        try:
            self._send(200, self.collector.health())
        except Exception as exc:
            self._send(500, {"ok": False, "error": "health_failed", "message": str(exc)})

    def do_POST(self) -> None:
        if self.path.split("?")[0] != "/collect":
            self._send(404, {"error": "not_found"})
            return
        if not self._authorized():
            self._send(401, {"error": "unauthorized"})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        except (ValueError, UnicodeDecodeError):
            self._send(400, {"error": "bad_request", "message": "请求体不是合法 JSON"})
            return
        question = str(payload.get("question") or "").strip()
        timeout_seconds = float(payload.get("timeout_seconds") or 120)
        try:
            self._send(200, self.collector.collect(question, timeout_seconds))
        except ValueError as exc:
            self._send(400, {"error": "bad_request", "message": str(exc)})
        except LoginRequired as exc:
            self._send(409, {"error": "login_required", "logged_in": False, "message": str(exc)})
        except CollectTimeout as exc:
            self._send(504, {"error": "timeout", "message": str(exc)})
        except Exception as exc:
            self._send(500, {"error": "collect_failed", "message": str(exc)})


def build_server(
    *,
    host: str,
    port: int,
    collector: BrowserCollector,
    token: str,
) -> ThreadingHTTPServer:
    handler = type("BoundBridgeHandler", (BridgeHandler,), {"collector": collector, "token": token})
    return ThreadingHTTPServer((host, port), handler)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="DeepSeek 网页版联网搜索采集桥")
    parser.add_argument("mode", choices=["serve", "login"], help="serve=起 HTTP 服务，login=人工登录一次")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8099)
    parser.add_argument("--channel", default="msedge", help="msedge / chrome / chromium")
    parser.add_argument("--profile", default=str(DEFAULT_PROFILE))
    parser.add_argument("--headed", action="store_true", help="serve 模式用可见浏览器（排障用）")
    parser.add_argument("--min-interval", type=float, default=15.0, help="两次采集最小间隔（秒）")
    parser.add_argument("--login-timeout", type=float, default=300.0)
    args = parser.parse_args(argv)

    collector = BrowserCollector(
        channel=args.channel,
        profile_dir=Path(args.profile),
        headless=not args.headed,
        min_interval_seconds=args.min_interval,
    )
    token = os.getenv(TOKEN_ENV, "").strip()

    if args.mode == "login":
        try:
            result = collector.login(args.login_timeout)
            print(json.dumps(result, ensure_ascii=False))
            return 0
        finally:
            collector.close()

    server = build_server(host=args.host, port=args.port, collector=collector, token=token)
    print(
        f"采集桥已启动 http://{args.host}:{args.port}（channel={args.channel}, "
        f"profile={args.profile}, token={'on' if token else 'off'}）",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("收到中断，关闭采集桥", flush=True)
    finally:
        server.server_close()
        collector.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
