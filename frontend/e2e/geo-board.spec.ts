import { expect, test, type Page } from "@playwright/test";

import { ACCOUNTS, loginAs } from "./helpers";
import { assertMockMode } from "./support/mock-mode";

/**
 * 数据大屏固化为「接口 mock」回归：不依赖库里有多少样本，专门守住几个易回归的交互——
 * 品牌标识、13 平台柱、采集端联动、线索类型/地区下拉、标记已审、全量导出 CSV、无权限隐藏。
 *
 * 同一份 spec 跑两种环境：
 * - 真实接口（playwright.config.ts）：登录真实账号，权限差异按项目角色断言；
 * - mock（playwright.mock.config.ts，进 CI）：登录页有 #username 时用 demo/demo，大屏数据仍由下面的拦截提供。
 */

const REAL_PROJECT_ID = "0295be7b-c1ab-449a-a837-80b11ad9465f";
const BRAND = "广东省AI数字人才就业实训基地";
const REVIEWED = new Set<string>();
let brandOverride: { name: string; configured: boolean; active: boolean } | null = null;

const PLATFORMS = [
  "DeepSeek", "Kimi", "通义千问", "秘塔 AI 搜索", "腾讯元宝", "豆包", "360 纳米 AI",
  "天工 AI", "夸克 AI", "智谱清言", "百度文心", "腾讯混元", "讯飞星火",
];

type Row = {
  citation_id: string; training_word: string; question: string; source_title: string;
  answer_entity: string; platform: string; voucher_url: string; official_url: string;
  reviewed: boolean; occurred_at: string;
};

type LeadRow = {
  event: string; region: string; ip_masked: string; source: string; url: string | null; occurred_at: string;
};

function reportRows(device: string, start: number): Row[] {
  const platforms = device === "mobile" ? PLATFORMS.slice(0, 6) : PLATFORMS;
  return platforms.slice(0, 10).map((platform, index) => {
    const id = `cite-${device}-${index}`;
    return {
      citation_id: id,
      training_word: index % 2 ? "AIGC 短剧培训" : "AI数字人才实训基地",
      question: "广州哪里有值得报的 AIGC 短视频剪辑班？",
      source_title: "2026 广州 AI 实训机构盘点：AIGC 短剧班怎么选 - 知乎",
      answer_entity: "zhuanlan.zhihu.com",
      platform,
      voucher_url: "https://zhuanlan.zhihu.com/p/000001",
      official_url: "https://zhuanlan.zhihu.com",
      reviewed: REVIEWED.has(id),
      occurred_at: "2026-11-26T18:00:00+08:00",
    };
  }).slice(start);
}

/** 登录：按登录页提示条判断模式——mock 没有真实账号，用 demo/demo；真实模式走 helpers 的项目账号。 */
async function loginForBoard(page: Page, account: { username: string; password: string }): Promise<{ projectId: string; mock: boolean }> {
  await page.goto("/login");
  // 两种模式都有 #username，只能按提示条文案判：mock 写「前端演示环境」，live 写「真实接口模式」。
  const note = page.locator(".demo-note");
  await note.waitFor({ state: "visible", timeout: 15_000 }).catch(() => {});
  const noteText = (await note.count()) > 0 ? await note.first().innerText().catch(() => "") : "";
  const mock = noteText.includes("前端演示环境");
  if (process.env.CI) {
    // CI 必须 mock：提示不对就让门禁失败，不静默走真实登录。
    await assertMockMode(page);
  }
  if (mock) {
    await page.locator("#username").fill("demo");
    await page.locator("#password").fill("demo");
    await page.getByRole("button", { name: /进入工作台/ }).click();
    await page.waitForURL(/\/workbench/);
    return { projectId: "p-demo", mock: true };
  }
  await loginAs(page, account);
  return { projectId: REAL_PROJECT_ID, mock: false };
}

