# 接口契约（V1.0 冻结版）

> 由 C 按数据模型与审核意见整理，经审核收敛后随 `4499b20` 冻结，供 A/B 按此实现。V0.1 → V0.2 变更（角色边界与能力矩阵、统一错误信封、任务状态端点、发布状态机约束、凭证管理、导出审计全覆盖、路径补全）已并入本版；冻结后任何字段、路径、错误码、权限码变更须走契约变更单 + 迁移评审。

## 一、通用约定

### 1.1 鉴权与项目隔离

- 认证：`Authorization: Bearer <JWT>`，由 `POST /api/v1/auth/login` 签发。
- 项目上下文：项目内接口路径统一为 `/api/v1/projects/{project_id}/...`。
- 术语：接口/库表字段保留 `engine`、`engines`、`engine_id`；对内展示统一称 **AI 平台**，不称“模型”或“渠道”。
- 服务端顺序固定：解析身份 → 查 `project_members` 确认该项目授权 → 校验角色能力 → 执行。前端传的 `project_id` 只作定位参数，不作权限依据。
- 越权统一返回 `403`，且不区分“项目不存在”与“无权限”。

### 1.2 错误信封（与实现一致）

```json
{ "error": { "code": "project_forbidden", "message": "..." } }
```

错误码：`unauthorized`、`invalid_credentials`、`token_expired`、`token_invalid`、`token_stale`、`user_inactive`、`current_password_invalid`、`password_unchanged`、`system_admin_only`、`project_forbidden`、`insufficient_permission`、`path_escape`、`evidence_missing`、`export_too_large`、`task_rejected`、`validation_error`、`engine_missing`、`engine_entry_missing`、`engine_entry_exists`、`engine_entry_in_use`、`entry_url_missing`、`model_name_missing`、`protocol_entry_type_mismatch`；CR-004 追加 `competitor_missing`、`competitor_conflict`、`invalid_competitor_field`、`metric_missing`、`invalid_metric_field`、`cannot_remove_self`（明细见 `docs/契约变更单/CR-004-竞品指标成员链路补全.md`）；审批职责分离追加 `review_self_not_allowed`（400，提交人不能审批自己提交的内容版本或报价，见 `docs/链路能力矩阵与E2E回归-2026-11-16.md`）；预算提交追加 `budget_approver_required`（400，项目内没有除提交人外的有效 `budget.approve` 持有人（项目成员与账号均有效）时阻止提交）。
实现见 `backend/app/core/errors.py` 与 `app/main.py` 的统一异常处理器，禁止混用 FastAPI 默认的 `detail` 包装。

### 1.3 响应与分页

```json
{ "data": [], "meta": { "page": 1, "page_size": 20, "total": 137 } }
```

分页参数 `page`（默认 1）、`page_size`（默认 20，上限 100），列表统一返回 `{"data": [...], "meta": {"page", "page_size", "total"}}`；时间 ISO 8601 带时区。

排序：业务流水类（`leads`、`monitoring/tasks`、`publish/tasks`）按 `created_at` 降序；字典/目录类（`channels`、`engines`、`projects` 按 `code`，`members` 按成员 id）升序，保证翻页稳定。

已实现分页的端点：`GET projects`、`GET engines`、`GET members`、`GET channels`、`GET leads`、`GET monitoring/tasks`、`GET publish/tasks`。

### 1.4 幂等与异步

- 监测任务幂等键：`round_id + question_version_id + engine_entry_id + sampling_no`，重复提交返回既有记录。
- 发布任务幂等键：`account_id + channel_id + version_id + task_key`（等价于“账号+渠道+内容版本+任务ID”）。
- 耗时操作返回 `202` + `task_id`，通过统一的 `GET /api/v1/tasks/{task_id}` 轮询。
- 队列消息必须带 `project_id`，Worker 执行前重新核对（`app/core/task_guard.py`）。

### 1.5 统一任务状态端点（新增，V0.1 缺失）

`GET /api/v1/tasks/{task_id}`

```json
{
  "task_id": "8017e50d-...",
  "kind": "monitoring.execute | publish.execute | export.run",
  "project_id": "...",
  "status": "pending | running | succeeded | failed | revoked",
  "progress": { "done": 12, "total": 24 },
  "error": null,
  "created_at": "2026-11-10T17:32:25+08:00",
  "finished_at": null
}
```

约定：任务状态只反映执行器，不等于业务状态。业务状态（样本 `hit/miss/failed`、发布 `published/unknown`）以对应资源记录为准；任务失败时必须同步业务记录为失败原因，不允许“任务失败但业务仍 running”。

实现说明（`backend/app/api/tasks.py`，`docs/openapi.json` 已按此导出 schema）：

- 响应包在 `{"data": {...}}` 内（与 1.3 一致），上面示例是 `data` 的内容。
- `kind` 由 outbox topic 归一：`monitoring.task.execute` → `monitoring.execute`，`publish.task.execute` → `publish.execute`，`export.run` 保持不变。
- `progress`、`finished_at` 当前**无数据源**（outbox 只落状态、时间与错误描述），显式返回 `null`，不伪造数值；执行器补充进度落库后再填。
- `error` 取 `outbox_events.error_note` 文本（暂不含结构化错误码）。
- 额外返回 `topic`、`dispatched_at` 两个排障字段，属只增不减，不影响按本契约生成类型。

### 1.6 角色边界与能力矩阵

系统管理员与项目管理员是两个层级，不能互推：`sys_admin` 持有 `project.create` / `engine.manage`，但**不默认读写项目业务数据**；项目内权限只来自 `project_members` 里的角色。

| 能力 | sys_admin | project_admin | editor | reviewer | viewer | lead_ops |
| --- | --- | --- | --- | --- | --- | --- |
| 建项目 / 维护引擎目录 | 是 | 否 | 否 | 否 | 否 | 否 |
| 管理本项目成员（限授予 4 个业务角色） | 否（加入项目后按角色） | 是 | 否 | 否 | 否 | 否 |
| 题库写入 / 监测执行 / 内容写入 / 发布执行 | 否（加入项目后按角色） | 否 | 是 | 否 | 否 | 否 |
| 渠道台账维护 | 否（加入项目后按角色） | 是 | 是 | 否 | 否 | 否 |
| 内容审批 / 证据复核 | 否（加入项目后按角色） | 是 | 否 | 是 | 否 | 否 |
| 线索读写 | 否（加入项目后按角色） | 是 | 否 | 否 | 是 | 是 |
| 只读查看 | 否（加入项目后按角色） | 是 | 是 | 是 | 是 | 仅线索 |
| 导出（写审计） | 否 | 是 | 是 | 否 | 是 | 否 |
| 查看审计日志 | 否 | 是 | 否 | 是 | 否 | 否 |

实现锚点（分层，改权限只改前两处）：
- 能力矩阵唯一事实来源：`backend/app/core/permissions.py`（`PERMISSION_CATALOG` / `ROLE_PERMISSIONS` / `GRANTABLE_ROLE_CODES` / `can_grant`）。
- 领域判定：`backend/app/services/access.py`（`resolve_project_context` / `ensure_capability` / `ensure_system_capability` / `ensure_can_grant`），拒绝先写 `audit_logs` 再抛异常。
- HTTP 适配：`backend/app/api/deps.py` 只有 `get_current_user`、`get_project_context`、`require_permission`、`require_system_permission` 四个入口。
- 请求模型：`backend/app/schemas/`；成功响应统一 `{"data": ...}`，错误统一 `{"error": {"code", "message"}}`（`app/api/responses.py` + `app/core/errors.py`）。

越权判定规则：目标角色只能是 `editor` / `reviewer` / `viewer` / `lead_ops`；不得授予 `project_admin` / `sys_admin`；管理类能力不随角色转授；项目管理员不得调整同为项目管理员的成员。

`sys_admin` 的单一判定链：系统级权限只认 `users.is_system_admin=true` + 能力矩阵（`project.create` / `engine.manage`），`roles.sys_admin` 仅作能力映射字典，**禁止写进 `project_members`**；若有人绕过接口直接写入，服务端按无效授权拒绝（403 `project_forbidden`，审计 `reason=sys_admin_role_not_assignable`），不会因该角色行拿到项目数据。

