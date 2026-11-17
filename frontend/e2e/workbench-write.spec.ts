import { expect, test } from "@playwright/test";

import { ACCOUNTS, loginAs, openSection } from "./helpers";

/**
 * 写入链路回归：会真实落库，默认跳过。
 * 开启：`$env:E2E_WRITE="1"; pnpm exec playwright test e2e/workbench-write.spec.ts`
 * 清理（本机 dev 库）：
 *   delete from media_quotes where note like 'E2E-%';
 *   delete from content_plans where title like 'E2E-%';
 *   delete from metric_definitions where code like 'e2e_%';
 *   delete from competitors where name like 'E2E-%';
 */
const WRITE_ON = () => process.env.E2E_WRITE === "1";

test.describe("工作台写入链路（真实接口）", () => {
  test.skip(!WRITE_ON(), "写入用例默认跳过，避免污染 dev 库（置 E2E_WRITE=1 开启）");

  test("竞品新增 → 停用", async ({ page }) => {
    const suffix = Date.now().toString(36);
    const name = `E2E-竞品-${suffix}`;
    const projectId = await loginAs(page, ACCOUNTS.admin);
    const main = page.getByRole("main");

    await openSection(page, "competitors", projectId);
    await page.getByRole("button", { name: "新增竞品" }).click();
    await page.getByLabel("竞品名称").fill(name);
    await page.getByLabel("官网域名").fill(`e2e-${suffix}.example.com`);
    await page.getByRole("button", { name: "保存竞品" }).click();

    await expect(main).toContainText(name);
    await expect(main).toContainText("跟踪中");

    await main.locator(".knowledge-item").filter({ hasText: name }).getByRole("button", { name: "停用" }).click();
    await expect(main.locator(".knowledge-item").filter({ hasText: name })).toContainText("已停用");
  });

  test("指标口径新增版本 → 停用", async ({ page }) => {
    const suffix = Date.now().toString(36);
    const code = `e2e_metric_${suffix}`;
    const projectId = await loginAs(page, ACCOUNTS.admin);
    const main = page.getByRole("main");

    await openSection(page, "metrics", projectId);
    await page.getByRole("button", { name: "新增口径版本" }).click();
    await page.getByLabel("口径代码").fill(code);
    await page.getByLabel("口径名称").fill(`E2E 口径 ${suffix}`);
    await page.getByLabel("计算公式").fill("E2E 分子 / E2E 分母");
    await page.getByRole("button", { name: "创建版本" }).click();

    await expect(main).toContainText(code);
    await main.locator(".knowledge-item").filter({ hasText: code }).getByRole("button", { name: "停用" }).click();
    await expect(main.locator(".knowledge-item").filter({ hasText: code })).toContainText("→");
  });

  test("计划新增 → 状态推进 → 报价提交 → 审核通过", async ({ browser }) => {
    const suffix = Date.now().toString(36);
    const planTitle = `E2E-计划-${suffix}`;

    const editorContext = await browser.newContext();
    const editorPage = await editorContext.newPage();
    const projectId = await loginAs(editorPage, ACCOUNTS.editor);

    await openSection(editorPage, "plans", projectId);
    await editorPage.getByRole("button", { name: "新增计划" }).click();
    await editorPage.getByLabel("计划标题").fill(planTitle);
    await editorPage.getByRole("button", { name: "保存计划" }).click();
    await expect(editorPage.getByRole("main")).toContainText(planTitle);

    await editorPage.getByLabel("更新计划状态").selectOption("pending_review");

    await openSection(editorPage, "quotes", projectId);
    await editorPage.getByRole("button", { name: "新增报价" }).click();
    await editorPage.getByLabel("关联计划").selectOption({ label: planTitle });
    await editorPage.getByLabel("单价").fill("300");
    await editorPage.getByLabel("数量").fill("2");
    await editorPage.getByLabel("备注").fill(`E2E-报价-${suffix}`);
    await editorPage.getByRole("button", { name: "提交报价" }).click();
    await expect(editorPage.getByRole("main")).toContainText("300 × 2 = 600 CNY");

    const reviewerContext = await browser.newContext();
    const reviewerPage = await reviewerContext.newPage();
    await loginAs(reviewerPage, ACCOUNTS.reviewer);
    await openSection(reviewerPage, "quotes", projectId);
    await expect(reviewerPage.getByRole("main")).toContainText(planTitle);
    await reviewerPage.getByRole("main").locator(".knowledge-item").first().getByRole("button", { name: "通过" }).click();
    await expect(reviewerPage.getByRole("main")).toContainText("已通过");

    await editorContext.close();
    await reviewerContext.close();
  });
});
