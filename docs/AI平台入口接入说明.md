# AI 平台入口自助接入说明（后端 MVP）

> 适用：系统管理员 / 运营配置人员。2026-11-13 首次实现，已开放 `openai_compatible`（DeepSeek、火山方舟、千帆 v2 等）和 `yuanbao_search`（腾讯云元宝 SearchPro）两种协议。
> 前端接入页尚未开发，本说明用接口调用完成配置；不要把 API Key 直接写进请求体或数据库。

## 零、目录批次（2026-11-13）

`backend/scripts/seed_platform_catalog.py` 管理 15 个国内监测候选入口：

- 首轮 4 个：豆包、腾讯元宝、DeepSeek、百度文心，保留现有 `web_user` 主入口，active；
- 扩展 6 个：Kimi、千问、夸克、秘塔AI搜索、百度AI搜、360纳米AI；
- 探测 5 个：智谱清言、讯飞星火、微信搜一搜AI、知乎直答、小红书点点。

扩展 6 个和探测 5 个先落目录与入口配置，`protocol=custom`、引擎和入口均 `is_active=false`，不参与 `generate_tasks`。因此 24 格基线仍是 4×6=24，不会变成 15×6。官方入口、联网能力、来源可见性、访问限制、最近核验日期由运营核验后补；未接协议前不会伪造调用。

## 一、能力边界

- 运营可以自助维护：入口地址、协议、模型名、密钥环境变量名、启停、备注。
- **不能**在接口里传 API Key 明文。`credential_ref` 只存环境变量名（如 `DEEPSEEK_API_KEY`），真实 Key 由运维在 API/Worker 进程环境中预置。
- 只有已实现协议（`openai_compatible`、`yuanbao_search`）会被 Worker 真正调用；`custom` 入口仍走明确失败 `access_blocked`，不会伪造回答。
- `yuanbao_search` 调用的是腾讯云元宝 SearchPro，返回检索结果摘要，不是元宝对话生成答案；报表/样本以 `engine_model=yuanbao-search` 标识，业务解读写“元宝搜索可见性”，不要写成“元宝回答”。
- 测试连接只发固定短探针，不创建监测样本、不保存回答正文；成功才回写 `last_verified_at`。
- 权限：入口维护是系统级能力 `engine.manage`，普通项目角色（含项目管理员）不能改全局平台目录；入口列表登录用户可读。

## 二、接入步骤（以 DeepSeek 为例）

### 1. 确认平台目录

```http
GET /api/v1/engines
Authorization: Bearer <token>
```

已有 4 个目标平台时直接取对应 `engine_id`；没有则先建：

```http
POST /api/v1/engines
Authorization: Bearer <token>
Content-Type: application/json

{"code": "deepseek", "name": "DeepSeek", "vendor": "深度求索", "supports_search": false, "supports_citation": false}
```

### 2. 在 API 与 Worker 环境预置 Key

```powershell
# 只配在进程环境，不要提交到仓库，也不要写进接口请求
$env:DEEPSEEK_API_KEY = "sk-..."
```

Worker 与 API 必须都能读到同名变量；只配 API 不配 Worker，采集仍会落 `failed`。

### 3. 新建入口

```http
POST /api/v1/engines/{engine_id}/entries
Authorization: Bearer <token>
Content-Type: application/json

{
  "entry_type": "api",
  "name": "DeepSeek 官方 API",
  "entry_url": "https://api.deepseek.com/v1",
  "protocol": "openai_compatible",
  "model_name": "deepseek-chat",
  "credential_ref": "DEEPSEEK_API_KEY",
  "supports_search": false,
  "is_active": true
}
```

字段规则：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `entry_type` | 是 | `openai_compatible` 只接受 `api` |
| `entry_url` | 启用时必填 | 填到版本根，如 `https://api.deepseek.com/v1`；服务端补 `/chat/completions` |
| `model_name` | 启用时必填 | 平台真实模型名，如 `deepseek-chat` |
| `credential_ref` | 否 | 环境变量名；只接受大写字母/数字/下划线，不能是 `sk-...` 明文 |
| `is_active` | 否 | 默认 `true`；停用后 Worker 不选该入口 |

响应里的 `credential_configured` 只表示当前 API 进程能否读到该环境变量，不返回 Key 值。

### 4. 测试连通性

```http
POST /api/v1/engines/{engine_id}/entries/{entry_id}/test-connection
Authorization: Bearer <token>
```

成功示例：

```json
{"data": {"success": true, "protocol": "openai_compatible", "endpoint": "https://api.deepseek.com/v1/chat/completions", "model_name": "deepseek-chat", "latency_ms": 312.4, "error_code": null, "message": "连接成功", "checked_at": "2026-11-13T03:20:00Z"}}
```

失败也会返回 200 信封，`success=false` 并给 `error_code`：