系统级异步边界：`outbox_events.project_id` 允许为空，但库层 CHECK `ck_outbox_events_project_or_system` 规定“无项目归属的事件，topic 必须是 `system.*`”。因此引擎目录同步、权限矩阵同步这类系统事件可以正常入队（`system.engine.catalog.sync`、`system.permission.matrix.sync`），而 `monitoring.task.execute` 等项目级 topic 不带项目 id 会被数据库直接拒绝。系统级变更同时写 `audit_logs`。

## 二、端点骨架

权限列说明：`editor+` / `reviewer` 这类写法只是便于阅读的简称，**实际判定一律按能力码**（见 1.6）。例如“`editor+`”表示请求方需具备该端点对应的写能力（`question.write` / `monitoring.execute` / `content.write` / `publish.execute` / `channel.write`），而不是按角色名硬编码。

### 2.1 认证与用户

| 方法 | 路径 | 说明 | 权限 |
| --- | --- | --- | --- |
| POST | /api/v1/auth/login | 用户名密码换 JWT | 公开 |
| GET | /api/v1/auth/me | 当前用户及项目授权 | 登录用户 |
| POST | /api/v1/auth/password | 改密码（旧令牌立即失效） | 登录用户 |

以本分支的实现为准：`login` 的 `data` 包含 `access_token`、`token_type="bearer"`、`expires_in`；当前用户和项目授权由 `me` 返回，不要求登录响应重复用户资料。`me.projects` 仅列出当前用户仍为活跃成员的活跃项目，每项包含 `id/code/name/role_code/permissions`；系统管理员不因系统身份自动取得项目成员权限。账号或密码错误返回 `401 invalid_credentials`，缺少令牌返回 `401 unauthorized`，令牌版本缺失或失效返回 `401 token_stale`，JWT 时间过期返回 `401 token_expired`。改密返回新令牌，旧令牌立即失效。该响应与错误码变更登记于 CR-003。

### 2.2 项目与权限

| 方法 | 路径 | 说明 | 权限 |
| --- | --- | --- | --- |
| GET | /api/v1/projects | 可访问项目列表 | 登录用户 |
| POST | /api/v1/projects | 新建项目 | 系统管理员 |
| GET | /api/v1/projects/{project_id} | 项目详情 | 项目成员 |
| PATCH | /api/v1/projects/{project_id} | 改名 / 状态 / 时区 | 系统管理员 |
| POST | /api/v1/projects/{project_id}/confirm | 确认项目资料并设置优先级（1 最高、5 最低）；`priority` 必填，`note` 可空；落 `business_confirmed_at` / `business_confirmed_by`，写 `project.business_confirm` 审计 | `project.member.manage` |
| GET / POST | /api/v1/projects/{project_id}/members | 成员与授权（已实现） | `project.member.manage` |
| PATCH | /api/v1/projects/{project_id}/members/{member_id} | 改角色或停用（已实现，不得越级授予） | `project.member.manage` |

### 2.3 题库与关键词

| 方法 | 路径 | 说明 | 权限 |
| --- | --- | --- | --- |
| GET / POST | /api/v1/projects/{project_id}/questions | 列表 / 新建 | editor+ |
| PATCH | /api/v1/projects/{project_id}/questions/{question_id} | 状态、人群、意图、优先级 | editor+ |
| GET / POST | /api/v1/projects/{project_id}/questions/{question_id}/versions | 版本列表 / 追加版本 | editor+ |
| GET | /api/v1/projects/{project_id}/keywords | 目标词列表；可带已关联内容版本数量 | `question.read` |
| POST | /api/v1/projects/{project_id}/keywords | 新建目标词；`name` 项目内唯一 | `question.write` |
| PATCH | /api/v1/projects/{project_id}/keywords/{keyword_id} | 改名、分类、优先级、启停、备注 | `question.write` |
| DELETE | /api/v1/projects/{project_id}/keywords/{keyword_id} | 软删：置 `is_active=false`，保留 `content_version_keywords` 关联与审计 | `question.write` |

关键词通过 `question_keywords` 关联题目、通过 `content_version_keywords` 关联内容版本；创建关键词时可同时提交 `question_ids` 和 `content_version_ids`，跨项目关联返回 400 `question_project_mismatch` / `content_version_project_mismatch`。不得用 `notes` JSON、逗号串或 `content_version_questions` 传递推导冒充题目关联。

改题目正文必须新开版本并同步 `current_version_no`，旧版本不可编辑。

B2 题库与 B3 关键词端点已实现（2026-11-13，PR #34）；关键词 DELETE 只做软删，不物理删除，未关联题目的关键词仍可保留历史内容版本关联。

### 2.4 AI 平台目录

| 方法 | 路径 | 说明 | 权限 |
| --- | --- | --- | --- |
| GET | /api/v1/engines | AI 平台列表（系统级） | 登录用户 |
| POST | /api/v1/engines | 新建平台 | `engine.manage` |
| GET | /api/v1/engines/{engine_id}/entries | 入口列表（含 `credential_configured`） | 登录用户 |
| POST | /api/v1/engines/{engine_id}/entries | 新建入口 | `engine.manage` |
| PATCH | /api/v1/engines/{engine_id}/entries/{entry_id} | 修改入口、模型、密钥引用、启停 | `engine.manage` |
| POST | /api/v1/engines/{engine_id}/entries/{entry_id}/verify | 用户端/应用内搜索入口人工核验，写最近核验时间 | `engine.manage` 或项目级 `engine.verify` |
| POST | /api/v1/engines/{engine_id}/entries/{entry_id}/test-connection | 测试连通性 | `engine.manage` |
| DELETE | /api/v1/engines/{engine_id}/entries/{entry_id} | 删除误建的入口（模型）；被监测任务引用时返回 400 `engine_entry_in_use`，建议改为停用 | `engine.manage` |

平台目录不提供删除接口：平台是全局配置基线，只维护入口；误建的入口可单独删除，不影响所属平台。

入口字段与边界：

