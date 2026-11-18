# AI 平台入口自助接入说明（后端 MVP）

> 适用：系统管理员 / 运营配置人员。2026-11-13 首次实现，当前已开放 `openai_compatible`（DeepSeek、火山方舟、千帆 ERNIE 对话模型等）、`yuanbao_search`（腾讯云元宝 SearchPro）、`deepseek_web_search`（DeepSeek Responses 服务端联网工具）、`doubao_search`（火山方舟 Responses + `web_search`）与 `wenxin_search`（千帆 AI 搜索，旧产品，仅留档）五种协议。文心主路径是 `openai_compatible` + `ernie-5.1`，不是 `wenxin_search`。
> 2026-11-18 起，API Key **可以在系统里直接填写**（加密落库、接口与日志不回显），不再要求运维每次改 `.env` 重启；旧的 `credential_ref` 环境变量路径继续有效，优先级低于系统内填写。

## 零、目录批次（2026-11-13）

`backend/scripts/seed_platform_catalog.py` 管理 15 个国内监测候选入口：

- 首轮 4 个：豆包、腾讯元宝、DeepSeek、百度文心；文心主入口是千帆 ERNIE 对话模型（API），不是网页端或千帆 AI 搜索；
- 扩展 6 个：Kimi、千问、夸克、秘塔AI搜索、百度AI搜、360纳米AI；
- 探测 5 个：智谱清言、讯飞星火、微信搜一搜AI、知乎直答、小红书点点。

扩展 6 个和探测 5 个先落目录与入口配置，`protocol=custom`、引擎和入口均 `is_active=false`，不参与 `generate_tasks`。因此 24 格基线仍是 4×6=24，不会变成 15×6。官方入口、联网能力、来源可见性、访问限制、最近核验日期由运营核验后补；未接协议前不会伪造调用。

## 一、能力边界

- 运营可以自助维护：入口地址、协议、模型名、密钥（系统内填写或环境变量名）、启停、备注。
- 密钥两种来源，**库内密文优先**：① 前端弹窗 / 接口里传 `api_key`（写入时按 `SECRET_KEY` 派生密钥加密，密文带 `v1:` 前缀，列表与响应都不回显）；② 旧的 `credential_ref` 指向 API/Worker 进程环境变量（如 `DEEPSEEK_API_KEY`）。系统内清空后自动回落到环境变量。
- 换 `SECRET_KEY` 会让已保存的密文失效（表现为“已配置但调用失败”），需要重新填一次 Key。
- 只有已实现协议（`openai_compatible`、`yuanbao_search`、`deepseek_web_search`、`doubao_search`、`wenxin_search`）会被 Worker 真正调用；`custom` 入口仍走明确失败 `access_blocked`，不会伪造回答。
- `yuanbao_search` 调用的是腾讯云元宝 SearchPro，返回检索结果摘要，不是元宝对话生成答案；报表/样本以 `engine_model=yuanbao-search` 标识，业务解读写“元宝搜索可见性”，不要写成“元宝回答”。
- `doubao_search` 走方舟 Responses `web_search`，返回的是**生成回答 + url_citation 引用**（`answer_kind=answer`）；`yuanbao_search` / `wenxin_search` 返回检索结果（`answer_kind=search_result`），两类提及率不得合并统计。
- **文心主路径**走 `openai_compatible`：`entry_url=https://qianfan.baidubce.com/v2`、`model_name=ernie-5.1`、`credential_ref=QIANFAN_API_KEY`；入口 `supports_search=true` 时适配器在请求体顶层加 `web_search:{"enable":true}`，返回**生成回答**（`answer_kind=answer`），当前实测无结构化 URL 引用。它调用的是千帆 ModelBuilder 的 ERNIE 对话模型，不是 `/v2/ai_search/web_search`。
- `wenxin_search` 是独立的千帆 AI 搜索检索产品（`/v2/ai_search/web_search`），返回 `references` 检索结果（`answer_kind=search_result`）；2026-11-17 已停用留档，不再作为文心主入口。不要把它和 ERNIE 对话模型混用或合并统计。
- `deepseek_web_search` 调 DeepSeek `POST /responses` 并声明服务端工具 `tools:[{"type":"deepseek_web_search"}]`，由模型自己搜索/打开网页后作答，返回**生成回答 + url_citation 引用**（`answer_kind=answer`，默认模型 `deepseek-flash`）。DeepSeek 官方 `/v1/tools/search`（原 `deepseek_search`）已于 2026-11-17 永久删除，每个平台只保留一条主路径，不再并存两份样本。
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

### 2. 决定密钥放在哪

- **推荐**：在系统里填（前端「AI 平台入口」弹窗的 `API Key` 输入框，或接口传 `api_key`）。写入即加密落库，换 Key 只需重填，不用重启 API/Worker。
- 兼容旧路径：在 API 与 Worker 进程环境预置变量名（`credential_ref`）。

```powershell
# 仅当走环境变量路径时需要；只配在进程环境，不要提交到仓库
$env:DEEPSEEK_API_KEY = "sk-..."
```

