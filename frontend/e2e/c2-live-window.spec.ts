import { expect, test, type Page } from "@playwright/test";
import fs from "node:fs";

/**
 * C2-4 真实链路验收（真实后端 + 真实 PostgreSQL + 真实前端）。
 *
 * 与 mock-tz-invariance 的分工：
 * - mock：只证明"浏览器时区不参与切窗"，窗口是写死的样本；
 * - 本用例：证明"数据库过滤 → API window/counts → 前端展示"整条链路一致，
 *   并在三个浏览器时区下重复同一项目，要求 DOM 完全不变。
 *
 * 前置（脚本见 backend/scripts/c2_live_fixture.py）：
 *   GEO_C2_LIVE=1
 *   C2_LIVE_FIXTURE=<fixture JSON 路径>
 *   C2_LIVE_API=http://127.0.0.1:8000       （后端直连地址，用于读 API 事实）
 *   E2E_BASE_URL=http://127.0.0.1:3220      （真实前端，非 mock）
 *
 * 夹具为每个项目在"今天窗口"的四条边界写入事实：
 *   start-1s（外）、start（内）、end-1s（内）、end（外）→ today=2、all=4。
 */

const FIXTURE_PATH = process.env.C2_LIVE_FIXTURE ?? "";
const API_BASE = process.env.C2_LIVE_API ?? "http://127.0.0.1:8000";
const ZONES = ["Asia/Shanghai", "America/New_York", "Europe/Berlin"] as const;

type FixtureProject = {
  timezone: string;
  project_id: string;
  username: string;
  password: string;
  window: { start: string; end: string };
  expected: { today: number; week: number; all: number };
};

test.describe("C2-4 真实链路", () => {
  test.skip(!process.env.GEO_C2_LIVE, "未开启 GEO_C2_LIVE=1，跳过真实链路验收");
  test.skip(!FIXTURE_PATH, "缺少 C2_LIVE_FIXTURE");

  const fixture = FIXTURE_PATH ? JSON.parse(fs.readFileSync(FIXTURE_PATH, "utf8")) : { projects: [] };
  const projects = fixture.projects as FixtureProject[];

  test("夹具就绪且覆盖三个时区", () => {
    expect(projects.map((project) => project.timezone).sort()).toEqual([...ZONES].sort());
  });

  for (const project of [...projects]) {
    test(`${project.timezone}：API 窗口与前端计数一致，且浏览器时区不影响`, async ({ browser, baseURL }) => {
      test.setTimeout(300_000);
      const snapshots: Array<{ zone: string; range: string[]; summary: string[]; rows: string[] }> = [];
      let apiCounts: { today: number; week: number; all: number } | null = null;

      for (const zone of ZONES) {
        const context = await browser.newContext({ baseURL, timezoneId: zone, locale: "zh-CN" });
        const page = await context.newPage();

        await page.goto("/login");
        await page.locator("#username").fill(project.username);
        await page.locator("#password").fill(project.password);
        await page.getByRole("button", { name: /进入工作台/ }).click();
        await expect(page).toHaveURL(/\/workbench/);

        // 会话 cookie 里存的就是后端 token，直接用它读 API 事实，不经过前端渲染
        const token = (await context.cookies()).find((item) => item.name === "geo_workbench_session")?.value;
        expect(token, "登录后应拿到后端会话 token").toBeTruthy();

        if (!apiCounts) {
          const payloads = await Promise.all(
            (["today", "week", "all"] as const).map(async (range) => {
              const response = await context.request.get(
                `${API_BASE}/api/v1/projects/${project.project_id}/workbench/todos?range=${range}`,
                { headers: { Authorization: `Bearer ${token}` } },
              );
              expect(response.status(), `API range=${range} 应返回 200`).toBe(200);
              return (await response.json()).data;
            }),
          );

          const [today, week, all] = payloads;
          expect(today.business_timezone).toBe(project.timezone);
          test.skip(
            today.window.start !== project.window.start,
            `窗口已跨日（API ${today.window.start} ≠ 夹具 ${project.window.start}），请重跑 fixture`,
          );
          expect(today.window).toEqual(project.window);
          expect(today.generated_at).toBeTruthy();
          expect(all.window, "range=all 不应返回窗口").toBeNull();
          apiCounts = { today: today.counts.today, week: week.counts.week, all: all.counts.all };
          expect(apiCounts).toEqual(project.expected);
        }

        // 待办只在快照拿到项目后异步拉取：先挂好响应等待，再进页面，避免读到 loading 中的 0
        const todosResponse = page
          .waitForResponse((response) => response.url().includes("/workbench/todos") && response.status() === 200, { timeout: 30_000 })
          .catch(() => null);
        await page.goto(`/workbench?project_id=${project.project_id}&section=reviews`);
        await todosResponse;
        const snapshot = await readTodoCenter(page);
        snapshots.push({ zone, ...snapshot });
        await context.close();
      }

      expect(apiCounts, "必须已经读到 API 计数").not.toBeNull();
      const baseline = snapshots[0];
      expect(parseCount(baseline.range[0]), "今天计数应等于 API counts.today").toBe(apiCounts!.today);
      expect(parseCount(baseline.range[1]), "本周计数应等于 API counts.week").toBe(apiCounts!.week);
      expect(parseCount(baseline.range[2]), "全部计数应等于 API counts.all").toBe(apiCounts!.all);

      for (const other of snapshots.slice(1)) {
        expect(other.range, `${other.zone} 计数与上海不一致`).toEqual(baseline.range);
        expect(other.summary, `${other.zone} 汇总与上海不一致`).toEqual(baseline.summary);
        expect(other.rows, `${other.zone} 待办行与上海不一致`).toEqual(baseline.rows);
      }
    });
  }
});

function parseCount(text: string): number {
  return Number(text.replace(/[^\d]/g, ""));
}

async function readTodoCenter(page: Page) {
  await page.getByRole("button", { name: /待办/ }).first().click();
  await expect(page.getByText("待办中心")).toBeVisible();
  // 等聚合完成：loading 时汇总显示“…”且各范围计数尚未回填
  await expect(page.locator(".task-center-summary strong").first()).not.toHaveText("…");
  await expect(page.locator(".task-center-range button").first()).toContainText(/\d/);
  await page.locator(".task-center-range button").first().waitFor({ state: "visible" });
  await page.waitForTimeout(300);
  return {
    range: await page.locator(".task-center-range button").allInnerTexts(),
    summary: await page.locator(".task-center-summary strong").allInnerTexts(),
    rows: await page.locator(".task-center-row strong").allInnerTexts(),
  };
}