- `protocol` 已实现 `openai_compatible`（DeepSeek、火山方舟、**千帆 ERNIE 对话模型**等）、`yuanbao_search`（腾讯云元宝 SearchPro）、`doubao_search`（火山方舟 Responses + `web_search`）、`deepseek_web_search`（DeepSeek Responses 服务端联网工具）和 `wenxin_search`（千帆 AI 搜索旧产品，留档停用）；`deepseek_websearch`（8099 网页桥）已于 2026-11-17 整体摘除，枚举、适配器、采集桥脚本与库约束取值范围均不再包含该值；`custom` 入口保存后仍返回 `access_blocked`，等对应适配器开发。
- `credential_ref` **只存环境变量名**（如 `DEEPSEEK_API_KEY`、`YUANBAO_SECRET_ID`），不接收、不回显 API Key 明文；响应只返回 `credential_configured` 布尔值。变量名必须在白名单内（以 `_API_KEY` / `_SECRET_KEY` / `_SECRET_ID` / `_ACCESS_KEY` / `_TOKEN` 结尾），防止用 `PATH`、`DATABASE_URL` 等变量名越权读环境。元宝还需进程内 `YUANBAO_SECRET_KEY`，两者都读到才算 configured。
- 启用 `openai_compatible` 入口必须填写 `entry_url` 和 `model_name`；文心一言填 `https://qianfan.baidubce.com/v2` + `ernie-5.1`，入口 `supports_search=true` 时适配器请求体加 `web_search:{"enable":true}`；启用 `yuanbao_search` 入口必须填写 `entry_url` 和 `credential_ref`（`model_name` 可写 `yuanbao-search`）；启用 `doubao_search` 入口必须填写 `model_name`（方舟模型 ID），`credential_ref` 缺省按 `ARK_API_KEY` 读、`entry_url` 留空走默认方舟 Responses 地址；启用 `wenxin_search` 入口 `credential_ref` 缺省按 `QIANFAN_API_KEY` 读、`entry_url` 留空走默认千帆地址；`deepseek_web_search` 入口 `credential_ref` 缺省按 `DEEPSEEK_API_KEY` 读、`model_name` 留空按 `deepseek-flash`、`entry_url` 留空走默认 `https://api.deepseek.com/responses`；以上协议的 `entry_type` 都必须是 `api`。
- 统计口径分组：`GET /api/v1/projects/{project_id}/stats/overview-by-answer-kind` 按 `monitoring_samples.answer_kind` 返回两组总览（`answer` / `search_result`），`NULL` 归入 `answer` 兜底；两组各自独立分母，不提供合并后的总提及率，避免生成回答与检索结果混算。
- `yuanbao_search` 走 `wsa.tencentcloudapi.com` 的 `SearchPro`，TC3-HMAC-SHA256 签名，返回检索结果摘要而非对话生成答案；样本以 `engine_model=yuanbao-search` 标识，口径写“元宝搜索可见性”。
- `doubao_search` 走方舟 `POST /api/v3/responses`：`tools:[{"type":"web_search"}]`（默认不限定 `sources`；带 `sources:["doubao"]` 会 403，见测试报告 15.58），非流式；回答取 `output[]` 中 `message` 的 `output_text`，引用取 `content[].annotations` 的 `url_citation`（`title/url/site_name/publish_time/summary`）并按 URL 去重；`raw_response.answer_kind="answer"`、记 `search_queries` 与 `usage`（input/output/total tokens），`engine_model` 用响应里的实际模型；必须配置 `model_name`（方舟模型 ID），`entry_url` 留空走默认地址，`credential_ref` 缺省按 `ARK_API_KEY` 读。
- **文心一言（ERNIE 对话模型）**走 `openai_compatible`：`POST https://qianfan.baidubce.com/v2/chat/completions`，Bearer 鉴权，body `{model:"ernie-5.1", messages:[...], web_search:{"enable":true}}`；返回 `choices[0].message.content` 生成回答，`answer_kind="answer"`、`engine_model` 用响应里的实际模型。`web_search` 字段是对象，传 bool 会 400；`enable_search` / `disable_search` / 外层 `enable_citation` 在该 v2 对话接口不触发检索。当前响应没有结构化 `search_info` / `url_citation`，引用统计按 0，不伪造。
- `wenxin_search` 走千帆 AI 搜索旧产品 `POST https://qianfan.baidubce.com/v2/ai_search/web_search`，Bearer 鉴权，请求体 `{"messages":[{"role":"user","content":...}]}`；返回 `references[]`（兼容对象 `title/url/snippet/date/website` 与纯 URL 字符串两种元素），按 URL 去重写 citations，`answer_kind="search_result"`、`engine_model=wenxin-search`；`credential_ref` 缺省按 `QIANFAN_API_KEY` 读，`entry_url` 留空走默认地址。该协议 2026-11-17 已停用，只保留代码与库约束兼容，不再作为文心主路径。
- `deepseek_web_search` 走 DeepSeek `POST https://api.deepseek.com/responses`，Bearer 鉴权，body `{model, tools:[{"type":"deepseek_web_search"}], input:"<问题>", stream:false}`，模型自行决定搜索/打开网页；回答取 `output[]` 中 `message` 的 `output_text`，引用取 `content[].annotations` 的 `url_citation`（`url/title`）并按 URL 去重，检索动作从 `web_search_call.action` 抽成 `search_actions`（`queries`/`url`）；`raw_response.answer_kind="answer"`、记 `usage`（含 `server_tool_use`），`engine_model` 用响应里的实际模型（默认 `deepseek-flash`）；`deepseek_search`（纯检索结果）已于 2026-11-17 永久删除，DeepSeek 只保留这一条主路径。
- `test-connection` 只发固定短探针，不创建监测样本、不保存回答正文；成功回写 `last_verified_at` 并写审计 `engine.entry.test`，失败返回 `success=false` + `error_code`（不吞成 500）。
- `verify` 仅允许 `web_user` / `app_search` 入口，用于没有连通性测试的网页端和应用内搜索入口；`verified_at` 不传默认当前 UTC，`note` 追加到 `access_note`，写审计 `engine.entry.manual_verify`。`api` 入口调用返回 400 `manual_verify_not_allowed`，必须走 `test-connection`。系统管理员持 `engine.manage` 可核验；任一项目内角色持窄权限 `engine.verify` 也可核验，但不因此获得目录增改权限。
- 测试连接错误码：`unsupported_protocol`、`entry_url_missing`、`model_name_missing`、`credential_ref_missing`、`credential_missing`、`auth_failed`、`endpoint_not_found`、`rate_limited`、`timeout`、`unreachable`、`upstream_error`、`http_error`。

### 2.5 监测

| 方法 | 路径 | 说明 | 权限 |
| --- | --- | --- | --- |
| GET | /api/v1/projects/{project_id}/monitoring/rounds | 轮次列表 | `monitoring.read` |
| POST | /api/v1/projects/{project_id}/monitoring/rounds | 新建轮次（基线 `is_baseline=true`） | `monitoring.execute` |
| POST | /api/v1/projects/{project_id}/monitoring/rounds/{round_id}/tasks/batch | 按 6 题 × 4 引擎批量生成基线任务（幂等） | `monitoring.execute` |
| GET | /api/v1/projects/{project_id}/monitoring/tasks | 任务列表（轮次/引擎/状态过滤） | 项目成员 |
| POST | /api/v1/projects/{project_id}/monitoring/tasks/{task_id}/execute | 触发采样（202） | editor+ |
| GET | /api/v1/projects/{project_id}/monitoring/diagnostics | 内部排障：失败样本、失败码、重试次数、耗时、token、trace | `monitoring.read` |
| GET | /api/v1/projects/{project_id}/monitoring/traces/{trace_id} | 跨实体链路：轮次 → 任务 → 样本 → 引用 → 内容版本 → 发布任务；缺失返回 `found=false` | `monitoring.read` |
| GET | /api/v1/projects/{project_id}/monitoring/samples | 样本列表（状态过滤、分页） | `monitoring.read` |
| POST | /api/v1/projects/{project_id}/monitoring/samples/{sample_id}/manual-review | 人工复核归入 hit/miss | reviewer |
| POST | /api/v1/projects/{project_id}/monitoring/samples/{sample_id}/replay | 用留存请求体新建一次 attempt 回放；不改原任务状态 | `monitoring.execute` |
| POST | /api/v1/projects/{project_id}/monitoring/samples/{sample_id}/reanalyze | 重新分析留存原始回答：不调外部引擎、不新增样本，递增 `analysis_version` | `monitoring.execute` |
| POST | /api/v1/projects/{project_id}/monitoring/samples/{sample_id}/resample | 重复采样：新建下一个逻辑 `sampling_no` 的任务并真正请求引擎；失败只记失败样本 | `monitoring.execute` |
| POST | /api/v1/projects/{project_id}/monitoring/samples/{sample_id}/replay | 兼容旧路径（已弃用）；语义等同 `/resample`，不再在原任务上叠加 attempt | `monitoring.execute` |
| GET | /api/v1/projects/{project_id}/monitoring/samples/{sample_id} | 答案详情：题目原文/`QuestionVersion`/类型/意图、轮次与 `round_snapshot_hash`、引擎/入口类型/模型/搜索模式/会话 ID 与会话模式、状态/失败码/采样时间、`raw_answer` 与 `raw_response`、品牌命中偏移证据、竞品提及与列表位次、引用（含标题/顺序/来源类别/页面类型/复核状态）、证据文件与 `analysis_version`/`matcher_version` | `monitoring.read` |

手动触发限制：仅 `pending` 任务可触发；同一任务并发触发用数据库原子条件更新拒绝（返回 `409 task_rejected`）；按项目限并发；每次触发写审计。

实现边界（2026-11-12，C 侧现状）：本端点当前只做 `pending → running` 原子抢占，**不写 outbox、不投递 Worker**；真正的采样执行/投递由 B4 的采样执行器或 Worker 补。若后续把本端点改成“触发即投递”，必须在同一事务写 `monitoring.task.execute` 事件并确保有消费者，否则任务会停在 `running`。这一条同时作为 B4 对外口径，避免把“已抢占”误写成“已执行”。

批量生成行为（`POST .../monitoring/rounds/{round_id}/tasks/batch`，B4 已实现）：

