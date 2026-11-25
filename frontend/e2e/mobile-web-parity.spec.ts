import { expect, test } from "@playwright/test";

import { ACCOUNTS, loginAs, openSection } from "./helpers";

test("手机端与网页端入口对照可验收", async ({ page }) => {
  const projectId = await loginAs(page, ACCOUNTS.editor);
  const main = page.getByRole("main");

  await openSection(page, "monitoring", projectId);
  await page.getByText("监测轮次与批量生成").click();
  await expect(main).toContainText("固定周期复测");
  await page.getByRole("button", { name: "新建计划" }).click();
  await expect(page.getByText("手机客户端（人工真实采样）")).toBeVisible();
  await expect(page.getByText("网页端入口（人工真实采样）")).toBeVisible();
  await page.screenshot({ path: "test-results/mobile-web-retest-scope.png" });

  await openSection(page, "statistics", projectId);
  await page.getByRole("tab", { name: /入口对照/ }).click();
  await expect(main).toContainText("同一引擎的网页端、手机客户端、官方 API、应用内搜索分别一行");
  await expect(main).toContainText("不把两端回答平均成单一结论");
  await page.screenshot({ path: "test-results/mobile-web-entry-tab.png", fullPage: true });

  await openSection(page, "samples", projectId);
  await page.getByRole("button", { name: "新增手测样本" }).click();
  await expect(main).toContainText("应用内、网页端或手机客户端入口的待处理任务也可直接录入");
});
