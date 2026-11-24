import { expect, test } from "@playwright/test";

import { ACCOUNTS, loginAs, openSection } from "./helpers";

/**
 * 演示项目页面闭环：真实点击建号/停用，以及勾选批量归类。
 * 只对 `onbdem` 演练项目运行，默认跳过；开启：
 *   $env:E2E_WRITE="1"; $env:E2E_BASE_URL="http://127.0.0.1:3200"; pnpm exec playwright test e2e/workbench-demo-closure.spec.ts
 */
const WRITE_ON = () => process.env.E2E_WRITE === "1";
const DEMO_PROJECT = process.env.E2E_DEMO_PROJECT_ID ?? "cefcae3f-d9f5-4f4f-a5fe-6cc548aa3119";

test.describe("演示项目页面闭环（真实接口）", () => {
  test.skip(!WRITE_ON(), "写入用例默认跳过，避免污染 dev 库（置 E2E_WRITE=1 开启）");

  test("账号目录：页面建号后停用", async ({ page }) => {
    const suffix = Date.now().toString(36);
    const username = `demo-ui-${suffix}`;
    await loginAs(page, ACCOUNTS.admin);
    await openSection(page, "members", DEMO_PROJECT);

    const accountPanel = page
      .locator(".knowledge-list-panel")
      .filter({ hasText: "账号目录（系统管理员）" });
    await expect(accountPanel).toBeVisible();

    await accountPanel.getByLabel(/^账号 \*$/).fill(username);
    await accountPanel.getByLabel(/^显示名 \*$/).fill("页面闭环测试");
    await accountPanel.getByLabel(/^初始密码 \*$/).fill("demo-password-123");
    await accountPanel.getByRole("button", { name: "创建账号" }).click();

    await expect(page.getByText(`已创建账号 ${username}`)).toBeVisible();
    await accountPanel.getByPlaceholder("用户名 / 邮箱 / 显示名").fill(username);
    await accountPanel.getByRole("button", { name: "搜索", exact: true }).click();
    const row = accountPanel.locator(".knowledge-item").filter({ hasText: username });
    await expect(row).toContainText("启用");
    await page.screenshot({ path: "../验收-账号UI创建.png", fullPage: true });

    await row.getByRole("button", { name: "停用" }).click();
    await expect(page.getByText(`已停用 ${username}`)).toBeVisible();
    await expect(row).toContainText("已停用");
    await page.screenshot({ path: "../验收-账号UI停用.png", fullPage: true });
  });

  test("未知被引信源：页面勾选并批量归类", async ({ page }) => {
    await loginAs(page, ACCOUNTS.admin);
    await openSection(page, "samples", DEMO_PROJECT);
    await page.getByRole("tab", { name: /待复核渠道/ }).click();

    const sourcePanel = page
      .locator(".knowledge-list-panel")
      .filter({ hasText: "未知被引信源（待归类）" });
    await expect(sourcePanel).toBeVisible();
    await sourcePanel.getByLabel("信源状态筛选").selectOption("classified");
    await expect(sourcePanel.locator(".knowledge-item").first()).toBeVisible();

    await sourcePanel.locator('input[type="checkbox"]').first().check();
    await sourcePanel.getByLabel("批量归类类别").selectOption("other");
    const bulkButton = sourcePanel.getByRole("button", { name: /归类已选/ });
    await expect(bulkButton).toBeEnabled();
    await bulkButton.click();
    await expect(page.getByText(/已归类 \d+ 个域名，回填 \d+ 条引用/)).toBeVisible();

    await page.screenshot({ path: "../验收-站点批量UI.png", fullPage: true });
  });
});