- **权限**：`GET /monitoring/rounds` 用 `monitoring.read`；`POST /monitoring/rounds` 与 `POST .../tasks/batch` 用 `monitoring.execute`。本期不新增能力码。
- **只选 `status=active` 且当前版本存在的题目**：`draft`、`archived` 不进入正式任务；`active` 但 `current_version_no` 无对应版本时整批阻断，`skipped_reason="question_version_missing"`。
- 响应必须显式返回：`requested_question_count`（本项目题目总数）、`eligible_question_count`（active 且有当前版本数）、`inactive_question_count`、`inactive_question_ids`（按 `code` 排序）、`inactive_questions`（`id/code/title/status`）、`question_version_missing_count`、`question_version_missing_question_ids`、`engine_count`、`expected_task_count`、`eligible_expected_task_count`、`created_task_count`、`reused_task_count`、`generated_task_count`、`complete`、`skipped_reason`。
- 计数口径：`expected_task_count=requested_question_count×engine_count`；`eligible_expected_task_count=eligible_question_count×engine_count`；`generated_task_count=created_task_count+reused_task_count`。
- `complete = generated==expected AND eligible==requested AND engine_count==expected_engine_count AND question_version_missing_count==0 AND skipped_reason IS NULL`。`expected_engine_count` 默认 4；部分基线脚本传选中平台数（如 `--only deepseek` 传 1），避免 1/4 平台被误标不完整。
- 部分未激活采用“部分生成 + 不完整”：生成 `eligible×engine_count` 条，`complete=false`、`skipped_reason="inactive_questions"`；全量未激活生成 0 条，同样返回结构化字段。本期统一用 `200 + complete=false`，不返回 409；409 只作为错误信封扩展后的目标态，不进入本期验收。
- 引擎只取当前项目内启用引擎 + 至少一个启用入口，每个引擎只取一个有效入口；`engine_count<expected_engine_count` 时 `complete=false`、`skipped_reason="engine_entries_insufficient"`；`engine_count=0` 不生成任务。
- 幂等键 `round_id + question_version_id + engine_entry_id + sampling_no`；基线 `sampling_no=1`，请求体不传采样序号。首次 `created=24,reused=0,generated=24`；重放 `created=0,reused=24,generated=24,complete=true`。并发重放用轮次行锁或 `INSERT ... ON CONFLICT DO NOTHING` + `RETURNING`，第二次全部 reused。
- 批量生成写审计 `monitoring.tasks_batch_generate`，payload 含 `round_id` 与上述计数/原因字段。
- 并发：批量生成锁 `monitoring_rounds` 轮次行；仅 `POST /rounds` 建基线时锁 `projects` 行。非基线并发建轮次撞 `seq` 唯一约束本期不做 seq+1 重试，前端需防重复点击。
- 状态机：批量只创建 `pending` 任务；B4 采样器按 `pending→running→failed` 走 `ensure_task_transition()`，样本按 `pending→failed` 走 `ensure_sample_transition()`，不把 pending 任务直接改成 failed。
- `draft` 预览/测试任务走独立流程（单独 `dry_run` 或独立端点），不复用正式生成，不写入正式任务表。

#### 2.5.1 引擎网关与 trace（2026-11-16 v1）

- `MonitoringTask.trace_id` 在批量建任务时生成（32 位 hex）；老任务在首次执行时补；样本和引用沿任务继承，用于串“轮次 → 任务 → 样本 → 引用”。
- `MonitoringSample` 新增 `request_payload`（只存 model/messages/参数，不存 `Authorization`）、`latency_ms`、`prompt_tokens`、`completion_tokens`、`total_tokens`、`estimated_cost_cny`、`gateway_version`；`raw_response` 继续存完整响应。
- **逐题会话隔离（P60）**：`MonitoringSample` 新增 `conversation_id`（项目内唯一，32 位 hex）与 `conversation_mode`（`stateless`=API 每次独立请求 / `fresh`=网页端新开对话 / `manual`=人工录入）。样本抢占时生成新 ID，不复用上一题会话；项目内唯一约束阻止同题重试或跨题误用同一会话键；`sampling_mode` 继续记录 `search_on/search_off` 联网模式。列表、答案详情与手测录入响应均返回这两个字段。
- 网关 v1 只做进程内统一结果与留痕：重试仍由 Celery 任务级控制，限流仍按引擎每分钟 6 次，超时由适配器 `httpx` 控制；不引入 litellm/Langfuse，不伪造 fallback（当前只有 DeepSeek 单入口可验证）。
- 费用：`estimated_cost_cny` 预留 `Numeric(14,6)`；只有配置 `DEEPSEEK_INPUT_PRICE_CNY_PER_MILLION` / `DEEPSEEK_OUTPUT_PRICE_CNY_PER_MILLION` 才按 token 估算，未配置保持空，不编造价格。
- 回放：`POST /samples/{sample_id}/replay` 用该样本留存请求体新建一次 `attempt`；原任务状态不改，回放样本独立落 hit/miss/failed；旧样本没有 `request_payload` 时退回按当前题目重建请求，并在响应 `used_stored_request=false` 明示。
- `GET /samples/{sample_id}`、样本列表、任务列表返回 trace/耗时/token/费用/请求体字段；回放写审计 `monitoring.sample.replay`。
- 内部排障：`GET /monitoring/diagnostics?status=failed&failure_code=timeout` 聚合失败样本的任务状态、引擎/问题、`attempt_no`、`retry_count=attempt_no-1`、耗时、token、`trace_id`；默认只查 `failed`，权限 `monitoring.read`。
- 跨实体 trace：`GET /monitoring/traces/{trace_id}` 以任务/样本/引用的 `trace_id` 为准；内容版本只纳入真正引用本 trace 引用的版本；发布任务按 `trace_id` 或版本关联；没有节点返回 `found=false`，不补假数据。


### 2.6 证据与渠道

| 方法 | 路径 | 说明 | 权限 |
| --- | --- | --- | --- |
| GET | /api/v1/projects/{project_id}/citations | 引用列表 | `monitoring.read` |
| PATCH | /api/v1/projects/{project_id}/citations/{citation_id} | 确认或驳回归属 | `evidence.review` |
| GET | /api/v1/projects/{project_id}/citations/unknown-domains | 待归类队列 | `channel.read` |
| GET | /api/v1/projects/{project_id}/evidence/{evidence_id}/download | 下载证据文件（已实现，带授权与路径检查） | 项目成员 |
| GET / POST | /api/v1/projects/{project_id}/channels | 渠道台账；POST 新增渠道，`code` 项目内唯一 | `channel.read` / `channel.write` |
| GET | /api/v1/projects/{project_id}/channels/{channel_id} | 渠道明细（引用样本摘要、去重页面、引擎/问题编码） | 项目成员（channel.read） |
| PATCH | /api/v1/projects/{project_id}/channels/{channel_id} | 局部更新分类、状态、主域名、负责人、备注、启停与别名；`code` 不改 | `channel.write` |
| GET | /api/v1/projects/{project_id}/channels/export | 导出 CSV（已实现，写审计；支持 `engine_id`、`question_id`、`start_date`、`end_date` 多维筛选；同步 ≤5000 行，超过转异步） | `export.data` |
| GET | /api/v1/projects/{project_id}/channels/anomalies | 渠道台账 / 发布任务 / 回执一致性异常清单（只读，不返回全部渠道正文） | `channel.read` |
| GET | /api/v1/projects/{project_id}/brand-profile | 品牌正式名、别名、唯一标识、自有域名与生效词表 | `monitoring.read` |
| PUT | /api/v1/projects/{project_id}/brand-profile | 整体替换品牌口径；别名与唯一标识重叠直接 400 | `brand.manage` |
| GET | /api/v1/projects/{project_id}/brand-profile/governance | P14 首月运营准备度：域名、品牌口径、素材数、渠道负责人覆盖率与缺口清单 | `monitoring.read` |

引用复核行为（B6）：

- `PATCH /citations/{id}` 只能把 `review_status` 改为 `manual_confirmed` / `manual_rejected`；`auto` 由系统回填，手动回写返回 400 `invalid_review_status`。
- `channel_id` / `competitor_id` 为部分更新：请求体显式出现才处理；传值须查 `Channel` / `Competitor` 且属于当前项目，否则 404 `resource_missing`（不暴露存在性）；显式 `null` 清空映射；不传保持原值。`raw_url` 不可经本接口修改。
- `review_note` 同为部分更新：显式传值（含 `null`）才覆盖，不传保留原备注。
- 归属改挂与复核结论写审计，payload 记录最终归属值。

