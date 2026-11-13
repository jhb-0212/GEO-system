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

错误码：`unauthorized`、`invalid_credentials`、`token_expired`、`token_invalid`、`token_stale`、`user_inactive`、`current_password_invalid`、`password_unchanged`、`system_admin_only`、`project_forbidden`、`insufficient_permission`、`path_escape`、`evidence_missing`、`export_too_large`、`task_rejected`、`validation_error`、`engine_missing`、`engine_entry_missing`、`engine_entry_exists`、`entry_url_missing`、`model_name_missing`、`protocol_entry_type_mismatch`。
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
| GET / POST | /api/v1/projects/{project_id}/members | 成员与授权（已实现） | `project.member.manage` |
| PATCH | /api/v1/projects/{project_id}/members/{member_id} | 改角色或停用（已实现，不得越级授予） | `project.member.manage` |

### 2.3 题库与关键词

| 方法 | 路径 | 说明 | 权限 |
| --- | --- | --- | --- |
| GET / POST | /api/v1/projects/{project_id}/questions | 列表 / 新建 | editor+ |
| PATCH | /api/v1/projects/{project_id}/questions/{question_id} | 状态、人群、意图、优先级 | editor+ |
| GET / POST | /api/v1/projects/{project_id}/questions/{question_id}/versions | 版本列表 / 追加版本 | editor+ |
| GET / POST | /api/v1/projects/{project_id}/keywords | 目标词 | editor+ |

改题目正文必须新开版本并同步 `current_version_no`，旧版本不可编辑。

### 2.4 AI 平台目录

| 方法 | 路径 | 说明 | 权限 |
| --- | --- | --- | --- |
| GET | /api/v1/engines | AI 平台列表（系统级） | 登录用户 |
| POST | /api/v1/engines | 新建平台 | `engine.manage` |
| GET | /api/v1/engines/{engine_id}/entries | 入口列表（含 `credential_configured`） | 登录用户 |
| POST | /api/v1/engines/{engine_id}/entries | 新建入口 | `engine.manage` |
| PATCH | /api/v1/engines/{engine_id}/entries/{entry_id} | 修改入口、模型、密钥引用、启停 | `engine.manage` |
| POST | /api/v1/engines/{engine_id}/entries/{entry_id}/test-connection | 测试连通性 | `engine.manage` |

入口字段与边界：

- `protocol` 已实现 `openai_compatible` 和 `yuanbao_search`（腾讯云元宝 SearchPro）；`custom` 入口保存后仍返回 `access_blocked`，等对应适配器开发。
- `credential_ref` **只存环境变量名**（如 `DEEPSEEK_API_KEY`、`YUANBAO_SECRET_ID`），不接收、不回显 API Key 明文；响应只返回 `credential_configured` 布尔值。元宝还需进程内 `YUANBAO_SECRET_KEY`，两者都读到才算 configured。
- 启用 `openai_compatible` 入口必须填写 `entry_url` 和 `model_name`；启用 `yuanbao_search` 入口必须填写 `entry_url` 和 `credential_ref`（`model_name` 可写 `yuanbao-search`）；两种协议的 `entry_type` 都必须是 `api`。
- `yuanbao_search` 走 `wsa.tencentcloudapi.com` 的 `SearchPro`，TC3-HMAC-SHA256 签名，返回检索结果摘要而非对话生成答案；样本以 `engine_model=yuanbao-search` 标识，口径写“元宝搜索可见性”。
- `test-connection` 只发固定短探针，不创建监测样本、不保存回答正文；成功回写 `last_verified_at` 并写审计 `engine.entry.test`，失败返回 `success=false` + `error_code`（不吞成 500）。
- 测试连接错误码：`unsupported_protocol`、`entry_url_missing`、`model_name_missing`、`credential_ref_missing`、`credential_missing`、`auth_failed`、`endpoint_not_found`、`rate_limited`、`timeout`、`unreachable`、`upstream_error`、`http_error`。

### 2.5 监测

