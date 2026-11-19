import { expect, test } from "@playwright/test";

import { ACCOUNTS, loginAs } from "./helpers";

/**
 * 平台授权只读冒烟：验证发布页有入口、能加载 providers/connections。
 * 真实 OAuth 授权闭环由 backend tests/test_oauth_flow.py 的假 provider 覆盖，避免 E2E 依赖外部平台。
 */
test.describe("平台授权入口（真实接口）", () => {
  test("运营编辑可看到平台授权页与配置状态", async ({ page }) => {
    const projectId = await loginAs(page, ACCOUNTS.editor);
    await page.goto(`/workbench?section=publishing&publish_tab=oauth&project_id=${projectId}`);
    await page.waitForSelector("main");
    await page.waitForLoadState("networkidle").catch(() => undefined);

    const main = page.getByRole("main");
    await expect(main).toContainText("平台授权");
    await expect(main).toContainText("通用 OAuth 授权码 + PKCE");
    await expect(main).toContainText("已授权账号");
    await expect(main.getByText(/尚未配置平台|连接账号/).first()).toBeVisible();
  });
});
