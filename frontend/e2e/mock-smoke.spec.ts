import { expect, test } from "@playwright/test";

/**
 * CI 用的冒烟用例（mock 模式，不依赖后端 / 数据库 / Redis）。
 *
 * 与 `workbench-read.spec.ts` 的分工：
 * - 那边跑真实接口，验证"接上了"，需要本地后端起好、库里有种子数据；
 * - 这里只验证"页面本身能走通"，给合并门禁一条不依赖环境的证据。
 * 只断言三件事：能登录、能到面板、拿到的确实是演示数据（而不是假装成功）。
 */
test("mock 模式：可登录并打开内容审核面板", async ({ page }) => {
  await page.goto("/login");
  test.skip((await page.locator(".demo-note").filter({ hasText: "前端演示环境" }).count()) === 0, "当前是真实接口模式，跳过 mock 冒烟");

  // mock 模式下演示账号与密码都是 demo（见 app/login/page.tsx 的提示文案）
  await page.locator("#username").fill("demo");
  await page.locator("#password").fill("demo");
  await page.getByRole("button", { name: /进入工作台/ }).click();

  await expect(page).toHaveURL(/\/workbench/);

  await page.goto("/workbench?section=reviews");
  await expect(page.getByText("内容审核").first()).toBeVisible();
  await expect(page.getByText("演示数据").first()).toBeVisible();
  await expect(page.getByRole("heading", { name: "内容版本" })).toBeVisible();
});
