import { expect, test, type Page } from "@playwright/test";

/**
 * mock 模式判定：CI 与本地行为必须不同。
 *
 * - CI：工作流已显式指定 `GEO_API_MODE=mock`。此时登录页没有“前端演示环境”
 *   提示，说明 mock 没生效（环境变量没传进去 / 起错了服务）。这是门禁故障，
 *   必须让测试失败，不能静默 skip 成绿灯。
 * - 本地：允许复用已在跑的真实接口前端，此时显式 skip，并在报告里写明原因。
 */
export async function assertMockMode(page: Page): Promise<void> {
  await page.goto("/login");
  const note = page.locator(".demo-note");

  if (process.env.CI) {
    await expect(note, "CI 必须运行在 mock 模式：登录页未出现演示环境提示，说明 GEO_API_MODE 未生效").toBeVisible({
      timeout: 15_000,
    });
    await expect(note).toContainText("前端演示环境");
    return;
  }

  // mode 由 /internal/session 异步返回，先等提示条出现再判定，避免竞态误跳过
  await note.waitFor({ state: "visible", timeout: 15_000 }).catch(() => {});
  const text = (await note.count()) > 0 ? await note.first().innerText() : "";
  test.skip(!text.includes("前端演示环境"), "本地复用的是真实接口服务，跳过 mock 用例");
}