| 方法 | 路径 | 说明 | 权限 |
| --- | --- | --- | --- |
| GET | /api/v1/projects/{project_id}/monitoring/rounds | 轮次列表 | `monitoring.read` |
| POST | /api/v1/projects/{project_id}/monitoring/rounds | 新建轮次（基线 `is_baseline=true`） | `monitoring.execute` |
| POST | /api/v1/projects/{project_id}/monitoring/rounds/{round_id}/tasks/batch | 按 6 题 × 4 引擎批量生成基线任务（幂等） | `monitoring.execute` |
| GET | /api/v1/projects/{project_id}/monitoring/tasks | 任务列表（轮次/引擎/状态过滤） | 项目成员 |
| POST | /api/v1/projects/{project_id}/monitoring/tasks/{task_id}/execute | 触发采样（202） | editor+ |
| GET | /api/v1/projects/{project_id}/monitoring/samples | 样本列表（状态过滤、分页） | `monitoring.read` |
| POST | /api/v1/projects/{project_id}/monitoring/samples/{sample_id}/manual-review | 人工复核归入 hit/miss | reviewer |
| GET | /api/v1/projects/{project_id}/monitoring/samples/{sample_id} | 原始回答与引用；证据文件走证据端点 | `monitoring.read` |

手动触发限制：仅 `pending` 任务可触发；同一任务并发触发用任务锁拒绝（返回 `409 task_rejected`）；按项目限并发；每次触发写审计。

批量生成行为（`POST .../monitoring/rounds/{round_id}/tasks/batch`，B4 已实现）：

- **权限**：`GET /monitoring/rounds` 用 `monitoring.read`；`POST /monitoring/rounds` 与 `POST .../tasks/batch` 用 `monitoring.execute`。本期不新增能力码。
- **只选 `status=active` 且当前版本存在的题目**：`draft`、`archived` 不进入正式任务；`active` 但 `current_version_no` 无对应版本时整批阻断，`skipped_reason="question_version_missing"`。
- 响应必须显式返回：`requested_question_count`（本项目题目总数）、`eligible_question_count`（active 且有当前版本数）、`inactive_question_count`、`inactive_question_ids`（按 `code` 排序）、`inactive_questions`（`id/code/title/status`）、`question_version_missing_count`、`question_version_missing_question_ids`、`engine_count`、`expected_task_count`、`eligible_expected_task_count`、`created_task_count`、`reused_task_count`、`generated_task_count`、`complete`、`skipped_reason`。
- 计数口径：`expected_task_count=requested_question_count×engine_count`；`eligible_expected_task_count=eligible_question_count×engine_count`；`generated_task_count=created_task_count+reused_task_count`。
- `complete = generated==expected AND eligible==requested AND engine_count==4 AND question_version_missing_count==0 AND skipped_reason IS NULL`。
- 部分未激活采用“部分生成 + 不完整”：生成 `eligible×engine_count` 条，`complete=false`、`skipped_reason="inactive_questions"`；全量未激活生成 0 条，同样返回结构化字段。本期统一用 `200 + complete=false`，不返回 409；409 只作为错误信封扩展后的目标态，不进入本期验收。
- 引擎只取当前项目内启用引擎 + 至少一个启用入口，每个引擎只取一个有效入口；`engine_count<4` 时 `complete=false`、`skipped_reason="engine_entries_insufficient"`；`engine_count=0` 不生成任务。
- 幂等键 `round_id + question_version_id + engine_entry_id + sampling_no`；基线 `sampling_no=1`，请求体不传采样序号。首次 `created=24,reused=0,generated=24`；重放 `created=0,reused=24,generated=24,complete=true`。并发重放用轮次行锁或 `INSERT ... ON CONFLICT DO NOTHING` + `RETURNING`，第二次全部 reused。
- 批量生成写审计 `monitoring.tasks_batch_generate`，payload 含 `round_id` 与上述计数/原因字段。
- 并发：批量生成锁 `monitoring_rounds` 轮次行；仅 `POST /rounds` 建基线时锁 `projects` 行。非基线并发建轮次撞 `seq` 唯一约束本期不做 seq+1 重试，前端需防重复点击。
- 状态机：批量只创建 `pending` 任务；B4 采样器按 `pending→running→failed` 走 `ensure_task_transition()`，样本按 `pending→failed` 走 `ensure_sample_transition()`，不把 pending 任务直接改成 failed。
- `draft` 预览/测试任务走独立流程（单独 `dry_run` 或独立端点），不复用正式生成，不写入正式任务表。


### 2.6 证据与渠道

