# AI 平台入口自助接入说明（后端 MVP）

> 适用：系统管理员 / 运营配置人员。2026-11-13 首次实现，先开放 `openai_compatible` 协议（DeepSeek、火山方舟等）。
> 前端接入页尚未开发，本说明用接口调用完成配置；不要把 API Key 直接写进请求体或数据库。

## 一、能力边界

- 运营可以自助维护：入口地址、协议、模型名、密钥环境变量名、启停、备注。
- **不能**在接口里传 API Key 明文。`credential_ref` 只存环境变量名（如 `DEEPSEEK_API_KEY`），真实 Key 由运维在 API/Worker 进程环境中预置。
- 只有 `openai_compatible` 协议会被 Worker 真正调用；`custom` 入口仍走明确失败 `access_blocked`，不会伪造回答。
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
| `entry_url_missing` / `model_name_missing` | 必填未填 | 补 `entry_url` / `model_name` |
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

PATCH 未传字段不变；`entry_url` / `model_name` / `credential_ref` / `access_note` 传 `null` 可清空，但启用中的 `openai_compatible` 入口清空 `entry_url` / `model_name` 会被拒绝。

### 6. 进入采集链

入口 `is_active=true` 且协议为 `openai_compatible` 后，`geo.monitoring.execute` 会按入口自动构建适配器；运营不需要改代码。Key 缺失时该样本落 `failed`，不会被当成有效 GEO 回答。

## 三、审计与排障

- `engine.entry.create`：记录入口名、协议、`credential_ref`，不记录 Key。
- `engine.entry.update`：记录变更字段名，不记录字段值。
- `engine.entry.test`：记录成功/失败与 `error_code`，不记录探针回答。
- `last_verified_at` 只在测试成功时更新；失败不覆盖上次成功时间。

## 四、当前未完成

- 前端接入页未开发，运营仍需通过接口配置。
- 非 OpenAI-compatible 协议（百度文心、腾讯元宝等）仍需单独适配器。
- 没有真实 DeepSeek Key 时，只能验证配置/错误码链路，不能把结果当业务基线。
- 真实 24 格基线仍需 4 个平台凭据齐全；本地 Ollama smoke 只证明链路，不是平台业务基线。
