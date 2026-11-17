# DeepSeek 网页端采集稳跑流程

适用：`deepseek_websearch` 入口（走本地采集桥 + 浏览器登录态）。官方 API 没有联网搜索，网页端风控敏感，按本流程执行。

## 一、硬性额度（代码已内置，无需手工遵守）

| 约束 | 默认值 | 配置项 |
| --- | --- | --- |
| 每分钟调用 | 1 次 | `MONITORING_WEBSEARCH_RATE_LIMIT_PER_MINUTE` |
| 每日调用 | 20 次 | `MONITORING_WEBSEARCH_DAILY_CAP` |
| 单轮次单引擎 | 5 条 | `MONITORING_WEBSEARCH_ROUND_CAP` |
| 命中限流后冷却 | 1440 分钟（当天停手） | `MONITORING_WEBSEARCH_COOLDOWN_MINUTES` |
| 采集桥两次采集间隔 | ≥60s + 0–10s 抖动 | 桥启动参数 `--min-interval` |

超过任一额度：不建样本、不发请求，任务直接落失败并带原因（如「本轮网页端采集已达 5 条上限」）。

## 二、解封后的第一次验证

1. 先跑登录（弹出浏览器，人工扫码/验证码）：
   ```
   backend\.venv\Scripts\python.exe backend\scripts\deepseek_websearch_bridge.py login --headed
   ```
2. 起采集桥（默认 60s 间隔）：
   ```
   backend\.venv\Scripts\python.exe backend\scripts\deepseek_websearch_bridge.py serve
   ```
3. 只跑 **1 条**问题，确认返回有答案和引用、没有「限流/验证」提示。单条通过再谈下一批。

## 三、日常跑法

- 每轮最多 5 题，题与题之间让后端自然排队（1 次/分钟），不要连点「重跑」。
- 一天总量控制在 20 条以内，建议压在 10–15 条，留余量。
- 只发题库里的问题原文；不发指令式、诱导式、敏感话题的问法。
- 同一问题 24 小时内不重复采集。

## 四、异常处理

- 出现一次 `rate_limited`：当天停手，不要动冷却键「续跑」。
- 出现 `login_blocked`：重新执行第 1 步登录，再跑 1 条验证。
- 需要人工解除冷却（仅在确认账号状态正常后）：
  ```
  docker exec geo-redis redis-cli del geo:monitoring:cooldown:deepseek_websearch
  ```
- 查看当天已用额度：
  ```
  docker exec geo-redis redis-cli get "geo:monitoring:daily:deepseek_websearch:20261117"
  ```

## 五、进程与开关

- 采集桥停止 = 网页端不会再有任何调用；需要时按第 2 步重启。
- 任务真正执行还需要 Celery worker（Windows 用 solo 池）：
  ```
  backend\.venv\Scripts\celery.exe -A app.worker.celery_app worker --pool=solo --loglevel=info --workdir backend
  ```
- 自动建任务由 beat 负责，不启动 beat 就不会自动生成新一轮任务。

## 六、边界

- 冷却与日额度是 Redis 级护栏，Redis 故障时按「放行」降级，此时必须人工盯首批结果。
- 单轮上限按「轮次 × 引擎」计数，跨轮次累计仍受日额度 20 条约束。
