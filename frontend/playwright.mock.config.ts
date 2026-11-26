import { defineConfig, devices } from "@playwright/test";

/**
 * CI 专用配置：mock 模式冒烟，不依赖后端。
 *
 * 与默认 `playwright.config.ts` 的区别：
 * - 默认配置跑真实接口（需要 dev 前端 + 后端 + PG），用于本地完整回归；
 * - 本配置自起一个 `next dev`（`GEO_API_MODE=mock`）在独立端口，CI 里可直接跑。
 *
 * `isMockMode()` 要求 NODE_ENV !== production，所以这里必须是 dev 而不是 start。
 */
const PORT = Number(process.env.GEO_E2E_PORT ?? 3100);

export default defineConfig({
  testDir: "./e2e",
  testMatch: ["**/mock-smoke.spec.ts", "**/mock-tz-*.spec.ts"],
  timeout: 45_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: [["list"]],
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    locale: "zh-CN",
    viewport: { width: 1280, height: 900 },
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    launchOptions: process.env.E2E_CHROME_PATH ? { executablePath: process.env.E2E_CHROME_PATH } : {},
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    // 用 process.execPath：CI 与本地都能定位同一个 node，不依赖 PATH 里有什么。
    command: `"${process.execPath}" node_modules/next/dist/bin/next dev --port ${PORT}`,
    url: `http://127.0.0.1:${PORT}/login`,
    // CI 默认自起 mock 服务；本地允许复用已起的服务。
    // GEO_E2E_REUSE=1 可强制复用（用于验证“CI 模式下 mock 缺失必须失败”这条门禁）。
    reuseExistingServer: process.env.GEO_E2E_REUSE === "1" || !process.env.CI,
    timeout: 180_000,
    env: { GEO_API_MODE: "mock", NEXT_TELEMETRY_DISABLED: "1" },
  },
});