function boardOf(url: URL) {
  const device = url.searchParams.get("device") ?? "all";
  const leadKind = url.searchParams.get("lead_kind") ?? "all";
  const leadRegion = url.searchParams.get("lead_region") ?? "";
  const page = Math.max(1, Number(url.searchParams.get("page")) || 1);
  const items = device === "mobile"
    ? PLATFORMS.slice(0, 6).map((name, index) => ({ engine_id: `e${index}`, engine_name: name, value: 18 - index, share: 0.2 }))
    : PLATFORMS.map((name, index) => ({ engine_id: `e${index}`, engine_name: name, value: 27 - index, share: 0.08 }));

  const trafficRows: LeadRow[] = [
    { event: "访问官网", region: "广东·广州", ip_masked: "6a1e6f03", source: "DeepSeek", url: "https://chengcaiai.com", occurred_at: "2026-11-26T16:13:00+08:00" },
  ];
  const leadOnlyRows: LeadRow[] = [
    { event: "提交线索", region: "广东·深圳", ip_masked: "02ee189f", source: "豆包", url: null, occurred_at: "2026-11-27T15:13:00+08:00" },
  ];
  const baseRows = leadKind === "traffic" ? trafficRows : leadKind === "lead" ? leadOnlyRows : [...trafficRows, ...leadOnlyRows];
  const leadRows = leadRegion ? baseRows.filter((row) => row.region === leadRegion) : baseRows;

  return {
    project_window: { days: 30, start_date: "2026-10-29", end_date: "2026-11-27", timezone: "Asia/Shanghai" },
    brand: brandOverride ?? { name: BRAND, configured: true, active: true },
    has_demo: false,
    kpis: [
      { key: "training_words", label: "训练词总量", unit: "个", value: 12, window_value: 12, window_days: 30, spark: Array.from({ length: 30 }, (_, i) => (i > 26 ? 6 : 0)), source: "real", note: "启用中的目标关键词" },
      { key: "recommended_words", label: "推荐词总量", unit: "个", value: 12, window_value: 12, window_days: 30, spark: Array.from({ length: 30 }, () => 0), source: "real", note: "题库问题" },
      { key: "indexed_total", label: "累计收录总量", unit: "条", value: 792, window_value: 792, window_days: 30, spark: Array.from({ length: 30 }, (_, i) => (i < 3 ? 0 : 24 + i * 2)), source: "real", note: "引用证据条数" },
      { key: "lead_events", label: "线索事件量", unit: "条", value: 10, window_value: 10, window_days: 30, spark: Array.from({ length: 30 }, (_, i) => (i % 4 === 0 ? 3 : 0)), source: "real", note: "非机器人访问 + 表单线索" },
    ],
    top_keywords: {
      items: [{ rank: 1, keyword_id: "k1", name: "AI数字人才实训基地", questions: 2, citations: 176 }],
      total: 1,
      max: 176,
    },
    indexed_series: {
      source: "real",
      items: Array.from({ length: 30 }, (_, i) => ({ date: `2026-11-${String(i + 1).padStart(2, "0")}`, value: 24 + i * 26 })),
    },
    engine_share: { items, total: items.reduce((sum, item) => sum + item.value, 0) },
    report: {
      total: 20,
      page,
      page_size: 10,
      pages: 2,
      rows: reportRows(device, (page - 1) * 10),
      kind: "all",
      device,
      engines: [{ engine_id: null, engine_name: "全部", value: 792 }],
      selected_engine_id: null,
    },
    lead_events: {
      total: leadRows.length,
      page: 1,
      page_size: 10,
      pages: 1,
      rows: leadRows,
      kind: leadKind,
      region: leadRegion || null,
      regions: [{ region: "广东·广州", count: 1 }, { region: "广东·深圳", count: 1 }],
      counts: { all: 10, traffic: 7, lead: 3 },
    },
    notes: ["平台占比与报表明细都跟随采集端筛选，但分母不同（有效样本数 vs 引用条数），不互相换算。"],
  };
}

const CSV_BODY = "\ufeff序号,训练词,最新搜索词场景\r\n1,AI数字人才实训基地,广州哪里有值得报的 AIGC 短视频剪辑班？\r\n";

