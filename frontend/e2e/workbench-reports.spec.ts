import { expect, test } from "@playwright/test";

import { ACCOUNTS, loginAs, openSection } from "./helpers";

/**
 * 月报、线索漏斗、统计轮次与渠道导出的只读冒烟。
 * 渠道导出只下载 CSV，不改库；月报/漏斗均为只读接口。
 */
test.describe("运营看板新增能力（真实接口）", () => {
  test("管理员可见月报、漏斗、轮次差值与渠道 CSV 导出", async ({ page }) => {
    const projectId = await loginAs(page, ACCOUNTS.admin);
    const main = page.getByRole("main");

    await openSection(page, "monthly", projectId);
    await expect(main).toContainText("月度报告");
    await expect(main).toContainText("本月任务");
    await expect(main).toContainText("发布结案");
    await expect(main.locator(".form-error")).toHaveCount(0);

    const monthlyDownload = page.waitForEvent("download");
    await page.getByRole("button", { name: "导出月报" }).click();
    const monthlyFile = await monthlyDownload;
    expect(monthlyFile.suggestedFilename()).toMatch(/^geo-monthly-report-\d{4}-\d{2}\.md$/);

    await openSection(page, "funnel", projectId);
    await expect(main).toContainText("线索漏斗");
    await expect(main).toContainText("咨询总量");
    await expect(main.locator("table").first()).toContainText("地区");
    await expect(main).toContainText("按来源");
    await expect(main).toContainText("按渠道");
    await expect(main.locator(".form-error")).toHaveCount(0);

    await openSection(page, "statistics", projectId);
    const roundSelect = page.getByLabel("监测轮次");
    await expect(roundSelect).toBeVisible();
    const options = roundSelect.locator("option");
    let nonBaseline = "";
    for (let index = 0; index < await options.count(); index += 1) {
      const option = options.nth(index);
      const label = (await option.textContent()) ?? "";
      const value = (await option.getAttribute("value")) ?? "";
      if (value && value !== "all" && !label.includes("（基线）")) nonBaseline = value;
    }
    expect(nonBaseline).toBeTruthy();
    await roundSelect.selectOption(nonBaseline);
    // 分栏模式两个分母不合并，差值只有在单一答案口径下才有可比基线。
    await page.getByLabel("答案口径").selectOption("answer");
    await expect(main).toContainText("较基线");

    await openSection(page, "channels", projectId);
    await expect(main).toContainText("渠道台账");
    const downloadPromise = page.waitForEvent("download");
    await page.getByRole("button", { name: "导出表格" }).click();
    const download = await downloadPromise;
    expect(download.suggestedFilename()).toMatch(/^channels(?:-[a-z0-9-]+)?-\d+\.csv$/);
  });

  test("编辑账号无线索权限仍可导出月报", async ({ page }) => {
    const projectId = await loginAs(page, ACCOUNTS.editor);
    const main = page.getByRole("main");

    await openSection(page, "monthly", projectId);
    await expect(main).toContainText("月度报告");
    await expect(main).toContainText("当前月报没有线索段");
    await expect(main.locator(".form-error")).toHaveCount(0);

    const monthlyDownload = page.waitForEvent("download");
    await page.getByRole("button", { name: "导出月报" }).click();
    const monthlyFile = await monthlyDownload;
    expect(monthlyFile.suggestedFilename()).toMatch(/^geo-monthly-report-\d{4}-\d{2}\.md$/);
  });
});