导出行为：

- 不带筛选参数：导出本项目全部渠道台账，列 `code,name,category,status,primary_domain,owner_name,owner_contact`。
- 带任一筛选参数：按 `monitoring_citations → monitoring_samples → monitoring_tasks → ai_engine_entries → ai_engines / questions` 联表聚合，一个 `channel_id` 一行；渠道去重按 `channel_id`，页面数按 `normalized_url` 去重；列追加引用数、样本数、页面数、引擎/问题编码与采样时间范围。
- 审计 `filters` 必须记录实际筛选条件（`engine_id`、`question_id`、`start_date`、`end_date`），便于按同一条件复跑。

渠道明细行为：

- 返回渠道台账字段、`citation_count`、`sample_count`、`page_count`、去重 `page_urls`、`engine_codes`、`question_codes`、首末采样时间与逐条 `citations`；
- `citations` 每条含 `raw_url`、`normalized_url`、`domain`、`is_brand_related`、`review_status`、`sample_status`、`brand_mentioned`、`failure_code` 与 200 字回答摘要；完整回答仍留在样本表；
- 只读，不写审计；未知 `channel_id` 返回 404；不属于当前项目的渠道同样 404/403，不暴露存在性。

- `POST /channels` 请求体：`code`、`name`、`category`、`status`（默认 `candidate`）、`primary_domain`、`notes`、`aliases`、`is_active`；`code` 只允许小写字母、数字、连字符，项目内唯一；`aliases` 是旧域名列表；
- `PATCH /channels/{channel_id}` 只改传入字段，`code` 不可改；改名或换主域名时，旧名称落 `channel_aliases.alias_name`，旧主域名落 `channel_aliases.domain`，没有旧域名时旧名称追加到备注；
- 域名同时被其他渠道的主域名或别名占用时返回 400 `channel_domain_conflict`；跨项目访问返回 403，不暴露资源是否存在；
- 写操作均写 `audit_logs action=channel.create / channel.update`，与业务写入同一事务。
- 状态自动推进口径：发布任务回执结案（或 `verify` 确认 `published`）时，对应渠道 `candidate/review_pending → published`；监测引用域名命中渠道 `primary_domain` 或 `channel_aliases.domain`（精确或子域后缀上溯，如 `zhuanlan.zhihu.com → zhihu.com`）时，`candidate/review_pending → observed`。两种推进都只升不降：`published` 的渠道被引用不改为 `observed`，`observed` 的渠道发布结案不改为 `published`。引用命中渠道域名只用于观测状态，不改变渠道效果归因（`channel_citations` 仍只认发布回执 URL）。

渠道/发布异常（`GET /channels/anomalies`）：

- 返回 `generated_at`、`counts`（`total` / `high` / `warning`）与 `anomalies` 数组；每条含 `code`、`severity`、渠道台账字段、`task_status`、`receipt_id`、`published_url`、`message`、`recommended_action`。
- 检查项：回执存在但任务非 `published`（`receipt_status_mismatch`）；任务 `published` 但无回执（`published_task_missing_receipt`）；任务 `published` 有回执但渠道状态非 `published`（`channel_status_mismatch`）；任务 `unknown`（`publish_task_unknown`）；渠道标 `published` 但无任何回执（`published_channel_without_receipt`）；同一任务多条回执（`duplicate_receipts`）。
- 只读，不修改业务数据，不写审计；前端渠道台账顶部展示异常条数与逐条处理建议，不替代发布任务/回执的正式处理。

### 2.7 内容与审核

| 方法 | 路径 | 说明 | 权限 |
| --- | --- | --- | --- |
| POST | /api/v1/projects/{project_id}/contents | 新建母稿 / 渠道稿 | `content.write` |
| POST | /api/v1/projects/{project_id}/contents/{item_id}/versions | 追加版本（服务端算 hash） | editor+ |
| GET | /api/v1/projects/{project_id}/content-versions | 待审版本列表（可按状态过滤） | `content.read` |
| PATCH | /api/v1/projects/{project_id}/content-versions/{version_id}/body | 仅草稿可改正文 | `content.write` |
| POST | /api/v1/projects/{project_id}/content-versions/{version_id}/submit | 提交审核 | `content.write` |
| GET | /api/v1/projects/{project_id}/content-versions/{version_id}/reviews | 审批历史 | `content.read` |
| POST | /api/v1/projects/{project_id}/content-versions/{version_id}/review | 通过 / 驳回 + 意见 | `content.review` |
| GET | /api/v1/projects/{project_id}/content-versions/{version_id}/export | 交付包：标题、markdown、html、摘要、canonical 建议、Article JSON-LD、粘贴清单（只读，不生成页面、不写 `public_pages`） | `content.read` |
| GET / POST / PATCH | /api/v1/projects/{project_id}/plans | 运营计划与排期；PATCH 局部更新计划字段与状态 | `content.read` / `content.write` |
| GET / POST / PATCH / POST review | /api/v1/projects/{project_id}/media-quotes | 报价与审批；创建/改价 `content.write`，审批 `/media-quotes/{quote_id}/review` 用 `content.review` | 提交 `content.write` / 审批 `content.review` |
| GET / POST | /api/v1/projects/{project_id}/budget-approvals | 四类预算申请列表（`status` / `category` 过滤）与提交；`category` 取 `development_hours` / `content_production` / `media_placement` / `monitoring_service` | `budget.read` / `budget.write` |
| POST | /api/v1/projects/{project_id}/budget-approvals/{budget_id}/review | 通过 / 驳回；仅 `pending` 可审批，驳回必须写原因 | `budget.approve` |
| GET / POST / PATCH | /api/v1/projects/{project_id}/pages | 公开站事实页登记；PATCH 更新标题、URL、canonical 与发布状态 | `content.read` / `content.write` |

只有草稿版本正文可编辑；提交后正文锁定。修改已提交内容须创建新版本，审核记录保留提交时的 `content_hash` 快照。

计划/报价/页面行为（2026-11-13，C 接后端）：

- `plans`：`channel_id`、`content_item_id`、`site_page_id`、`owner_id` 必须属于当前项目；`owner_id` 必须是有效项目成员，创建时未传默认当前登录人；`PATCH` 不传字段保持原值，显式 `null` 清空可空关联；状态值受模型 CHECK 约束。
- `media-quotes`：创建固定 `pending`；`PATCH` 仅待审批可改，已审批/驳回一律 409 `quote_status_conflict`；审批 `POST /{quote_id}/review` 只接受 `approved` / `rejected`，落 `approved_by` / `approved_at`；预算 = `unit_price × quantity`，列表返回 `budget`。
- `budget-approvals`：项目级四类成本申请；`amount > 0`，`quantity` / `unit_price` 可选且大于 0/不小于 0；同时给 `quantity` 与 `unit_price` 时 `amount` 必须等于二者乘积（服务端 422）。创建固定 `pending`；仅 `pending` 可审批，驳回必须写 `decision_note`；已审批/驳回再次审批返回 400。提交人不能审批自己提交的预算申请（`review_self_not_allowed`，400），与内容版本 / 媒体报价职责分离口径一致。项目内若没有除提交人外的 `budget.approve` 有效持有人（项目成员与账号均有效），提交前直接返回 400 `budget_approver_required`，避免单据永久 pending；需要先添加审核账号（`reviewer` 或另一名 `project_admin`）。创建写 `budget.create`，审批写 `budget.approve` / `budget.reject` 审计。该表与 `media_quotes` 分工：报价只管媒体单价与总预算，四类预算审批管开发工时、内容制作、媒体投放、监测服务的成本申请。
- `pages`：`slug` 项目内唯一且创建后不可改，重复返回 409 `page_slug_conflict`；`publish_status` 改 `published` 时刷新 `last_published_at`；本接口只做登记，不生成页面、不发布站点。公开页由公司官网 `https://www.gdccai.com` 渲染，本表登记其真实 URL 供 `content_plans.site_page_id` 关联与 `citations` 归因（公开站已于 2026-11-17 下线，见 `docs/公开站下线与内容登记口径-2026-11-17.md`）。
- 三组写操作均写 `plan.create/update`、`quote.create/update/review`、`page.create/update` 审计，与业务写入同一事务；跨项目单条资源返回 404 `plan_missing` / `quote_missing` / `page_missing`，不暴露存在性。

