# 工作台 E2E 回归（Playwright）

前置条件：前端 dev（`localhost:3000`）、后端（`localhost:8000`）、PostgreSQL 已启动，库里跑过种子数据。

> 用 `npm run start` 跑生产构建时，`NODE_ENV=production` 下 BFF 默认请求 `http://api:8000`；本地验收需显式设置 `$env:GEO_API_URL="http://localhost:8000"` 再启动，否则登录页会提示“暂时无法连接后端登录服务”。

## 跑法

```powershell
cd frontend
pnpm exec playwright test                      # 只跑只读用例（默认）
$env:E2E_WRITE="1"; pnpm exec playwright test e2e/workbench-write.spec.ts   # 追加写入用例
```

- 只读用例（`workbench-read.spec.ts`）：登录、5 个补齐页面渲染真实数据、管理员在计划/报价页只读、编辑可见新增入口、只读账号的成员管理门禁。
- 平台授权只读用例（`workbench-oauth.spec.ts`）：发布页“平台授权”页签可进入，provider 配置状态与已授权账号区域正常渲染；真实授权/撤销闭环由后端假 provider 用例覆盖，不连外部平台。
- 写入用例（`workbench-write.spec.ts`）：竞品新增→停用、指标新增版本→停用、计划新增→状态推进→报价提交→审核通过（跨编辑与审核两个账号）。**默认跳过**，避免每次跑都往 dev 库写数据。

## 账号

取自 `docs/DEV_ENV.md` 的本地开发种子，可用环境变量覆盖：

| 变量 | 默认值 |
| --- | --- |
| `E2E_USER_ADMIN` / `E2E_PASS_ADMIN` | `geo_admin` / `geo-admin-dev` |
| `E2E_USER_EDITOR` / `E2E_USER_REVIEWER` / `E2E_USER_VIEWER` | `geo_editor` / `geo_reviewer` / `geo_viewer` |
| `E2E_PASS_USER` | `geo-user-dev` |
| `E2E_BASE_URL` | `http://localhost:3000` |
| `E2E_PROJECT_ID` | 空（默认取登录后 URL 里的 `project_id`） |

## mock 冒烟（CI 跑的就是这一套）

不依赖后端与数据库：`playwright.mock.config.ts` 会自己起一个 mock 模式的 dev（默认端口 3100），
用例为 `e2e/mock-smoke.spec.ts`（登录 → 首页 → 关键面板渲染）。

```powershell
cd frontend
pnpm exec playwright test --config=playwright.mock.config.ts
```

注意两点：

- **必须先停掉本地 3000 的 dev**：Next 16 不允许同一目录起第二个 dev server，配置里
  `reuseExistingServer: false`，两个一起跑会报 `Another next dev server is already running`。
- 需要浏览器时可复用 `E2E_CHROME_PATH`（见下节）。

## 浏览器

`pnpm exec playwright install chromium` 会下载 Playwright 指定版本的 Chromium。若网络受限或已有现成 Chromium，可用 `E2E_CHROME_PATH` 指向本机可执行文件跳过下载，例如：

```powershell
$env:E2E_CHROME_PATH="$env:LOCALAPPDATA\ms-playwright\chromium-1248\chrome-win64\chrome.exe"
```

## 写入用例的清理

写入用例的标题/编码都带 `E2E-` 前缀或 `e2e_` 前缀，跑完按前缀清理即可：

```sql
delete from media_quotes where note like 'E2E-%';
delete from content_plans where title like 'E2E-%';
delete from metric_definitions where code like 'e2e_%';
delete from competitors where name like 'E2E-%';
```

## 失败排查

- 失败会保留 `test-results/` 下的截图、trace 与页面快照；`pnpm exec playwright show-trace <trace.zip>` 回放。
- 登录后若 URL 里没有 `project_id`，用例会等待前端补上（最多 20s）；仍为空时可用 `E2E_PROJECT_ID` 指定。
