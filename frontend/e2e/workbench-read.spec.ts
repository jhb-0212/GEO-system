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

  test("只读账号看不到成员管理，直接打开回落到工作概览", async ({ page }) => {
    const projectId = await loginAs(page, ACCOUNTS.viewer);
    await openSection(page, "members", projectId);
    await expect(page.getByRole("main")).toContainText("欢迎来到 GEO 工作台");
    await expect(page.getByRole("main")).not.toContainText("位有效成员");
  });

  test("项目管理员可看预算，并可提交与审批", async ({ page }) => {
    const projectId = await loginAs(page, ACCOUNTS.admin);
    await openSection(page, "budget", projectId);
    await expect(page.getByRole("main")).toContainText("四类费用分别审批，互不混算");
    await expect(page.getByRole("button", { name: "新增申请" })).toBeVisible();
  });

  test("渠道详情在发布归因为 0 时仍展示域名观测明细", async ({ page }) => {
    const projectId = await loginAs(page, ACCOUNTS.admin);
    await openSection(page, "channels", projectId);
    await page.getByRole("button", { name: /百家号/ }).first().click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toContainText("引用 0 · 样本 0 · 页面 0");
    await expect(dialog).toContainText("域名观测（人工确认引用，仅信源层）");
    await expect(dialog).toContainText("引用 10 条");
    await expect(dialog).toContainText("baijiahao.baidu.com");
  });

  test("项目管理员可确认项目资料，只读账号没有确认按钮", async ({ page }) => {
    const projectId = await loginAs(page, ACCOUNTS.admin);
    await openSection(page, "projects", projectId);
    await expect(page.getByRole("button", { name: "确认资料" }).or(page.getByRole("button", { name: "重新确认" })).first()).toBeVisible();

    await page.evaluate(() => window.sessionStorage.clear());
    const viewerProjectId = await loginAs(page, ACCOUNTS.viewer);
    await openSection(page, "projects", viewerProjectId);
    await expect(page.getByRole("button", { name: "确认资料" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "重新确认" })).toHaveCount(0);
  });

  test("运营编辑可提交预算，没有审批按钮", async ({ page }) => {
    const projectId = await loginAs(page, ACCOUNTS.editor);
    await openSection(page, "budget", projectId);
    await expect(page.getByRole("main")).toContainText("四类费用分别审批，互不混算");
    await expect(page.getByRole("button", { name: "新增申请" })).toBeVisible();
    await expect(page.getByRole("button", { name: "通过" })).toHaveCount(0);
  });

  test("审核账号可看预算，没有新增入口", async ({ page }) => {
    const projectId = await loginAs(page, ACCOUNTS.reviewer);
    await openSection(page, "budget", projectId);
    await expect(page.getByRole("main")).toContainText("四类费用分别审批，互不混算");
    await expect(page.getByRole("button", { name: "新增申请" })).toHaveCount(0);
  });

  test("只读账号看不到预算，直接打开回落到工作概览", async ({ page }) => {
    const projectId = await loginAs(page, ACCOUNTS.viewer);
    await openSection(page, "budget", projectId);
    await expect(page.getByRole("main")).toContainText("欢迎来到 GEO 工作台");
    await expect(page.getByRole("main")).not.toContainText("四类费用分别审批，互不混算");
  });

  test("招生账号只看线索，看不到预算", async ({ page }) => {
    const projectId = await loginAs(page, ACCOUNTS.lead_ops);
    await openSection(page, "leads", projectId);
    await expect(page.getByRole("main")).toContainText("线索");
    await openSection(page, "budget", projectId);
    await expect(page.getByRole("main")).toContainText("欢迎来到 GEO 工作台");
    await expect(page.getByRole("main")).not.toContainText("四类费用分别审批，互不混算");
  });
});