### 2.8 发布

| 方法 | 路径 | 说明 | 权限 |
| --- | --- | --- | --- |
| POST | /api/v1/projects/{project_id}/publish/accounts | 登记发布账号（只存账号名与凭证引用） | `publish.execute` |
| GET | /api/v1/projects/{project_id}/publish/accounts | 发布账号只读列表（`credential_ref` 只存引用） | `publish.read` |
| GET / POST | /api/v1/projects/{project_id}/publish/tasks | 发布任务列表 / 建发布任务 | `publish.read` / `publish.execute` |
| POST | /api/v1/projects/{project_id}/publish/tasks/{task_id}/attempts | 记录一次尝试 | `publish.execute` |
| POST | /api/v1/projects/{project_id}/publish/tasks/{task_id}/receipts | 回填真实 URL 结案 | `publish.execute` |
| POST | /api/v1/projects/{project_id}/publish/tasks/{task_id}/verify | 回执不明时核实 | `publish.execute` |

发布侧 trace：

- `PublishTask.trace_id` 在内容版本引用的 `monitoring_citations` 中继承：去重后只有一个 trace 才写入；多个 trace 视为归属歧义，保持 `null`，不随机挑一条。
- `POST /publish/tasks` 与 `GET /publish/tasks` 返回 `trace_id`；幂等复用任务时返回原任务的 trace。
- 内容版本未关联监测引用时 trace 为空，属于正常情况；不拿项目/轮次 trace 冒充发布 trace。

状态机约束（必须落到接口）：

- 仅 `pending` / `needs_review` 允许新增 `attempt`；
- `publishing` 期间禁止重复提交；
- `unknown` 必须先 `verify`，核实为未发出才可回到 `pending` 重试，核实为已发出则补回执结案；
- `published` 终态，不得再新增 attempt。

建任务约束：

- `task_key` 由调用方生成且必填，缺失/空串/非法字符返回 422；≤64，只允许 `A-Z a-z 0-9 . _ : -`，不 trim、不做大小写归一；
- 最终幂等键 = `SHA-256(account_id:channel_id:version_id:task_key)`；重复提交返回已有任务，不重复插入；
- 账号、渠道、版本必须同项目；账号必须绑定该渠道且启用；内容必须是该渠道的渠道稿（`ContentKind.CHANNEL`）且为当前版本，版本状态 `approved`；
- 建任务、回执、verify 三处都比对最近一次审批通过的 `content_hash_snapshot`；不一致时版本回 `pending_review` 并返回 409，不继续写发布状态。

### 2.9 看板与线索

| 方法 | 路径 | 说明 | 权限 |
| --- | --- | --- | --- |
| GET | /api/v1/projects/{project_id}/stats/geo | 内部 GEO 验收指标：有效回答、Mention rate、Citation share、SOV、情感、品牌位次、Prompt coverage、Freshness、Failure rate；空分母返回 `null` 并带 `statement`/`definitions` | `stats.read` |
| GET | /api/v1/projects/{project_id}/stats/overview | 品牌提及率、引用率、样本完成率 | `stats.read` |
| GET | /api/v1/projects/{project_id}/stats/by-engine | 分引擎对比 | `stats.read` |
| GET | /api/v1/projects/{project_id}/stats/engine-health | 入口级真实可用性矩阵：配置状态、失败率、平均延迟、token、估算费用、最近采样 | `stats.read` |
| GET | /api/v1/projects/{project_id}/stats/by-question | 分问题对比（品牌题/通用题分开） | `stats.read` |
| GET | /api/v1/projects/{project_id}/stats/sources | 信源分布：按 `domain` 聚合 `citations/samples/brand_related/channel_citations/last_sampled_at`；`channel_citations` 只统计命中发布回执 URL 的条数（渠道效果），其余是第三方信源，不进渠道台账；`limit` 1–200 默认 20，支持轮次/引擎/问题/时间过滤，只计有效样本 | `stats.read` |
| GET | /api/v1/projects/{project_id}/stats/trend | 最多 12 周的周趋势 | `stats.read` |
| GET | /api/v1/projects/{project_id}/stats/task-distribution | 各引擎任务占比 | `stats.read` |
| GET | /api/v1/projects/{project_id}/stats/monthly | 月度报告：任务完成率、回答表现、发布结案与线索漏斗；`month=YYYY-MM`，默认当前月 | `stats.read` |
| POST | /api/v1/projects/{project_id}/stats/monthly/snapshots?month=YYYY-MM | 冻结月报快照：报告原文、period_start/period_end、规则版本、线索可见范围与 hash 落库；同项目同月唯一 | `content.review` 或 `monitoring.execute` |
| GET | /api/v1/projects/{project_id}/stats/monthly/snapshots | 月报快照摘要列表，可按 month 过滤 | `stats.read` |
| GET | /api/v1/projects/{project_id}/stats/monthly/snapshots/{snapshot_id} | 月报快照详情，report 为冻结时原文 | `stats.read` |
| GET | /api/v1/projects/{project_id}/stats/export | 导出（审计 + 行数上限） | `export.data`（lead_ops 无此能力，不得放行） |
| GET / POST | /api/v1/projects/{project_id}/leads | 线索录入与列表（已实现；lead_ops 与 project_admin 可用，editor 无该能力） | `lead.read` / `lead.write` |

统计导出行为：

- `GET /stats/export` 支持 `round_id`、`engine_id`、`question_id`、`start_at`、`end_at`、`answer_kind`、`question_type`、`question_intent` 与看板相同的筛选参数；输出 CSV 列为 `answer_kind,record_type,code,name,question_type,question_intent,valid_answers,brand_mentioned_answers,brand_identified_answers,citation_answers,brand_mention_rate,brand_identified_rate,citation_rate,channel_count,page_count,failed_answers,no_answer_surface_answers,manual_review_answers,pending_or_running_answers`；`overview` 行单列失败/无答案界面/待复核/未完成样本数，`engine` / `question` 行留空；
- 题目分区与意图：`stats/overview`、`overview-by-answer-kind`、`by-engine`、`by-entry`、`by-question`、`geo`、`sources`、`export` 均支持 `question_type=brand|general` 与 `question_intent=discovery|comparison|use_case|how_to|pricing|enrollment|career|brand_navigation|other`。**自然发现率必须同时传 `question_type=general&question_intent=discovery`**；只传 `question_type=general` 是“通用题全类型对照”，会把 how_to / use_case / career / pricing 混入，不能称为自然发现率。`brand` 只回答“用户直接询问品牌时 AI 是否识别”，不进入自然发现分母。不传 `question_type` 保留旧的全量口径，仅用于兼容和排查，不作为对外核心指标。看板默认使用 `general + discovery`，并单独展示品牌题卡片。
- 引擎与入口：`by-engine` 是厂商/模型折叠视图，每行附 `entries` 入口明细；`by-entry` 是独立入口口径，同一引擎不同入口不合并，并按 `sampling_mode` 分开联网/非联网。前端分引擎页同时展示厂商汇总和入口级明细，入口类型至少区分 `api` / `web_user` / `app_user` / `app_search`，并显示 `provider` 与模型名。
- 口径提醒：`page_count` 是**引用口径**——只统计有效回答关联且 `review_status=manual_confirmed` 的引用，按 `normalized_url` 去重；**不是** `public_pages` 登记的公司站页面数。`channel_count` 同样只统计已人工复核引用上的 `channel_id` 去重，引用未回填渠道时为 0；两者都先经过同一审核后引用范围，与其他统计口径一致；
- 失败单列：`stats/overview` 的 `excluded` 返回 `failed / manual_review / no_answer_surface / pending_or_running`，并额外返回 `failure_breakdown`（按 `failure_code` 分组，未标原因归 `unknown`）。失败样本不进入 `valid_answers` 分母，也不与 hit/miss 混算；
- 行集固定为三段：`overview` 一行、`engine` 每平台一行、`question` 每题一行；三段全部调用 `services/stats.py` 的 `overview` / `by_engine` / `by_question`，导出层不写新 SQL；
- 写 `audit_logs action=export`，`export_type=stats`、`row_count`、`mode=sync`、`filters` 记录实际筛选值；同步导出超过 `export_sync_row_limit` 返回 400 `export_too_large`；
- 权限为 `export.data`，`lead_ops` 无该能力；viewer 可导出但必须留痕。

