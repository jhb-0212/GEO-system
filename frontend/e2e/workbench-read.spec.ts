import { expect, test } from "@playwright/test";

import { ACCOUNTS, loginAs, openSection } from "./helpers";

test.describe("工作台 5 页只读回归（真实后端）", () => {
  test("五个补齐页面都能渲染真实数据", async ({ page }) => {
    const projectId = await loginAs(page, ACCOUNTS.admin);
    const main = page.getByRole("main");

    await openSection(page, "competitors", projectId);
    await expect(main).toContainText("共");
    await expect(main).toContainText("个竞品");

    await openSection(page, "metrics", projectId);
    await expect(main).toContainText("个版本");
    await expect(main).toContainText("rule_version");

    await openSection(page, "plans", projectId);
    await expect(main).toContainText("条计划");

    await openSection(page, "quotes", projectId);
    await expect(main).toContainText("条报价");
    await expect(main).toContainText("预算");

    await openSection(page, "members", projectId);
    await expect(main).toContainText("位有效成员");
  });

  test("项目管理员在计划/报价页是只读（content.write 只授 editor）", async ({ page }) => {
    const projectId = await loginAs(page, ACCOUNTS.admin);

    await openSection(page, "plans", projectId);
    await expect(page.getByRole("button", { name: "新增计划" })).toHaveCount(0);

    await openSection(page, "quotes", projectId);
    await expect(page.getByRole("button", { name: "新增报价" })).toHaveCount(0);
  });

  test("运营编辑能看到计划/报价的新增入口", async ({ page }) => {
    const projectId = await loginAs(page, ACCOUNTS.editor);

    await openSection(page, "plans", projectId);
    await expect(page.getByRole("button", { name: "新增计划" })).toBeVisible();

    await openSection(page, "quotes", projectId);
    await expect(page.getByRole("button", { name: "新增报价" })).toBeVisible();
  });

  test("只读账号打开成员管理被门禁拦下", async ({ page }) => {
    const projectId = await loginAs(page, ACCOUNTS.viewer);
    await openSection(page, "members", projectId);
    await expect(page.getByRole("main")).toContainText("只有项目管理员可以管理成员");
  });
});