test.describe("GEO 数据大屏（接口 mock）", () => {
  test.beforeEach(async ({ page }) => {
    REVIEWED.clear();
    brandOverride = null;
    await page.route("**/internal/workbench/data**", async (route) => {
      const url = new URL(route.request().url());
      const key = url.searchParams.get("kind");
      if (key === "dashboard-board") {
        await route.fulfill({ json: { data: boardOf(url) } });
        return;
      }
      if (key === "dashboard-board-csv") {
        await route.fulfill({
          status: 200,
          headers: {
            "Content-Type": "text/csv; charset=utf-8",
            "Content-Disposition": 'attachment; filename="geo-report.csv"',
          },
          body: CSV_BODY,
        });
        return;
      }
      if (key === "citation" && route.request().method() === "PATCH") {
        REVIEWED.add(url.searchParams.get("id") ?? "");
        await route.fulfill({ json: { data: { id: url.searchParams.get("id"), review_status: "manual_confirmed" } } });
        return;
      }
      await route.continue();
    });
  });

  test("品牌标识、13 平台、采集端、线索类型与地区、标记已审、全量导出", async ({ page }) => {
    // 标记已审要 evidence.review：真实模式用 reviewer，mock 演示账号是全权限。
    const { projectId } = await loginForBoard(page, ACCOUNTS.reviewer);
    await page.goto(`/geo-board?project_id=${projectId}`);
    await page.waitForSelector(".geo-engchart-col");

    await expect(page.locator(".geo-report-brand")).toContainText(BRAND);
    await expect(page.locator(".geo-engchart-col")).toHaveCount(13);
    await expect(page.locator(".geo-panel-head").filter({ hasText: "各平台问题占比" })).toContainText("全部端");
    await expect(page.locator(".geo-platform-badge")).toHaveCount(10);

    const leadSelect = page.locator('select[aria-label="线索事件类型"]');
    await expect(leadSelect.locator("option")).toHaveText(["全部事件（10）", "访问官网（7）", "提交线索（3）"]);
    const regionSelect = page.locator('select[aria-label="线索地区筛选"]');
    await expect(regionSelect.locator("option")).toHaveText(["全部地区", "广东·广州（1）", "广东·深圳（1）"]);

    // 采集端切到移动端：柱数、chips、文案都要跟着换，不能只换标签。
    await page.locator('select[aria-label="采集端筛选"]').selectOption("mobile");
    await expect(page.locator(".geo-engchart-col")).toHaveCount(6);
    await expect(page.locator(".geo-panel-head").filter({ hasText: "各平台问题占比" })).toContainText("移动端");
    await expect(page.locator(".geo-panel-head").filter({ hasText: "各平台问题占比" })).not.toContainText("全部端");

    // 线索类型切到「提交线索」：只剩表单线索一行；再按地区收窄仍应只剩深圳那条。
    await leadSelect.selectOption("lead");
    await expect(page.locator("table.geo-lead-table tbody tr")).toHaveCount(1);
    await expect(page.locator("table.geo-lead-table")).toContainText("提交线索");
    await regionSelect.selectOption("广东·深圳");
    await expect(page.locator("table.geo-lead-table tbody tr")).toHaveCount(1);

    await page.locator('select[aria-label="采集端筛选"]').selectOption("all");

    // 导出：走服务端全量接口，文件名由前端按窗口结束日期给。
    const download = page.waitForEvent("download");
    await page.getByRole("button", { name: "导出全量 CSV" }).click();
    expect((await download).suggestedFilename()).toMatch(/^GEO报表明细-\d{4}-\d{2}-\d{2}\.csv$/);

    // 标记已审：mock 收到 PATCH 后，刷新回来的行要变成「已复核」且按钮消失。
    const firstRow = page.locator("table.geo-report-table tbody tr").first();
    await firstRow.getByRole("button", { name: "标记已审" }).click();
    await expect(page.locator("table.geo-report-table tbody tr").first()).toContainText("已复核");
    await expect(page.locator("table.geo-report-table tbody tr").first().getByRole("button", { name: "标记已审" })).toHaveCount(0);
  });

  test("品牌档案缺失时回退项目名", async ({ page }) => {
    brandOverride = { name: "广州基地", configured: false, active: false };
    const { projectId } = await loginForBoard(page, ACCOUNTS.admin);
    await page.goto(`/geo-board?project_id=${projectId}`);
    await page.waitForSelector(".geo-engchart-col");
    await expect(page.locator(".geo-report-brand")).toContainText("广州基地");
    await expect(page.locator(".geo-report-brand em")).toHaveText("未配置");
  });

  test("只读账号没有证据复核权限时隐藏「标记已审」，只显示待审", async ({ page }) => {
    const { projectId, mock } = await loginForBoard(page, ACCOUNTS.viewer);
    // mock 演示账号是全能力，权限差异只在真实项目里有意义。
    test.skip(mock, "mock 演示账号为全权限，权限差异只在真实项目断言");
    await page.goto(`/geo-board?project_id=${projectId}`);
    await page.waitForSelector(".geo-report-table tbody tr");
    const firstRow = page.locator("table.geo-report-table tbody tr").first();
    await expect(firstRow.getByRole("button", { name: "标记已审" })).toHaveCount(0);
    await expect(firstRow.locator(".geo-badge.is-muted")).toHaveText("待审");
  });
});