| 方法 | 路径 | 说明 | 权限 |
| --- | --- | --- | --- |
| GET | /api/v1/projects/{project_id}/citations | 引用列表 | `monitoring.read` |
| PATCH | /api/v1/projects/{project_id}/citations/{citation_id} | 确认或驳回归属 | `evidence.review` |
| GET | /api/v1/projects/{project_id}/citations/unknown-domains | 待归类队列 | `channel.read` |
| GET | /api/v1/projects/{project_id}/evidence/{evidence_id}/download | 下载证据文件（已实现，带授权与路径检查） | 项目成员 |
| GET / POST | /api/v1/projects/{project_id}/channels | 渠道台账；POST 新增渠道，`code` 项目内唯一 | `channel.read` / `channel.write` |
| GET | /api/v1/projects/{project_id}/channels/{channel_id} | 渠道明细（引用样本摘要、去重页面、引擎/问题编码） | 项目成员（channel.read） |
| PATCH | /api/v1/projects/{project_id}/channels/{channel_id} | 局部更新分类、状态、主域名、备注、启停与别名；`code` 不改 | `channel.write` |
| GET | /api/v1/projects/{project_id}/channels/export | 导出 CSV（已实现，写审计；支持 `engine_id`、`question_id`、`start_date`、`end_date` 多维筛选；同步 ≤5000 行，超过转异步） | `export.data` |

引用复核行为（B6）：

- `PATCH /citations/{id}` 只能把 `review_status` 改为 `manual_confirmed` / `manual_rejected`；`auto` 由系统回填，手动回写返回 400 `invalid_review_status`。
- `channel_id` / `competitor_id` 为部分更新：请求体显式出现才处理；传值须查 `Channel` / `Competitor` 且属于当前项目，否则 404 `resource_missing`（不暴露存在性）；显式 `null` 清空映射；不传保持原值。`raw_url` 不可经本接口修改。
- `review_note` 同为部分更新：显式传值（含 `null`）才覆盖，不传保留原备注。
- 归属改挂与复核结论写审计，payload 记录最终归属值。

导出行为：

- 不带筛选参数：导出本项目全部渠道台账，列 `code,name,category,status,primary_domain`。
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
| GET / POST | /api/v1/projects/{project_id}/plans | 运营计划与排期 | editor+ |
| GET / POST | /api/v1/projects/{project_id}/media-quotes | 报价与审批 | 提交 `content.write` / 审批 `content.review` |
| GET / POST | /api/v1/projects/{project_id}/pages | 公开站事实页登记 | editor+ |

只有草稿版本正文可编辑；提交后正文锁定。修改已提交内容须创建新版本，审核记录保留提交时的 `content_hash` 快照。

### 2.8 发布

| 方法 | 路径 | 说明 | 权限 |
| --- | --- | --- | --- |
| GET | /api/v1/projects/{project_id}/publish/accounts | 发布账号只读列表（`credential_ref` 只存引用；本期不提供 POST，账号由 seed/运维预置） | `publish.read` |
| GET / POST | /api/v1/projects/{project_id}/publish/tasks | 发布任务列表 / 建发布任务 | `publish.read` / `publish.execute` |
| POST | /api/v1/projects/{project_id}/publish/tasks/{task_id}/attempts | 记录一次尝试 | `publish.execute` |
| POST | /api/v1/projects/{project_id}/publish/tasks/{task_id}/receipts | 回填真实 URL 结案 | `publish.execute` |
| POST | /api/v1/projects/{project_id}/publish/tasks/{task_id}/verify | 回执不明时核实 | `publish.execute` |

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
| GET | /api/v1/projects/{project_id}/stats/geo | 内部 GEO 验收六项指标（有效回答、Mention rate、Citation share、Prompt coverage、Freshness、Failure rate），空分母返回 `null` 并带 `statement` | `stats.read` |
| GET | /api/v1/projects/{project_id}/stats/overview | 品牌提及率、引用率、样本完成率 | `stats.read` |
| GET | /api/v1/projects/{project_id}/stats/by-engine | 分引擎对比 | `stats.read` |
| GET | /api/v1/projects/{project_id}/stats/by-question | 分问题对比（品牌题/通用题分开） | `stats.read` |
| GET | /api/v1/projects/{project_id}/stats/trend | 最多 12 周的周趋势 | `stats.read` |
| GET | /api/v1/projects/{project_id}/stats/task-distribution | 各引擎任务占比 | `stats.read` |
| GET | /api/v1/projects/{project_id}/stats/export | 导出（审计 + 行数上限） | `export.data`（lead_ops 无此能力，不得放行） |
| GET / POST | /api/v1/projects/{project_id}/leads | 线索录入与列表（已实现；lead_ops 与 project_admin 可用，editor 无该能力） | `lead.read` / `lead.write` |

