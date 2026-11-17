import { expect, type Page } from "@playwright/test";

/** 账号与口令取自 docs/DEV_ENV.md 的本地开发种子（非生产凭据）。 */
export const ACCOUNTS = {
  admin: { username: process.env.E2E_USER_ADMIN ?? "geo_admin", password: process.env.E2E_PASS_ADMIN ?? "geo-admin-dev" },
  editor: { username: process.env.E2E_USER_EDITOR ?? "geo_editor", password: process.env.E2E_PASS_USER ?? "geo-user-dev" },
  reviewer: { username: process.env.E2E_USER_REVIEWER ?? "geo_reviewer", password: process.env.E2E_PASS_USER ?? "geo-user-dev" },
  viewer: { username: process.env.E2E_USER_VIEWER ?? "geo_viewer", password: process.env.E2E_PASS_USER ?? "geo-user-dev" },
} as const;

/** 登录并返回当前项目 id（工作台会按会话自动带出项目）。 */
export async function loginAs(page: Page, account: { username: string; password: string }): Promise<string> {
  await page.goto("/login");
  await page.locator('input[placeholder="请输入工作账号"]').fill(account.username);
  await page.locator('input[placeholder="请输入密码"]').fill(account.password);
  await page.getByRole("button", { name: "进入工作台" }).click();
  await page.waitForURL(/\/workbench/);
  // 项目 id 由前端在拿到项目列表后补进 URL，需等它落定
  await page
    .waitForFunction(() => new URL(location.href).searchParams.has("project_id"), null, { timeout: 20_000 })
    .catch(() => undefined);
  let projectId = new URL(page.url()).searchParams.get("project_id");
  if (!projectId && process.env.E2E_PROJECT_ID) projectId = process.env.E2E_PROJECT_ID;
  expect(projectId, `登录后未带出项目 id（当前地址：${page.url()})`).toBeTruthy();
  return projectId as string;
}

/** 直接进入某个 section，避免依赖可滚动导航。 */
export async function openSection(page: Page, section: string, projectId: string) {
  await page.goto(`/workbench?section=${section}&project_id=${projectId}`);
  await page.waitForSelector("main");
  await page.waitForLoadState("networkidle").catch(() => {
    /* 轮询类页面可能不到 idle，忽略即可 */
  });
}
