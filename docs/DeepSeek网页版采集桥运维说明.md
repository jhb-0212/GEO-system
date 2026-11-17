# DeepSeek 网页版联网搜索采集桥 运维说明

> 适用：运维 / 系统管理员。2026-11-17 首次落地，代码在 `backend/scripts/deepseek_websearch_bridge.py`，
> 后端适配器在 `backend/app/services/deepseek_websearch_adapter.py`，协议值 `deepseek_websearch`。

## 一、为什么要单独起一个桥

- DeepSeek 官方 API 没有联网搜索能力（能力矩阵里 `supports_search=false`），拿不到 DeepSeek 自己的检索来源；
- 要拿"DeepSeek 检索了哪些网页、怎么引用"，只能走 `chat.deepseek.com` 的「智能搜索」；
- API 与 Celery Worker 里跑浏览器既不稳也不安全，所以把浏览器隔离成独立进程，用 `127.0.0.1` 上的 HTTP 暴露 `/health` 与 `/collect`，后端只发 httpx 请求。

链路：

```
Worker → deepseek_websearch 适配器 → httpx → 采集桥(127.0.0.1:8099) → Playwright → Edge（持久化登录） → chat.deepseek.com
```

## 二、前置条件

| 项 | 要求 |
| --- | --- |
| Python 依赖 | `pip install playwright==1.49.1`（backend venv 内） |
| 浏览器 | 本机 Edge（`--channel msedge`，实测 157.x 可用）；不必下载 chromium |
| 登录态 | 首次必须人工登录一次，写入 `backend/var/browser/deepseek-profile` |
| 端口 | 默认 `127.0.0.1:8099`，只监听本机，不要暴露到公网 |

`backend/var/` 是运行时目录，不要提交 profile 目录。

## 三、首次登录（只需做一次）

```powershell
cd C:\Users\EDY\Desktop\GEO系统开发\geo-system\backend
./.venv/Scripts/python.exe scripts/deepseek_websearch_bridge.py login --channel msedge
```

- 会弹出一个可见的 Edge 窗口，请在里面扫码 / 验证码 / 密码完成登录；
- 脚本检测到已离开 `/sign_in` 且出现输入框就写回 profile 并退出，默认最多等 300 秒（`--login-timeout`）；
- **登录由人完成，脚本不读取、不导出 cookie**；
- 同一 profile 只能被一个进程占用：跑 `login` 前先停掉正在跑的 `serve`，`login` 结束后再起 `serve`。

## 四、起服务

```powershell
cd C:\Users\EDY\Desktop\GEO系统开发\geo-system\backend
./.venv/Scripts/python.exe scripts/deepseek_websearch_bridge.py serve --channel msedge
```

参数：

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `--host` | `127.0.0.1` | 只监听本机，不要改成 `0.0.0.0` |
| `--port` | `8099` | 需与入口 `entry_url` 一致 |
| `--channel` | `msedge` | `msedge` / `chrome` / `chromium` |
| `--profile` | `backend/var/browser/deepseek-profile` | 登录态目录 |
| `--headed` | 关 | 排障时用可见浏览器跑 serve |
| `--min-interval` | `15` | 两次采集的最小间隔（秒），防风控 |
| `--login-timeout` | `300` | 仅 `login` 模式使用 |

可选 Token 鉴权：进程环境里有 `DEEPSEEK_WEBSEARCH_TOKEN` 时，请求必须带 `Authorization: Bearer <token>`；不设则不校验。

## 五、健康检查

```powershell
curl.exe http://127.0.0.1:8099/health
```

返回字段：

| 字段 | 含义 |
| --- | --- |
| `ok` | 服务本身可用 |
| `logged_in` | 浏览器探测结果；`false` 表示 profile 里没有有效登录 |
| `profile` | 当前 profile 目录 |
| `browser_channel` / `browser_started` | 浏览器通道与是否已拉起 |
| `last_collect` | 上一次采集的登录态与时间 |

注意：`/health` 会真的拉起浏览器访问首页，冷启动需要十几秒，不是纯粹的内存检查。

## 六、采集接口

```powershell
curl.exe -X POST http://127.0.0.1:8099/collect -H "Content-Type: application/json" -d "{\"question\":\"广东省AI数字人才就业实训基地在广州哪里，怎么报名？\",\"timeout_seconds\":180}"
```

返回：`logged_in`、`model_name`（固定 `deepseek-websearch`）、`answer`、`citations[]`、`searched_page_count`（页面出现"搜索到 N 个网页"时才有值，否则 `null`）、`smart_search_on`、`session_url`、`elapsed_ms`。

状态码与后端落库的对应：

| 桥返回 | 适配器抛出 | 样本/任务结果 |
| --- | --- | --- |
| 200 + 正常回答 | `AnswerPayload` | 正常落样本，`engine_model=deepseek-websearch` |
| 409 + `login_required` | `LoginBlockedFailure` | `login_blocked`，不自动重试、不算未命中 |
| 401 / 403 | `AccessBlockedFailure` | `access_blocked`（桥 Token 不对） |
| 429 | `RateLimitedFailure` | `rate_limited` |
| 504 | `TransientCollectionFailure` | `timeout`，可重试 |
| 5xx | `TransientCollectionFailure` | 可重试失败 |
| 连不上桥 | `AccessBlockedFailure` | `access_blocked`，`entry_url` 或桥进程有问题 |
| 200 但 `answer` 为空 | `CollectionFailure` | 不落 hit/miss |