统计口径读 `metric_definitions` 当前生效版本；失败样本不计入分母；无样本返回 `null` 而非 0。

**月报快照与首月复盘（P05）**：`stats/monthly` 继续返回实时聚合；`POST stats/monthly/snapshots` 把当前报告冻结为 `monthly_report_snapshots` 一行，同一项目同一月份拒绝第二次冻结（409 `monthly_report_snapshot_exists`）。快照保存 `report` JSON、`period_start/period_end`、`rule_version`、`definitions`（matcher/classifier 版本与 `leads_included`）和 SHA-256 `snapshot_hash`，并写 `audit_logs action=stats.monthly_snapshot`。冻结后再有新样本或线索，历史快照不会重算；`lead.read` 缺失时线索段按权限裁剪，并在 `definitions.leads_included=false` 留痕。前端“历史快照”只读该表，不重新聚合。

**内容分发看板（P05）**：发布页的“分发看板”由已审批渠道稿与 `publish/tasks` 汇总，不改后端资源；任务数、已发布结案、覆盖渠道均来自真实发布任务。批量分发仍逐账号调用 `POST /publish/tasks`，共用同一 `task_key`，同一批次重复提交按 `task_key + account_id` 复用，不产生重复任务。发布任务列表响应补 `account_id`，用于将任务回连到渠道账号。

**线索归因字段（C 侧新增，2026-11-12）**：`POST /leads` 与 `GET /leads` 增加 `source_question_id`、`source_channel_id`、`source_engine_id`、`landing_url`、`utm_campaign`。`source_question_id` / `source_channel_id` 必须属于当前项目，跨项目引用返回 `404 resource_missing`；`source_engine_id` 必须是已存在引擎。历史 `lead_source` 保留兼容，新数据以三个外键为准。口径见 `docs/转化归因口径.md`。

**线索自报 AI 产品与有效性（2026-11-18）**：`POST /leads` 接受 `reported_ai_product`（自由文本，最长 64，不做固定枚举）与 `is_valid`（默认 `true`）；`GET /leads`、CSV 导出、BFF 快照均返回这两个字段。`PATCH /leads/{lead_id}` 允许更新 `is_valid` 与 `reported_ai_product`，仍不允许改归因字段。`is_valid=false` 表示无效/误留资，列表用红色 Badge 标记，不改变线索是否入库。

### 2.9.1 FAQ、素材、线索跟进与发布入口（2026-11-16）

| 方法 | 路径 | 说明 | 权限 |
| --- | --- | --- | --- |
| GET / POST | /api/v1/projects/{project_id}/faqs | FAQ 列表与新增；状态 `draft/published/unpublished`，支持 `status` / `category` 筛选与分页；`deleted=true` 只看已删除，默认排除 | `content.read` / `content.write` |
| GET | /api/v1/projects/{project_id}/faqs/categories | 项目内未删除 FAQ 的去重分类列表，供筛选下拉 | `content.read` |
| PATCH | /api/v1/projects/{project_id}/faqs/{faq_id} | 局部更新问题、答案、分类、状态、排序；写 `faq.update` 审计；已删除条目拒绝更新 | `content.write` |
| DELETE | /api/v1/projects/{project_id}/faqs/{faq_id} | 软删：写 `deleted_at / deleted_by` 并置 `unpublished`，写 `faq.delete` 审计；公开接口随即不再返回 | `content.write` |
| POST | /api/v1/projects/{project_id}/faqs/{faq_id}/restore | 恢复已删除 FAQ：清空删除标记并回到 `draft`，写 `faq.restore` 审计 | `content.write` |
| GET | /api/v1/public/projects/{project_code}/faqs | 公开只读，仅返回 `published`，无需登录 | 无 |
| GET | /api/v1/projects/{project_id}/materials | 素材列表，支持 `category=image/document/case` | `content.read` |
| POST | /api/v1/projects/{project_id}/materials | multipart 上传：`title`、`category`、`description?`、`file` | `content.write` |
| PATCH | /api/v1/projects/{project_id}/materials/{material_id} | 更新标题、分类、说明 | `content.write` |
| GET | /api/v1/projects/{project_id}/materials/{material_id}/download | 下载素材文件，路径校验后写 `material.download` 审计 | `content.read` |
| GET | /api/v1/projects/{project_id}/leads/export | 线索 CSV，写 `action=export, export_type=leads` 审计；超过同步上限返回 400 | `export.data` |
| PATCH | /api/v1/projects/{project_id}/leads/{lead_id} | 更新 `enrollment_status`、`note`、`owner_id`，不改归因字段 | `lead.write` |

口径：

- 素材落 `evidence_root/materials/{project_id}/`，`storage_key` 由服务端生成；单文件上限 20MB，仅允许图片、PDF、Office 文档、文本、CSV、Markdown、zip；不接受前端传路径。
- `GET /projects` 现在返回 `owner_name`、`updated_at`、`channel_count`、`task_count`，前端不再用 `—` / `0` 占位；`owner_name` 取项目内最早的项目管理员。
- `GET /leads` 现在返回 `note`、`owner_id`、`owner_name`、`created_at`、`updated_at`；线索导出列头见 `LEAD_EXPORT_COLUMNS`。
- 渠道新增 `publish_url`、`login_url` 两个可空字段（http/https 绝对地址），用于手动发布工作台“打开发布后台/登录页”；没有配置时前端回退到 `https://{primary_domain}`。
- 发布任务详情不新增接口：前端用已有 `GET /content-versions/{version_id}` 取正文，配合渠道 `publish_url` 完成“预览 → 复制正文 → 打开发布后台 → 回填回执”。当前仍是 manual 台账，不调用平台 API。

### 2.10 已实现端点（本分支 `docs/openapi.json` 实测 96 条路径 / 121 个操作 / 278 个 schema）

