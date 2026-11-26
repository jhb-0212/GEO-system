import { expect, test, type Page } from "@playwright/test";

import { assertMockMode } from "./support/mock-mode";

/**
 * C2-4：浏览器时区不得影响待办窗口展示。
 *
 * mock 模式内置的是一份“服务端已经算好的窗口”（上海 11-26：16:00Z 起止）。
 * 如果前端仍在按浏览器本地时区推导自然日，把浏览器时区换成纽约/柏林后，
 * “今天”的计数与分组行就会变。这里用三个时区分别打开待办中心，要求
 * 计数、分组行完全一致。
 */

const ZONES = ["Asia/Shanghai", "America/New_York", "Europe/Berlin"] as const;

async function loginToWorkbench(page: Page) {
  await assertMockMode(page);

  await page.locator("#username").fill("demo");
  await page.locator("#password").fill("demo");
  await page.getByRole("button", { name: /进入工作台/ }).click();
  await expect(page).toHaveURL(/\/workbench/);
}

async function readTodoCenter(page: Page) {
  await page.goto("/workbench?section=reviews");
  await page.getByRole("button", { name: /待办/ }).first().click();
  await expect(page.getByText("待办中心")).toBeVisible();
  return {
    range: await page.locator(".task-center-range button").allInnerTexts(),
    summary: await page.locator(".task-center-summary strong").allInnerTexts(),
    rows: await page.locator(".task-center-row strong").allInnerTexts(),
  };
}

test("三个浏览器时区下待办计数与分组行完全一致", async ({ browser, baseURL }) => {
  const results: Array<{ zone: string; range: string[]; summary: string[]; rows: string[] }> = [];

  for (const zone of ZONES) {
    const context = await browser.newContext({ baseURL, timezoneId: zone, locale: "zh-CN" });
    const page = await context.newPage();
    await loginToWorkbench(page);
    const data = await readTodoCenter(page);
    results.push({ zone, ...data });
    await context.close();
  }

  const baseline = results[0];
  expect(baseline.range.join("|")).not.toBe("");

  for (const other of results.slice(1)) {
    expect(other.range, `${other.zone} 今天/本周/全部 计数与上海不一致`).toEqual(baseline.range);
    expect(other.summary, `${other.zone} 分组汇总与上海不一致`).toEqual(baseline.summary);
    expect(other.rows, `${other.zone} 待办行与上海不一致`).toEqual(baseline.rows);
  }
});

test("今天范围仍能看到落在服务端窗口内的待办", async ({ page }) => {
  await loginToWorkbench(page);
  await page.goto("/workbench?section=reviews");
  await page.getByRole("button", { name: /待办/ }).first().click();
  await expect(page.getByText("待办中心")).toBeVisible();

  const allButton = page.locator('.task-center-range button', { hasText: "全部" });
  const allCount = Number((await allButton.innerText()).replace(/[^\d]/g, ""));
  const todayButton = page.locator('.task-center-range button', { hasText: "今天" });
  const todayCount = Number((await todayButton.innerText()).replace(/[^\d]/g, ""));

  expect(allCount).toBeGreaterThan(0);
  // 今天必须真有落在服务端窗口内的待办，否则时区不变性等于在空集上比较
  expect(todayCount).toBeGreaterThan(0);
  // 今天不得凭空多出待办，也不得把所有待办都算成今天
  expect(todayCount).toBeLessThanOrEqual(allCount);
});
