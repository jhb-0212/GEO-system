import { expect, test } from "@playwright/test";

import { ACCOUNTS, loginAs, openSection } from "./helpers";

/**
 * 新增能力只读冒烟：不落库，只验证运营编辑能看到手测录入与内容关联入口。
 * 写入闭环由后端 pytest 覆盖，避免 E2E 污染 dev 库。
 */
test.describe("手测与内容关联入口（真实接口）", () => {
  test("运营编辑可见手测录入与内容版本关联编辑", async ({ page }) => {
    const projectId = await loginAs(page, ACCOUNTS.editor);
    const main = page.getByRole("main");

    await openSection(page, "samples", projectId);
    await expect(main).toContainText("样本回看");
    await page.getByRole("button", { name: "新增手测样本" }).click();
    await expect(page.getByLabel("监测任务")).toBeVisible();
    await expect(page.getByLabel("原始回答")).toBeVisible();
    await expect(page.getByLabel("答案口径")).toBeVisible();

    await openSection(page, "reviews", projectId);
    await page.locator(".knowledge-list-panel select").selectOption("approved");
    await expect(page.locator(".knowledge-list-panel .knowledge-item").first()).toBeVisible();
    await page.locator(".knowledge-list-panel .knowledge-item").first().click();
    await expect(page.getByRole("button", { name: "调整关联内容" })).toBeVisible();
    await expect(page.getByRole("button", { name: "标记待发布" })).toBeVisible();

    await page.getByRole("button", { name: "调整关联内容" }).click();
    await expect(page.getByText("题目关联（已启用题目）")).toBeVisible();
    await expect(page.getByText("权威事实关联")).toBeVisible();
  });
});
