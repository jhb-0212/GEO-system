# GEO 内部验收指标口径

> 适用：广州基地 C 侧内部验收，不对外商用。
> 入口：`backend/app/services/stats.py::geo_overview` + `backend/scripts/geo_report.py`；当前**不新增 HTTP 端点**，避免与 B 的统计契约重复。
> 原则：分母为 0 返回 `null`，不把“没有有效回答”显示成 0%；报告必须显式写“有效回答 0”。

## 一、有效回答

有效回答 = `monitoring_samples.status in ('hit', 'miss')` 的样本数。

以下不计入有效回答：

- `failed`：适配器/入口失败，例如 `access_blocked`、`timeout`、`rate_limited`；
- `pending` / `running`：尚未产出答案；
- 被人工复核改判前的样本仍按 `hit/miss` 计入，人工复核字段单独可查。

样本必须通过 `monitoring_tasks` → `question_versions` → `ai_engine_entries` 关联；跨项目样本不进入当前项目分母。

## 二、六项指标

| 指标 | 口径 | 分母为 0 |
| --- | --- | --- |
| `valid_answers` | 有效回答数，定义见上 | 0 |
| `mention_rate` | 品牌提及的有效回答 / 有效回答；品牌提及取 `monitoring_samples.brand_mentioned=true` | `null` |
| `citation_share` | 品牌相关引用 / 全部引用；只统计有效回答关联的 `monitoring_citations`，品牌相关取 `is_brand_related=true` | `null` |
| `sov` | 有品牌提及的有效回答 /（有品牌提及的有效回答 + 有竞品提及的有效回答）；竞品提及取 `monitoring_competitor_mentions` 的去重 `sample_id` | 双方都为 0 时 `null` |
| `prompt_coverage` | 有至少 1 条有效回答的 active 题目 / active 题目；题目为 `questions.status='active'` | active 题目为 0 时 `null`；有题目但 0 覆盖时为 `0.0` |
| `freshness_hours` | `now - 最近一条有效回答的 sampled_at`，单位小时 | 无有效回答时 `null` |
| `fresh_24h_rate` | 24 小时内有效回答 / 有效回答 | `null` |
| `failure_rate` | `failed` 样本 / 全部样本（含 pending/running/failed） | 全部样本为 0 时 `null` |

补充字段：

- `counts.confirmed_brand_citations`：人工复核确认的品牌引用数，供“严格 citation share”二次口径使用；
- `counts.used_citations` / `counts.cited_citations`：`citation_usage` 为 `used` / `cited` 的引用数；
- `counts.competitor_mentioned_samples`：有竞品提及的有效回答数；
- `by_competitor`：各竞品去重样本数，用于解释 SOV 分子分母。

## 三、结构化字段

本轮依赖的字段（迁移 `ec6900f899c0`，PR #11）：

- `monitoring_samples.engine_model` / `model_version`：哪个模型/版本回答；
- `monitoring_samples.country_code` / `language`：地域与语言；
- `monitoring_citations.citation_usage`：`used`（答案使用了该来源）/ `cited`（答案引用了该来源）；
- `monitoring_citations.competitor_id`：引用归属竞品；
- `monitoring_competitor_mentions`：样本 × 竞品唯一，保留位置与证据文本。

`sentiment` 本期不做；没有情感字段时不推断正负面。

## 四、自动采集链

```text
Celery beat
  ├─ geo.outbox.dispatch       每 30 秒
  └─ geo.monitoring.schedule   每 300 秒
        ↓
  schedule_active_rounds：active 项目 + planning/running 轮次
        ↓  plan_round_tasks（锁 monitoring_rounds 行，按 active 题目 × active 引擎入口幂等建 pending 任务）
  outbox_events(topic=monitoring.task.execute)
        ↓  dispatch_pending_events（FOR UPDATE SKIP LOCKED，发送成功才标 dispatched）
  Celery geo.monitoring.execute
        ↓  EngineRateLimiter（Redis INCR + 90s EXPIRE，key 按引擎/分钟）
  条件抢占样本（(task_id, attempt_no) 唯一约束 + begin_nested）
        ↓
  hit/miss + 结构化回填；失败落 failed/失败码
```

重试与失败归档：

- `RateLimitedFailure`、`TransientCollectionFailure`：Celery `max_retries=3`、`countdown=30`；重试耗尽后 `mark_task_failed`；
- `access_blocked` 等不可重试失败：样本直接 `failed`，任务直接 `failed`，不重试；
- 失败码写入 `monitoring_samples.failure_code` / `failure_note`，任务终态写 `monitoring_tasks.status='failed'`；
- 默认 `UnconfiguredAdapter` 明确抛 `access_blocked`，**不伪造答案**。

启动方式：worker 与 beat 必须分别启动（见 README 第三节）。只起 worker 不起 beat 时，调度与 outbox 消费都不会发生。

## 五、报告命令

```powershell
cd backend
.\.venv\Scripts\python.exe scripts\geo_report.py --project-code gz-base
.\.venv\Scripts\python.exe scripts\geo_report.py --project-code gz-base --round-seq 1 --json
.\.venv\Scripts\python.exe scripts\geo_report.py --project-code gz-base --require-valid-answers
```

`--require-valid-answers` 在有效回答为 0 时返回退出码 2；用于 CI/验收脚本，防止把技术链路基线当业务基线。

## 六、边界

- `24/24 access_blocked` 只能作为技术链路基线；报告里的 `valid_answers=0` 是事实，不是业务结论；
- `citation_share` 当前用全部有效引用；如需“人工确认后才算”，用 `confirmed_brand_citations` 另算，不偷换主口径；
- `sov` 按样本去重计数，不按提及次数加权；同一回答同时提品牌和竞品时，分子分母各计 1；
- `freshness` 当前只给“最近有效样本小时数 + 24h 占比”，没有设定通过阈值；
- `geo_overview` 是 service + CLI，尚无 `/stats/geo` HTTP 端点；B 的统计端点接入时直接调用同一函数。
