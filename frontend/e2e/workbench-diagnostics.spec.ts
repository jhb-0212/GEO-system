import { expect, test } from "@playwright/test";

import { ACCOUNTS, loginAs, openSection } from "./helpers";

test("官网诊断提供批量检查与 L2/L3 导入入口", async ({ page }) => {
  const projectId = await loginAs(page, ACCOUNTS.editor);
  const main = page.getByRole("main");
  await openSection(page, "site-diagnostics", projectId);
  await expect(main).toContainText("官网页面检查");
  await expect(page.getByRole("button", { name: "检查全部" })).toBeVisible();
  await expect(main).toContainText("L2/L3 日志导入");
  await expect(main).toContainText("L2 必填 page_url、occurred_at");
  await expect(main).toContainText("docs/site-diagnostics-import.md");
});

test("L2 导入前端把 JSON 事件发到 BFF", async ({ page }) => {
  const projectId = await loginAs(page, ACCOUNTS.editor);
  let received = 0;
  await page.route("**/internal/workbench/data?kind=crawler-events-import*", async (route) => {
    const body = JSON.parse(route.request().postData() ?? "{}");
    received = body.events?.length ?? 0;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ data: { imported: received, matched_pages: 0 } }),
    });
  });
  await openSection(page, "site-diagnostics", projectId);
  const textarea = page.getByRole("main").locator("textarea");
  await textarea.fill('[{"page_url":"https://example.com/a","occurred_at":"2026-11-19T08:00:00+08:00"}]');
  await page.getByRole("button", { name: "导入事件" }).click();
  await expect.poll(() => received).toBe(1);
  await expect(textarea).toHaveValue("");
});

test("检查全部按页分批调用 BFF", async ({ page }) => {
  const projectId = await loginAs(page, ACCOUNTS.editor);
  const pages = [
    {
      id: "page-1", title: "页面一", url: "https://example.com/a", page_type: "product",
      publish_status: "published", http_status: null, robots_allowed: null, in_sitemap: null,
      canonical_ok: null, js_dependent: null, checked_at: null, check_error: null,
    },
    {
      id: "page-2", title: "页面二", url: "https://example.com/b", page_type: "faq",
      publish_status: "published", http_status: null, robots_allowed: null, in_sitemap: null,
      canonical_ok: null, js_dependent: null, checked_at: null, check_error: null,
    },
  ];
  const summary = {
    pages_total: 2, pages_checked: 0, robots_blocked: 0, not_in_sitemap: 0, canonical_bad: 0,
    http_error: 0, js_dependent: 0, crawler_events: 0, verified_bot_events: 0, crawled_pages: 0,
    traffic_events: 0, bot_traffic_events: 0, visitor_sessions: 0, leads_with_session: 0,
    buckets: {},
  };
  let batchCalls = 0;
  await page.route("**/internal/workbench/data?*", async (route) => {
    const kind = new URL(route.request().url()).searchParams.get("kind");
    if (kind === "pages") {
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ data: pages, meta: { page: 1, page_size: 100, total: 2 } }) });
    }
    if (kind === "site-diagnostics") {
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ data: summary }) });
    }
    if (kind === "pages-check-batch") {
      batchCalls += 1;
      const body = JSON.parse(route.request().postData() ?? "{}");
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ data: { checked: body.page_ids.length, errors: 0, items: body.page_ids.map((id: string) => ({
          id, url: "https://example.com/", canonical_url: null, robots_allowed: true,
          in_sitemap: true, canonical_ok: true, http_status: 200, js_dependent: false,
          checked_at: "2026-11-19T08:00:00+08:00", check_error: null,
        })) } }),
      });
    }
    return route.continue();
  });
  await openSection(page, "site-diagnostics", projectId);
  await page.getByRole("button", { name: "检查全部" }).click();
  await expect.poll(() => batchCalls, { timeout: 20000 }).toBe(1);
  await expect(page.getByRole("button", { name: "重新检查全部" })).toBeVisible();
});
