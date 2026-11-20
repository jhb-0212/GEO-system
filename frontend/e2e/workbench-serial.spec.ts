import { expect, test } from "@playwright/test";

import { ACCOUNTS, loginAs, openSection } from "./helpers";

test.describe("业务编号持久化（真实后端）", () => {
  test("发布列表主标识使用数据库 serial_no，不回退 UUID 片段", async ({ page }) => {
    const projectId = await loginAs(page, ACCOUNTS.admin);
    await openSection(page, "publishing", projectId);

    const main = page.getByRole("main");
    const firstTitle = main.locator(".knowledge-item strong").first();
    await expect(firstTitle).toBeVisible();
    await expect(firstTitle).toHaveText(/^发布任务 #\d{3,}$/);
  });

  test("监测任务列表使用数据库 serial_no", async ({ page }) => {
    const projectId = await loginAs(page, ACCOUNTS.admin);
    await openSection(page, "monitoring", projectId);

    const main = page.getByRole("main");
    await expect(main.getByText(/任务 #\d{3,}/).first()).toBeVisible();
  });
});
