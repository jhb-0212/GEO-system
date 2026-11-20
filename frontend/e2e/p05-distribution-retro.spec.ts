import { expect, test } from "@playwright/test";

import { ACCOUNTS, loginAs, openSection } from "./helpers";

test.describe("P05 分发与复盘", () => {
  test("月报快照入口与分发看板可打开", async ({ page }) => {
    const projectId = await loginAs(page, ACCOUNTS.admin);

    await openSection(page, "monthly", projectId);
    await expect(page.locator("h3").filter({ hasText: "月度报告" })).toBeVisible();
    await expect(page.locator("h3").filter({ hasText: "历史快照" })).toBeVisible();
    await expect(page.getByRole("main")).toContainText("报告月份");

    await openSection(page, "publishing", projectId);
    await page.getByRole("tab", { name: /分发看板/ }).click();
    await expect(page.getByRole("heading", { name: "分发看板" })).toBeVisible();
    await expect(page.getByText("已审批渠道稿", { exact: true })).toBeVisible();
  });

  test("运营编辑可打开批量分发并看到账号清单", async ({ page }) => {
    const projectId = await loginAs(page, ACCOUNTS.editor);
    await openSection(page, "publishing", projectId);
    await page.getByRole("tab", { name: /新建任务/ }).click();
    await expect(page.getByRole("heading", { name: "新建分发任务" })).toBeVisible();
    await page.locator("select").filter({ hasText: "选择版本" }).selectOption({ index: 1 });
    await expect(page.getByText("发布账号（可多选）")).toBeVisible();
    await expect(page.locator(".publish-account-check").first()).toBeVisible();
  });
});
