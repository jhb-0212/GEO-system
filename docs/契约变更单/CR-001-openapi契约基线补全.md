# 契约变更单 CR-001：openapi.json 契约基线补全

| 项 | 内容 |
| --- | --- |
| 编号 | CR-001 |
| 日期 | 2026-11-11 |
| 提出 | 外部审查（DeepSeek）P0-3，方案 A |
| 处理 | C（数据库与交付） |
| 类型 | 响应 schema 补全 + 契约文本澄清；**不改路径、不改权限码、不改状态机、不改数据库结构** |
| 结论 | 已实施（`docs/openapi.json` 重新导出，`pytest` 33 passed） |

## 一、问题

`docs/openapi.json` 虽随 V1.0 冻结，但内容不足以作为契约基线：

1. `info.version = "0.1.0"`，与"V1.0 接口契约"不一致；
2. `GET /api/v1/tasks/{task_id}` 的 200 响应是空 object schema，前端无法据此生成类型；
3. `components.securitySchemes` 为空，`authorization` 未被声明为必填；
4. 所有响应都没有 schema，`{"data": ...}` / `{"error": {...}}` 两条约定只存在于文字。

复核还发现两处"契约写了、实现没做到"的差异：契约 1.3 要求列表分页返回 `meta{page,page_size,total}`，实现只有 `limit`；契约 1.5 的任务状态字段与实现返回字段不一致。

## 二、变更项

| # | 变更 | 落地位置 |
| --- | --- | --- |
| 1 | `info.version` 0.1.0 → 1.0.0 | `backend/app/core/config.py`（`app_version`） |
| 2 | 声明 Bearer 认证：`HTTPBearer(auto_error=False)`，`securitySchemes.BearerAuth`，非 health 操作全部 `security` 必填 | `backend/app/api/deps.py` |
| 3 | 响应模型：`Envelope[T]`、`PagedEnvelope[T]` + `PageMeta`、`ErrorEnvelope` + `ErrorBody`，以及 16 个业务数据模型 | `backend/app/api/responses.py` |
| 4 | 20 条路径、24 个操作全部挂 `response_model`（文件下载/CSV 导出声明二进制/文本响应） | `backend/app/api/*.py` |
| 5 | 列表分页：7 个列表端点统一 `page`（默认 1）、`page_size`（默认 20，上限 100），返回 `data + meta` | projects / engines / members / channels / leads / monitoring / publish |
| 6 | 任务状态对齐契约 1.5：新增 `kind`、`progress`、`error`、`finished_at`，`project_id` 允许空（系统级 topic） | `backend/app/api/tasks.py` |
| 7 | 422 也走错误信封：`{"error":{"code":"validation_error","message":...}}` | `backend/app/main.py` |
| 8 | 错误响应在 401/403/404/409/422 上声明 `ErrorEnvelope` | 各业务 router `responses=COMMON_ERRORS` |
| 9 | 契约文本澄清：1.3 补分页/排序说明，1.5 补实现说明（`progress`/`finished_at` 返回 `null` 的原因） | `docs/API契约.md` |

## 三、兼容性影响

- **无破坏性路径/字段删除**。任务状态只做加法（`topic`、`dispatched_at` 保留，新增 4 个契约字段）。
- **两处行为变化**：
  1. 列表接口新增 `page` / `page_size` 参数并返回 `meta`；原先的 `limit` 参数（仅 `leads` 使用）取消。前端目前是骨架（`app/page.tsx` 占位），未接后端，无现网调用方。
  2. 参数校验失败（422）由 FastAPI 默认 `{"detail":[...]}` 改为 `{"error":{"code":"validation_error","message":...}}`。这是把实现拉回契约 1.2 已定的错误码 `validation_error`，不是新增码。
- **认证行为未变**：缺头仍返回 401 `unauthorized`；只是该要求现在会出现在导出的契约里。
- **数据库未变**：`docs/数据库DDL.sql` SHA-256 仍为 `A8240B97DA31A18CD0133EF90A49C604A233DE9B3A9E544427964F10B38C125D`。

## 四、验证

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest tests -q          # 33 passed
.\.venv\Scripts\python.exe -c "import json; from app.main import app; open(r'..\docs\openapi.json','w',encoding='utf-8',newline='\n').write(json.dumps(app.openapi(), ensure_ascii=False, indent=2))"
```

实测结果：

- `info.version = 1.0.0`；20 条路径；`components.schemas` 57 个；
- `securitySchemes = ["BearerAuth"]`；除 `/health*` 外所有操作 `security` 非空；
- 7 个 `PagedEnvelope_*` 组件均含 `data` 与 `meta{page,page_size,total}`；
- `TaskStatusData` 字段：`task_id / kind / project_id / topic / status / progress / error / finished_at / created_at / dispatched_at`；
- 每个操作的 2xx 响应都有 schema（`evidence download`、`channels export` 为 binary / text/csv）；
- `docs/openapi.json` 新指纹 `772769CF4C3DBFEB0745939C7AEAB9521195C71C8B128842C9EDEF87657CB08B`。

## 五、回退

本次为独立提交，回退该提交即可恢复旧 `openapi.json` 与旧响应行为；数据库与迁移不受影响，无需 `downgrade`。

## 六、遗留（未在本单解决）

1. `progress` / `finished_at` 无数据源（outbox 不落进度），当前返回 `null`；需执行器补充进度写入后再填字段，属后续 CR。
2. `auth/login` 仍未实现，前端无法自助取令牌（本地验收用 `backend/scripts/dev_token.py`）。
3. 契约中标注"未实现"的端点（题库、关键词、监测轮次/复核、引用、渠道写、发布回执、统计看板与导出、运营计划、媒体报价、公开站、审计查询）本轮未新增实现。
4. 前端尚未接后端，契约类型生成与 mock 落地属 A 的后续工作。
