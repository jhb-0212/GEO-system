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
    await page.getByRole("tab", { name: /发布结果/ }).click();
    await expect(page.getByRole("heading", { name: "发布结果" })).toBeVisible();
    await expect(page.getByRole("main")).toContainText("每一条对应一次真实发布");
  });

  test("运营编辑可打开批量分发并看到账号清单", async ({ page }) => {
    const projectId = await loginAs(page, ACCOUNTS.editor);
    await openSection(page, "publishing", projectId);
    await page.getByRole("tab", { name: /新建发布/ }).click();
    await expect(page.getByRole("heading", { name: "新建发布" })).toBeVisible();
    await page.getByLabel("要发布的稿子").selectOption({ index: 1 });
    await expect(page.getByLabel("用哪个账号发布")).toBeVisible();
    await expect(page.getByLabel("用哪个账号发布").locator("option")).not.toHaveCount(1);
  });
});
