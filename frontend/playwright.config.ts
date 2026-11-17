import { defineConfig, devices } from "@playwright/test";

/**
 * 工作台 E2E 回归。
 * 前置：前端 dev（localhost:3000）+ 后端（localhost:8000）+ PG 已启动。
 * 写入类用例默认跳过，需要时显式开启：E2E_WRITE=1 pnpm exec playwright test
 */
export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    locale: "zh-CN",
    viewport: { width: 1280, height: 900 },
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    // 离线环境或浏览器包下载受限时，可显式指定本机已有的 Chromium
    launchOptions: process.env.E2E_CHROME_PATH ? { executablePath: process.env.E2E_CHROME_PATH } : {},
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