桥内部细节：
- 全程单浏览器 + 全局锁，一次只处理一个请求，并强制最小间隔，宁可排队也不并发轰；
- 每题从首页开新会话，若「智能搜索」开关未选中会自动点开，返回里 `smart_search_on` 可核对；
- 回答里页面渲染的 `-\n9` 引用编号，适配器入库前规范成 `[9]`；
- 引用去重后按 URL 落 citations，`deepseek.com` 自身的链接不计入。

## 七、登记入口与切换口径

脚本：`backend/scripts/register_deepseek_websearch.py`

```powershell
cd C:\Users\EDY\Desktop\GEO系统开发\geo-system\backend
# 演练（不写库）
./.venv/Scripts/python.exe scripts/register_deepseek_websearch.py
# 建/更新入口，保持现有 active 状态
./.venv/Scripts/python.exe scripts/register_deepseek_websearch.py --apply
# 启用网页版入口，并停用同引擎其它入口
./.venv/Scripts/python.exe scripts/register_deepseek_websearch.py --apply --activate-websearch
# 切回官方 API 采集口径
./.venv/Scripts/python.exe scripts/register_deepseek_websearch.py --apply --activate-api
```

**关键约束**：`_active_engine_entries` 每个引擎只取一个有效入口（按 `created_at` 最早）。所以同一 DeepSeek 引擎下 API 入口和网页版入口**不能同时 active**，否则批量任务仍会走 API 入口、口径悄悄变回"回答提及"。切口径必须用 `--activate-websearch` / `--activate-api`。

入口字段规则：

| 字段 | 值 |
| --- | --- |
| `entry_type` | 只能是 `web_user` |
| `protocol` | `deepseek_websearch` |
| `entry_url` | 桥地址，如 `http://127.0.0.1:8099`；未填则回落 `DEEPSEEK_WEBSEARCH_BRIDGE_URL` |
| `model_name` | `deepseek-websearch` |
| `credential_ref` | 可选；只存环境变量名（如 `DEEPSEEK_WEBSEARCH_TOKEN`），不填视为无需鉴权 |
| `supports_search` / `supports_citation` | 都应开启 |

`POST /api/v1/engines/{engine_id}/entries/{entry_id}/test-connection` 对协议 `deepseek_websearch` 走的是桥 `/health`：`logged_in` 不是 `True` 时返回 `login_blocked`，连通但未登录也算失败，不会置 `last_verified_at`。

## 八、配置项

| 环境变量 / 配置 | 默认 | 说明 |
| --- | --- | --- |
| `DEEPSEEK_WEBSEARCH_BRIDGE_URL` | 空 | 入口 `entry_url` 未填时的兜底桥地址 |
| `DEEPSEEK_WEBSEARCH_TIMEOUT_SECONDS` | `180` | 适配器等桥的最长时间；要大于单题实际耗时 |
| `DEEPSEEK_WEBSEARCH_TOKEN` | 空 | 桥 Token；设了就必须与桥进程同名变量一致 |

## 九、口径与业务解读

- 这是「DeepSeek 联网检索 + 生成回答」，与 `openai_compatible` 入口的「回答提及」不是同一种观测，**不要混算命中率**；
- 有 `citations` 时，来源结构（如全是 b2b168 / 万词里 / 搜狐号这类营销页、没有官网或权威信源）本身就是可交付的结论；
- `searched_page_count` 依赖页面文案，DeepSeek 改版会失效，取不到时按"未记录"处理，不要臆造数字。

## 十、排障清单

| 现象 | 排查 |
| --- | --- |
| `/health` 返回 `logged_in=false` | profile 过期或被挤下线，重跑一次 `login`（先停 `serve`） |
| 桥起不来、端口占用 | `Get-NetTCPConnection -LocalPort 8099` 找进程；profile 被另一个进程占用也会起不来 |
| `login` 卡在等待 | 确认弹窗是可交互的 Edge 前台窗口；超时改 `--login-timeout` |
| 采集一直 504 | 单题可能确实慢（实测 6 题约 30～60 秒），先把 `timeout_seconds` 和 `DEEPSEEK_WEBSEARCH_TIMEOUT_SECONDS` 调大；仍超时用 `--headed` 看页面卡在哪 |
| 回答拿到了但没引用 | 「智能搜索」没开或平台改版；看返回里的 `smart_search_on` |
| Worker 报 `access_blocked` | 桥没起、`entry_url` 写错、或 Token 不一致 |
| 任务显示 `login_blocked` | 按设计就是这样：人工登录后重跑，别调大重试次数 |

## 十一、已知局限

- 单实例单浏览器，吞吐就是串行的，6 题一轮按最小间隔算也要几分钟；适合基线/巡检，不适合高频批量；
- 依赖页面结构（`.ds-markdown`、`textarea`、`搜索到 N 个网页`），DeepSeek 前端改版需要回来改桥；
- 登录态过期不自动恢复，只能人工重新登录；
- 桥只监听本机，多机部署需要每台各起一份，或做成内网服务并加 Token；
- 官方 API 与网页版回答并不逐字一致，切口径属于统计口径变更，历史样本要按 `engine_model` 区分。