| 端点 | 能力码 |
| --- | --- |
| `GET /api/v1/projects` | 登录用户（系统管理员看全部，其他人看已加入项目） |
| `POST /api/v1/projects` | `project.create`（系统级） |
| `GET /api/v1/engines` | 登录用户 |
| `POST /api/v1/engines` | `engine.manage`（系统级） |
| `GET /api/v1/engines/{engine_id}/entries` | 登录用户 |
| `POST /api/v1/engines/{engine_id}/entries` | `engine.manage`（系统级） |
| `PATCH /api/v1/engines/{engine_id}/entries/{entry_id}` | `engine.manage`（系统级） |
| `POST /api/v1/engines/{engine_id}/entries/{entry_id}/verify` | `engine.manage`（系统级）或项目级 `engine.verify` |
| `POST /api/v1/engines/{engine_id}/entries/{entry_id}/test-connection` | `engine.manage`（系统级） |
| `GET/POST/PATCH /api/v1/projects/{project_id}/members` | `project.member.manage` |
| `GET/POST /api/v1/projects/{project_id}/leads` | `lead.read` / `lead.write` |
| `GET/POST /api/v1/projects/{project_id}/monitoring/rounds` | `monitoring.read` / `monitoring.execute` |
| `POST /api/v1/projects/{project_id}/monitoring/rounds/{round_id}/tasks/batch` | `monitoring.execute` |
| `GET /api/v1/projects/{project_id}/monitoring/tasks` | `monitoring.read` |
| `POST /api/v1/projects/{project_id}/monitoring/tasks/{task_id}/execute` | `monitoring.execute` |
| `GET /api/v1/projects/{project_id}/stats/geo` | `stats.read` |
| `GET /api/v1/projects/{project_id}/evidence/{evidence_id}/download` | `evidence.read` |
| `POST /api/v1/projects/{project_id}/contents` | `content.write` |
| `POST /api/v1/projects/{project_id}/contents/{item_id}/versions` | `content.write` |
| `PATCH /api/v1/projects/{project_id}/content-versions/{version_id}/body` | `content.write`（reviewer 无此能力，改正文 403） |
| `POST /api/v1/projects/{project_id}/content-versions/{version_id}/review` | `content.review` |
| `POST /api/v1/auth/login`、`GET /api/v1/auth/me`、`POST /api/v1/auth/password` | 登录公开；其余需登录 |
| `GET /api/v1/projects/{project_id}/monitoring/samples`、`GET /samples/{sample_id}` | `monitoring.read` |
| `GET /api/v1/projects/{project_id}/monitoring/diagnostics` | `monitoring.read` |
| `GET /api/v1/projects/{project_id}/monitoring/traces/{trace_id}` | `monitoring.read` |
| `POST /api/v1/projects/{project_id}/monitoring/samples/{sample_id}/manual-review` | `evidence.review` |
| `POST /api/v1/projects/{project_id}/monitoring/samples/{sample_id}/replay` | `monitoring.execute` |
| `GET /api/v1/projects/{project_id}/citations` | `monitoring.read` |
| `GET /api/v1/projects/{project_id}/citations/unknown-domains` | `channel.read`（按 C 拍板复用渠道读能力，不新增编辑者读码） |
| `PATCH /api/v1/projects/{project_id}/citations/{citation_id}` | `evidence.review` |
| `GET /api/v1/projects/{project_id}/content-versions`、`GET /content-versions/{version_id}/reviews` | `content.read` |
| `POST /api/v1/projects/{project_id}/content-versions/{version_id}/submit` | `content.write` |
| `GET /api/v1/projects/{project_id}/stats/overview`、`by-engine`、`by-question`、`trend`、`task-distribution`、`export` | `stats.read` / 导出 `export.data` |
| `GET /api/v1/projects/{project_id}/audit-logs` | `audit.read` |
| `POST /api/v1/projects/{project_id}/publish/accounts` | `publish.execute` |
| `GET /api/v1/projects/{project_id}/publish/accounts` | `publish.read`（只读） |
| `GET /api/v1/projects/{project_id}/publish/tasks` | `publish.read` |
| `POST /api/v1/projects/{project_id}/publish/tasks` | `publish.execute` |
| `POST /api/v1/projects/{project_id}/publish/tasks/{task_id}/attempts` | `publish.execute` |
| `POST /api/v1/projects/{project_id}/publish/tasks/{task_id}/receipts` | `publish.execute` |
| `POST /api/v1/projects/{project_id}/publish/tasks/{task_id}/verify` | `publish.execute` |
| `GET / POST /api/v1/projects/{project_id}/channels` | `channel.read` / 新增 `channel.write` |
| `GET / PATCH /api/v1/projects/{project_id}/channels/{channel_id}` | `channel.read` / 更新 `channel.write` |
| `GET /api/v1/projects/{project_id}/channels/export` | `export.data`（写审计） |
| `GET /api/v1/projects/{project_id}/monitoring/samples/{sample_id}` | `monitoring.read` |
| `POST /api/v1/projects/{project_id}/monitoring/samples/{sample_id}/manual-review` | `evidence.review` |
| `POST /api/v1/projects/{project_id}/monitoring/samples/{sample_id}/replay` | `monitoring.execute` |
| `GET /api/v1/projects/{project_id}/citations` | `monitoring.read` |
| `PATCH /api/v1/projects/{project_id}/citations/{citation_id}` | `evidence.review` |
| `GET /api/v1/projects/{project_id}/citations/unknown-domains` | `channel.read` |
| `GET/POST/PATCH /api/v1/projects/{project_id}/plans` | `content.read` / `content.write` |
| `GET/POST/PATCH /api/v1/projects/{project_id}/media-quotes`、`POST /media-quotes/{quote_id}/review` | `content.read` / `content.write` / 审批 `content.review` |
| `POST /api/v1/projects/{project_id}/confirm` | `project.member.manage` |
| `GET/POST /api/v1/projects/{project_id}/budget-approvals`、`POST /budget-approvals/{budget_id}/review` | `budget.read` / `budget.write` / 审批 `budget.approve` |
| `GET/POST/PATCH /api/v1/projects/{project_id}/pages` | `content.read` / `content.write` |
| `GET /api/v1/system/audit-logs` | `is_system_admin=true`（不引入额外能力码） |
| `GET /api/v1/tasks/{task_id}` | 按任务所属项目重新解析授权 |
| `GET /health`、`/health/db`、`/health/redis`、`/health/worker`、`/health/queue` | 公开探活（不带 `/api/v1` 前缀）；后两条为 CR-002 新增（2026-11-11） |
| `GET /api/v1/projects/{project_id}/members/candidates` | `project.member.manage`（成员邀请候选：全局用户按邮箱/姓名过滤，排除已在项目内的人） |
| `GET/POST /api/v1/projects/{project_id}/competitors`、`PATCH /competitors/{competitor_id}` | `monitoring.read` / `competitor.write` |
| `GET/POST /api/v1/projects/{project_id}/metric-definitions`、`PATCH /metric-definitions/{metric_id}` | `stats.read` / `metric.manage`（口径版本化，统计读当前生效版本） |
| `GET /api/v1/projects/{project_id}/content-versions/{version_id}/export` | `content.read`（导出内容包：正文、渠道、计划与素材引用） |

题库、关键词、计划、报价、公开站页面登记、项目级审计与系统级审计查询均已实现；B7 渠道写、B8 统计导出、B9 发布建任务/回执/verify 与 `publish/accounts` 同样已实现。公开页不归本系统渲染：对外页面在公司官网，GEO 侧只保留登记与匿名只读端点（`/api/v1/public/projects/{project_code}/faqs`）。公开站已于 2026-11-17 下线，见 `docs/公开站下线与内容登记口径-2026-11-17.md`。本分支增量及迁移评审状态见 `docs/契约变更单/CR-003-工作台后端联调接口.md`。

### 2.11 审计查询（项目级与系统级均已实现）

| 方法 | 路径 | 范围 | 权限 |
| --- | --- | --- | --- |
| GET | /api/v1/projects/{project_id}/audit-logs | 仅 `project_id = 本项目` | `audit.read`（project_admin / reviewer 持有） |
| GET | /api/v1/system/audit-logs | 仅 `project_id IS NULL` 的系统级记录 | 仅 `users.is_system_admin=true`，不引入额外能力码；不返回项目级记录 |

规则：两条链路互不越界——项目管理员看不到系统级审计，系统管理员也不能借系统查询读到某个项目的业务审计明细（要看必须按角色加入该项目）。`audit_logs.project_id` 实测可空，外键 `ON DELETE SET NULL`，因此删除项目后审计仍保留、但归属置空。

## 三、凭证管理

| 项 | 规定 |
| --- | --- |
| 存储位置 | 凭证明文存于部署环境的密钥管理（文件权限受控或 KMS），库里只存 `credential_ref` 引用 |
| 加密 | 静态加密（KMS 或受控密钥文件），传输走 HTTPS |
| 使用范围 | 仅 Worker 在执行发布时读取，**不返回给前端、不写日志、不进仓库、不进备份明文** |
| 轮换 | 支持按账号更新与吊销；更新后旧引用立即失效，历史发布记录保留引用快照 |
| 审计 | 凭证创建、轮换、吊销写 `audit_logs`，记录操作者与时间，不记录凭证明文 |

## 四、导出统一审计

- 所有导出端点（`channels/export`、`stats/export` 及后续新增）必须调用 `app/services/audit.py` 的 `record_export`，写 `action=export`，包含 `export_type`、`row_count`、`mode`、`filters`。
- 同步导出上限 `settings.export_sync_row_limit`（默认 5000 行），超过抛 `export_too_large`，必须转异步。
- 导出结果文件名带项目标识与批次/时间戳，异步导出结果设置过期时间与清理任务。

## 五、四个待评审点的结论（按审核意见定稿）

1. **令牌**：使用单 JWT（默认有效期 480 分钟），携带 `sub`、`type=access`、整数 `tv`；每次请求读取用户状态和 `users.token_version`。改密递增版本，旧令牌即时返回 `401 token_stale`；停用账号即时返回 `401 user_inactive`。缺少 `tv` 的旧令牌须重新登录。
2. **跨项目只读对比**：首期不支持，保持强隔离；将来若需要，只开放系统级聚合统计，不放项目明细串读。
3. **采样执行手动触发**：开放，但限制 `pending` 任务、幂等键、任务锁、项目级并发上限、操作审计；Worker 定时领取作为补充。
4. **导出**：小数据量同步 CSV（≤5000 行），大数据量异步；统一审计与限流。