走环境变量时 Worker 与 API 必须都能读到同名变量；只配 API 不配 Worker，采集仍会落 `failed`。

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
  "api_key": "sk-...",
  "credential_ref": "DEEPSEEK_API_KEY",
  "supports_search": false,
  "is_active": true
}
```

`api_key` 与 `credential_ref` 可以只填一个：填了 `api_key` 就优先用系统内密文；只填 `credential_ref` 就继续读进程环境。

字段规则：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `entry_type` | 是 | `openai_compatible` 只接受 `api` |
| `entry_url` | 启用时必填 | 填到版本根，如 `https://api.deepseek.com/v1`；服务端补 `/chat/completions` |
| `model_name` | 启用时必填 | 平台真实模型名，如 `deepseek-chat` |
| `credential_ref` | 否 | 受控密钥环境变量名：大写字母/数字/下划线，且以 `_API_KEY` / `_SECRET_KEY` / `_SECRET_ID` / `_ACCESS_KEY` / `_TOKEN` 结尾；不能是 `sk-...` 明文，也不能指向 `PATH`、`DATABASE_URL` 等非密钥变量 |
| `api_key` | 否 | 系统内填写的密钥明文，只用于写入；长度 ≤ 4096、不接受首尾空白；服务端加密后存 `encrypted_secret`，接口与列表都不回显 |
| `api_key_secondary` | 否 | 双密钥协议的第二值（当前仅腾讯元宝 SecretKey）；同样加密落库、不回显 |
| `is_active` | 否 | 默认 `true`；停用后 Worker 不选该入口 |

响应里的 `credential_configured` 表示“入口现在能不能拿到可用的密钥”（库内密文或环境变量任一），`credential_source` 说明来源：`database`=系统内填写、`environment`=进程环境变量、`none`=未配置；都不会返回 Key 值。

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
| `credential_missing` | 没读到可用密钥 | 在系统里填 `api_key`（推荐），或在 API/Worker 进程补对应环境变量并重启 |
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

PATCH 未传字段不变；`entry_url` / `model_name` / `credential_ref` / `access_note` 传 `null` 可清空，但启用中的 `openai_compatible` 入口清空 `entry_url` / `model_name` 会被拒绝，启用中的 `yuanbao_search` 入口清空 `entry_url` 且库内也没有密文时会被拒绝。

密钥字段的 PATCH 语义（三者互斥）：

| 传法 | 效果 |
| --- | --- |
| 不传 `api_key` | 保持系统内已保存的密钥不变 |
| `{"api_key": "sk-new"}` | 覆盖保存（重新加密），`credential_updated_at` 刷新 |
| `{"clear_api_key": true}` | 清空库内密文，改回读 `credential_ref` 环境变量；与 `api_key` 同传会 422 |

### 6. 进入采集链

入口 `is_active=true` 且协议为 `openai_compatible` 或 `yuanbao_search` 后，`geo.monitoring.execute` 会按入口自动构建适配器；运营不需要改代码。Key 缺失时该样本落 `failed`，不会被当成有效 GEO 回答。

## 二·补、文心一言（千帆 ERNIE 对话模型）

文心不是“百度 AI 搜索 / 千帆 AI 搜索”，而是千帆 ModelBuilder 的 ERNIE 对话模型，走 `openai_compatible`：

```json
{
  "entry_type": "api",
  "name": "文心一言 ERNIE 5.1（千帆对话模型）",
  "entry_url": "https://qianfan.baidubce.com/v2",
  "protocol": "openai_compatible",
  "model_name": "ernie-5.1",
  "credential_ref": "QIANFAN_API_KEY",
  "supports_search": true,
  "is_active": true
}
```

- `entry_url` 填 `https://qianfan.baidubce.com/v2`，服务端补 `/chat/completions`；不要填 `/v2/ai_search/web_search`。
- `supports_search=true` 时，适配器在请求体顶层加 `web_search:{"enable":true}`；`web_search:true` 会 400，`enable_search` / `disable_search` 在该 v2 接口不生效。
- 当前实测返回生成回答，但没有结构化 `search_info` / `url_citation`；GEO 引用统计按 0，不要伪造 URL。
- `wenxin_search` 是旧的千帆 AI 搜索检索产品，已停用留档，不要再选。

## 二·补、元宝搜索（`yuanbao_search`）

腾讯元宝当前可用的是腾讯云 `wsa` 服务的 `SearchPro` 接口，不是 OpenAI-compatible 的对话接口，也不能直接套 `/chat/completions`。它返回检索结果，适配器把 `title + passage/content + url` 归一成可审计文本，并把每条 `url` 写成 citation。

### 1. 两把密钥怎么给

**推荐：系统里直接填**——新建/编辑入口时分别填 `api_key`（SecretId）与 `api_key_secondary`（SecretKey），两者都加密落库、不回显，前端会按 `yuanbao_search` 协议自动出现第二个输入框。

兼容旧路径：给进程环境预置两个变量。

```powershell
$env:YUANBAO_SECRET_ID = "AKID..."
$env:YUANBAO_SECRET_KEY = "..."
```

走环境变量时，`credential_ref` 存 `YUANBAO_SECRET_ID`，SecretKey 由适配器固定读 `YUANBAO_SECRET_KEY`；API 与 Worker 两个进程都要能读到。

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

- `engine.entry.create`：记录入口名、协议、`credential_ref`，以及 `api_key_set` / `api_key_secondary_set` 布尔值，不记录任何 Key 值。
- `engine.entry.update`：记录变更字段名（含 `api_key` / `clear_api_key`），不记录字段值；另记两个 `*_set` 布尔。
- `engine.entry.test`：记录成功/失败与 `error_code`，不记录探针回答。
- `last_verified_at` 只在测试成功时更新；失败不覆盖上次成功时间。

## 四、当前未完成

- 其他既不是 OpenAI-compatible、也没有单独协议适配器的入口（如部分只提供网页/App 的平台）仍需后续开发。
- 元宝搜索适配器已接入，但需腾讯云 SecretId/SecretKey 才能实测；没有凭据时只能验证 `credential_missing` 分支。
- 没有真实 DeepSeek Key 时，只能验证配置/错误码链路，不能把结果当业务基线。
- 真实 24 格基线仍需 4 个平台凭据齐全；本地 Ollama smoke 只证明链路，不是平台业务基线。