| error_code | 含义 | 处理 |
| --- | --- | --- |
| `unsupported_protocol` | 该协议还没适配器 | 改 `openai_compatible` 或等适配器开发 |
| `entry_url_missing` / `model_name_missing` / `credential_ref_missing` | 必填未填 | 补 `entry_url` / `model_name` / `credential_ref` |
| `credential_missing` | 环境变量没读到 | 在 API/Worker 进程补 `DEEPSEEK_API_KEY` 并重启 |
| `auth_failed` | 401/403 | Key 错误、无权限或余额/配额问题 |
| `endpoint_not_found` | 404 | `entry_url` 少了 `/v1` 或路径不对 |
| `rate_limited` | 429 | 平台限流，稍后重试或调低并发 |
| `timeout` / `unreachable` | 网络问题 | 检查出网、代理、DNS 与平台状态 |
| `upstream_error` / `http_error` | 5xx / 其他 4xx | 看平台侧状态，必要时提工单 |

### 5. 改配置

```http
PATCH /api/v1/engines/{engine_id}/entries/{entry_id}
Authorization: Bearer <token>
Content-Type: application/json

{"model_name": "deepseek-chat", "access_note": "2026-11-13 已核验", "is_active": true}
```

PATCH 未传字段不变；`entry_url` / `model_name` / `credential_ref` / `access_note` 传 `null` 可清空，但启用中的 `openai_compatible` 入口清空 `entry_url` / `model_name` 会被拒绝，启用中的 `yuanbao_search` 入口清空 `entry_url` / `credential_ref` 会被拒绝。

### 6. 进入采集链

入口 `is_active=true` 且协议为 `openai_compatible` 或 `yuanbao_search` 后，`geo.monitoring.execute` 会按入口自动构建适配器；运营不需要改代码。Key 缺失时该样本落 `failed`，不会被当成有效 GEO 回答。

## 二·补、元宝搜索（`yuanbao_search`）

腾讯元宝当前可用的是腾讯云 `wsa` 服务的 `SearchPro` 接口，不是 OpenAI-compatible 的对话接口，也不能直接套 `/chat/completions`。它返回检索结果，适配器把 `title + passage/content + url` 归一成可审计文本，并把每条 `url` 写成 citation。

### 1. 预置两个环境变量

```powershell
$env:YUANBAO_SECRET_ID = "AKID..."
$env:YUANBAO_SECRET_KEY = "..."
```

`credential_ref` 只存 `YUANBAO_SECRET_ID`；SecretKey 由适配器固定读取 `YUANBAO_SECRET_KEY`，不落库、不回显。API 与 Worker 两个进程都要能读到。

### 2. 新建入口

```http
POST /api/v1/engines/{engine_id}/entries
Authorization: Bearer <token>
Content-Type: application/json

{
  "entry_type": "api",
  "name": "腾讯元宝 SearchPro",
  "entry_url": "https://wsa.tencentcloudapi.com",
  "protocol": "yuanbao_search",
  "model_name": "yuanbao-search",
  "credential_ref": "YUANBAO_SECRET_ID",
  "supports_search": true,
  "supports_citation": true,
  "is_active": true
}
```

`entry_url` 可留空，适配器默认使用 `https://wsa.tencentcloudapi.com`；建议显式填写，便于审计。协议固定 `Version=2025-05-08`、`Action=SearchPro`，签名使用 TC3-HMAC-SHA256，`x-tc-action` 按小写参与签名。

### 3. 业务口径

- SearchPro 的 `Pages` 是 JSON 字符串数组，适配器取前 10 条，字段含 `title/date/url/passage/content/site/score/pics`；没有 `content` 时退回 `passage`。
- 这是“元宝搜索可见性”，不是“元宝生成式回答”。24 格基线中该平台的结果只能说明检索结果是否提及品牌/竞品、引用了哪些 URL，不能与 DeepSeek/豆包/文心的回答质量直接等同。
- 空 `Pages` 不是调用失败，按“未检索到结果”落样本；`RequestLimitExceeded` 落 `rate_limited`，`UnauthorizedOperation/ResourceNotFound` 落 `access_blocked`，`InternalError/ResourceUnavailable` 按可重试失败处理。

## 三、审计与排障

- `engine.entry.create`：记录入口名、协议、`credential_ref`，不记录 Key。
- `engine.entry.update`：记录变更字段名，不记录字段值。
- `engine.entry.test`：记录成功/失败与 `error_code`，不记录探针回答。
- `last_verified_at` 只在测试成功时更新；失败不覆盖上次成功时间。

## 四、当前未完成

- 前端接入页未开发，运营仍需通过接口配置。
- 其他既不是 OpenAI-compatible、也没有单独协议适配器的入口（如部分只提供网页/App 的平台）仍需后续开发。
- 元宝搜索适配器已接入，但需腾讯云 SecretId/SecretKey 才能实测；没有凭据时只能验证 `credential_missing` 分支。
- 没有真实 DeepSeek Key 时，只能验证配置/错误码链路，不能把结果当业务基线。
- 真实 24 格基线仍需 4 个平台凭据齐全；本地 Ollama smoke 只证明链路，不是平台业务基线。
