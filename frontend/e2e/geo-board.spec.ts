import { expect, test } from "@playwright/test";

import { ACCOUNTS, loginAs } from "./helpers";

/**
 * 数据大屏固化为「接口 mock」回归：不依赖库里有多少样本，专门守住几个易回归的交互——
 * 品牌标识、13 平台柱、采集端联动、线索类型下拉、标记已审、导出 CSV。
 * 登录与权限仍走真实接口，只有大屏数据本身被拦截。
 */

const PROJECT_ID = "0295be7b-c1ab-449a-a837-80b11ad9465f";
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

function reportRows(device: string): Row[] {
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
  });
}

function boardOf(url: URL) {
  const device = url.searchParams.get("device") ?? "all";
  const leadKind = url.searchParams.get("lead_kind") ?? "all";
  const items = device === "mobile"
    ? PLATFORMS.slice(0, 6).map((name, index) => ({ engine_id: `e${index}`, engine_name: name, value: 18 - index, share: 0.2 }))
    : PLATFORMS.map((name, index) => ({ engine_id: `e${index}`, engine_name: name, value: 27 - index, share: 0.08 }));
  const rows = reportRows(device);
  const leadRows = leadKind === "traffic"
    ? [{ event: "访问官网", region: "广东·广州", ip_masked: "6a1e6f03", source: "DeepSeek", url: "https://chengcaiai.com", occurred_at: "2026-11-26T16:13:00+08:00" }]
    : leadKind === "lead"
      ? [{ event: "提交线索", region: "广东·深圳", ip_masked: "02ee189f", source: "豆包", url: null, occurred_at: "2026-11-27T15:13:00+08:00" }]
      : [
          { event: "访问官网", region: "广东·广州", ip_masked: "6a1e6f03", source: "DeepSeek", url: "https://chengcaiai.com", occurred_at: "2026-11-26T16:13:00+08:00" },
          { event: "提交线索", region: "广东·深圳", ip_masked: "02ee189f", source: "豆包", url: null, occurred_at: "2026-11-27T15:13:00+08:00" },
        ];
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
      total: 792,
      page: 1,
      page_size: 10,
      pages: 80,
      rows,
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
      counts: { all: 10, traffic: 7, lead: 3 },
    },
    notes: ["平台占比与报表明细都跟随采集端筛选，但分母不同（有效样本数 vs 引用条数），不互相换算。"],
  };
}

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
      if (key === "citation" && route.request().method() === "PATCH") {
        REVIEWED.add(url.searchParams.get("id") ?? "");
        await route.fulfill({ json: { data: { id: url.searchParams.get("id"), review_status: "manual_confirmed" } } });
        return;
      }
      await route.continue();
    });
  });

  test("品牌标识、13 平台、线索类型、标记已审、导出 CSV", async ({ page }) => {
    await loginAs(page, ACCOUNTS.admin);
    await page.goto(`/geo-board?project_id=${PROJECT_ID}`);
    await page.waitForSelector(".geo-engchart-col");

    await expect(page.locator(".geo-report-brand")).toContainText(BRAND);
    await expect(page.locator(".geo-engchart-col")).toHaveCount(13);
    await expect(page.locator(".geo-panel-head").filter({ hasText: "各平台问题占比" })).toContainText("全部端");

    const leadSelect = page.locator('select[aria-label="线索事件类型"]');
    await expect(leadSelect.locator("option")).toHaveText(["全部事件（10）", "访问官网（7）", "提交线索（3）"]);

    // 采集端切到移动端：柱数、chips、文案都要跟着换，不能只换标签。
    await page.locator('select[aria-label="采集端筛选"]').selectOption("mobile");
    await expect(page.locator(".geo-engchart-col")).toHaveCount(6);
    await expect(page.locator(".geo-panel-head").filter({ hasText: "各平台问题占比" })).toContainText("移动端");
    await expect(page.locator(".geo-panel-head").filter({ hasText: "各平台问题占比" })).not.toContainText("全部端");

    // 线索类型切到「提交线索」：只剩表单线索一行。
    await leadSelect.selectOption("lead");
    await expect(page.locator("table.geo-lead-table tbody tr")).toHaveCount(1);
    await expect(page.locator("table.geo-lead-table")).toContainText("提交线索");

    await page.locator('select[aria-label="采集端筛选"]').selectOption("all");

    // 导出：文件名带窗口结束日期，内容为当页明细。
    const download = page.waitForEvent("download");
    await page.getByRole("button", { name: "导出 CSV" }).click();
    expect((await download).suggestedFilename()).toMatch(/^GEO报表明细-\d{4}-\d{2}-\d{2}\.csv$/);

    // 标记已审：mock 收到 PATCH 后，刷新回来的行要变成「已复核」且按钮消失。
    const firstRow = page.locator("table.geo-report-table tbody tr").first();
    await firstRow.getByRole("button", { name: "标记已审" }).click();
    await expect(page.locator("table.geo-report-table tbody tr").first()).toContainText("已复核");
    await expect(page.locator("table.geo-report-table tbody tr").first().getByRole("button", { name: "标记已审" })).toHaveCount(0);
  });

  test("品牌档案缺失时回退项目名", async ({ page }) => {
    brandOverride = { name: "广州基地", configured: false, active: false };
    await loginAs(page, ACCOUNTS.admin);
    await page.goto(`/geo-board?project_id=${PROJECT_ID}`);
    await page.waitForSelector(".geo-engchart-col");
    await expect(page.locator(".geo-report-brand")).toContainText("广州基地");
  });
});