统计导出行为：

- `GET /stats/export` 支持 `round_id`、`engine_id`、`question_id`、`start_at`、`end_at` 与看板相同的筛选参数；输出 CSV 列为 `record_type,code,name,question_type,valid_answers,brand_mentioned_answers,citation_answers,brand_mention_rate,citation_rate,channel_count,page_count,failed_answers,manual_review_answers,pending_or_running_answers`；`overview` 行单列失败/待复核/未完成样本数，`engine` / `question` 行留空；
- 行集固定为三段：`overview` 一行、`engine` 每平台一行、`question` 每题一行；三段全部调用 `services/stats.py` 的 `overview` / `by_engine` / `by_question`，导出层不写新 SQL；
- 写 `audit_logs action=export`，`export_type=stats`、`row_count`、`mode=sync`、`filters` 记录实际筛选值；同步导出超过 `export_sync_row_limit` 返回 400 `export_too_large`；
- 权限为 `export.data`，`lead_ops` 无该能力；viewer 可导出但必须留痕。

统计口径读 `metric_definitions` 当前生效版本；失败样本不计入分母；无样本返回 `null` 而非 0。

**线索归因字段（C 侧新增，2026-11-12）**：`POST /leads` 与 `GET /leads` 增加 `source_question_id`、`source_channel_id`、`source_engine_id`、`landing_url`、`utm_campaign`。`source_question_id` / `source_channel_id` 必须属于当前项目，跨项目引用返回 `404 resource_missing`；`source_engine_id` 必须是已存在引擎。历史 `lead_source` 保留兼容，新数据以三个外键为准。口径见 `docs/转化归因口径.md`。

### 2.10 已实现端点（本分支 `docs/openapi.json` 实测 51 条路径 / 60 个操作 / 148 个 schema）

| 端点 | 能力码 |
| --- | --- |
| `GET /api/v1/projects` | 登录用户（系统管理员看全部，其他人看已加入项目） |
| `POST /api/v1/projects` | `project.create`（系统级） |
| `GET /api/v1/engines` | 登录用户 |
| `POST /api/v1/engines` | `engine.manage`（系统级） |
| `GET /api/v1/engines/{engine_id}/entries` | 登录用户 |
| `POST /api/v1/engines/{engine_id}/entries` | `engine.manage`（系统级） |
| `PATCH /api/v1/engines/{engine_id}/entries/{entry_id}` | `engine.manage`（系统级） |
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
| `POST /api/v1/projects/{project_id}/monitoring/samples/{sample_id}/manual-review` | `evidence.review` |
| `GET /api/v1/projects/{project_id}/citations`、`GET /citations/unknown-domains` | `monitoring.read` |
| `PATCH /api/v1/projects/{project_id}/citations/{citation_id}` | `evidence.review` |
| `GET /api/v1/projects/{project_id}/content-versions`、`GET /content-versions/{version_id}/reviews` | `content.read` |
| `POST /api/v1/projects/{project_id}/content-versions/{version_id}/submit` | `content.write` |
| `GET /api/v1/projects/{project_id}/stats/overview`、`by-engine`、`by-question`、`trend`、`task-distribution`、`export` | `stats.read` / 导出 `export.data` |
| `GET /api/v1/projects/{project_id}/audit-logs` | `audit.read` |
| `GET /api/v1/projects/{project_id}/publish/accounts` | `publish.read`（只读，本期不提供 POST） |
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
| `GET /api/v1/projects/{project_id}/citations` | `monitoring.read` |
| `PATCH /api/v1/projects/{project_id}/citations/{citation_id}` | `evidence.review` |
| `GET /api/v1/projects/{project_id}/citations/unknown-domains` | `channel.read` |
| `GET /api/v1/tasks/{task_id}` | 按任务所属项目重新解析授权 |
| `GET /health`、`/health/db`、`/health/redis`、`/health/worker`、`/health/queue` | 公开探活（不带 `/api/v1` 前缀）；后两条为 CR-002 新增（2026-11-11） |

未实现的端点（题库、关键词、计划、报价、公开站页面、系统级审计查询）保持本文件契约，按同一能力码规则实现。B7 渠道写、B8 统计导出、B9 发布建任务/回执/verify 与 `publish/accounts` 已实现。本分支增量及迁移评审状态见 `docs/契约变更单/CR-003-工作台后端联调接口.md`。

### 2.11 审计查询（本项目已实现，系统级未实现）

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
