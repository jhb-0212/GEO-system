# 接口契约草案（V0.1）

> 由 C 按数据模型整理，供 A/B 评审后定稿。本文只定义约定与端点骨架，不实现；实现在 `backend/app/api` 下落地。

## 一、通用约定

### 1.1 鉴权与项目隔离

- 认证：`Authorization: Bearer <JWT>`，由 `POST /api/v1/auth/login` 签发。
- 项目上下文：项目内接口路径统一带 `project_id`，例如 `/api/v1/projects/{project_id}/questions`。
- 服务端处理顺序固定：解析身份 → 查 `project_members` 确认该项目授权 → 校验角色能力 → 执行。前端传的 `project_id` 只作定位参数，不作权限依据。
- 越权统一返回 `403 {"error":{"code":"project_forbidden"}}`，不区分“项目不存在”与“无权限”，避免探测。

### 1.2 响应与分页

```json
{ "data": [], "meta": { "page": 1, "page_size": 20, "total": 137 } }
```

```json
{ "error": { "code": "validation_error", "message": "...", "details": [] } }
```

- 分页：`page`（默认 1）、`page_size`（默认 20，上限 100），列表默认按 `created_at desc`。
- 时间：ISO 8601 带时区，如 `2026-11-10T17:00:00+08:00`。

### 1.3 幂等与异步

- 监测任务幂等键：`round_id + question_version_id + engine_entry_id + sampling_no`，重复提交返回既有记录。
- 发布任务幂等键：`account_id + channel_id + version_id + task_key`。
- 回执不明一律置 `unknown`，不得直接重试发布，须走 `verify` 核实后再决定。
- 耗时操作（采样、发布、导出）返回 `202` + `task_id`，通过 `GET .../tasks/{task_id}` 轮询。

## 二、端点骨架

### 2.1 认证与用户

| 方法 | 路径 | 说明 | 角色 |
| --- | --- | --- | --- |
| POST | /api/v1/auth/login | 用户名密码换 JWT | 公开 |
| GET | /api/v1/auth/me | 当前用户及项目授权 | 登录用户 |
| POST | /api/v1/auth/password | 改密码 | 登录用户 |

### 2.2 项目与权限

| 方法 | 路径 | 说明 | 角色 |
| --- | --- | --- | --- |
| GET | /api/v1/projects | 可访问项目列表 | 登录用户 |
| POST | /api/v1/projects | 新建项目 | admin |
| GET | /api/v1/projects/{project_id} | 项目详情 | 项目成员 |
| PATCH | /api/v1/projects/{project_id} | 改名/状态/时区 | admin |
| GET / POST | /api/v1/projects/{project_id}/members | 成员与授权 | admin |
| PATCH | /api/v1/projects/{project_id}/members/{member_id} | 改角色或停用 | admin |

### 2.3 题库与关键词

| 方法 | 路径 | 说明 | 角色 |
| --- | --- | --- | --- |
| GET / POST | /api/v1/projects/{project_id}/questions | 列表 / 新建 | editor+ |
| PATCH | /api/v1/projects/{project_id}/questions/{question_id} | 状态、人群、优先级 | editor+ |
| GET / POST | .../questions/{question_id}/versions | 版本列表 / 追加版本 | editor+ |
| GET / POST | .../keywords | 目标词 | editor+ |

修改题目正文必须新开版本并同步 `questions.current_version_no`，旧版本不可编辑。

### 2.4 引擎目录

| 方法 | 路径 | 说明 | 角色 |
| --- | --- | --- | --- |
| GET | /api/v1/engines | 引擎与入口（系统级） | 登录用户 |
| POST / PATCH | /api/v1/engines、/engines/{id}/entries | 维护目录、入口、核验日期 | admin |

### 2.5 监测

| 方法 | 路径 | 说明 | 角色 |
| --- | --- | --- | --- |
| GET / POST | .../monitoring/rounds | 轮次 | editor+ |
| POST | .../monitoring/rounds/{round_id}/tasks/batch | 按 6 题 × 4 引擎批量生成基线任务 | editor+ |
| GET | .../monitoring/tasks | 任务列表（轮次/引擎/状态过滤） | 项目成员 |
| POST | .../monitoring/tasks/{task_id}/execute | 触发采样（202） | editor+ |
| POST | .../monitoring/samples/{sample_id}/manual-review | 人工复核归入 hit/miss | reviewer |
| GET | .../monitoring/samples/{sample_id} | 原始回答、引用、证据文件 | 项目成员 |

### 2.6 证据与渠道

| 方法 | 路径 | 说明 | 角色 |
| --- | --- | --- | --- |
| GET | .../citations | 引用列表 | 项目成员 |
| PATCH | .../citations/{citation_id} | 确认或驳回归属 | reviewer |
| GET | .../citations/unknown-domains | 待归类队列 | editor+ |
| GET / POST | .../channels | 渠道台账 | editor+ |
| PATCH | .../channels/{channel_id} | 分类、状态、域名映射 | editor+ |
| GET | .../channels/export | 按引擎/问题/时间导出 | 项目成员 |

### 2.7 内容与审核

| 方法 | 路径 | 说明 | 角色 |
| --- | --- | --- | --- |
| GET / POST | .../contents | 母稿/渠道稿 | editor+ |
| POST | .../contents/{item_id}/versions | 追加版本（服务端算 content_hash） | editor+ |
| POST | .../contents/versions/{version_id}/submit | 提交审核 | editor+ |
| GET | .../contents/versions/{version_id}/reviews | 审批历史 | 项目成员 |
| POST | .../contents/versions/{version_id}/review | 通过/驳回 + 意见 | reviewer |
| GET / POST | .../plans | 运营计划与排期 | editor+ |
| GET / POST | .../media-quotes | 报价与审批 | editor+ / admin 审批 |
| GET / POST | .../pages | 公开站事实页登记 | editor+ |

审批通过后若 `content_hash` 与审批快照不一致，状态回落 `pending_review` 并写审计。

### 2.8 发布

| 方法 | 路径 | 说明 | 角色 |
| --- | --- | --- | --- |
| GET / POST | .../publish/accounts | 发布账号 | editor+ |
| GET / POST | .../publish/tasks | 发布任务 | editor+ |
| POST | .../publish/tasks/{task_id}/attempts | 记录一次尝试 | editor+ |
| POST | .../publish/tasks/{task_id}/receipts | 回填真实 URL 结案 | editor+ |
| POST | .../publish/tasks/{task_id}/verify | 回执不明时核实 | editor+ |

### 2.9 看板与线索

| 方法 | 路径 | 说明 | 角色 |
| --- | --- | --- | --- |
| GET | .../stats/overview | 品牌提及率、引用率、样本完成率 | 项目成员 |
| GET | .../stats/by-engine | 分引擎对比 | 项目成员 |
| GET | .../stats/by-question | 分问题对比（品牌题/通用题分开） | 项目成员 |
| GET | .../stats/export | 导出（写审计） | 项目成员 |
| GET / POST | .../leads | 线索录入与列表 | lead_ops |

统计口径读 `metric_definitions` 当前生效版本；失败样本不计入分母；无样本返回 `null` 而非 0。

## 三、待评审点

1. 认证用单 JWT 还是 access/refresh 双令牌。
2. 是否需要“跨项目只读对比”权限（当前模型未支持）。
3. 采样执行是否开放前端手动触发，还是只由 Worker 定时领取。
4. 导出用同步 CSV 还是异步任务（大数据量建议异步）。
