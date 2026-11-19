# 官网诊断 L2/L3 日志导入契约

本文是官网诊断 L2（爬虫访问）与 L3（用户访问）事件的系统内导入契约。对应页面：

`/workbench?section=site-diagnostics&project_id=<项目 ID>` → “L2/L3 日志导入”面板。

## 1. 权限与接口

| 数据 | 接口 | 权限 |
| --- | --- | --- |
| L2 爬虫事件 | `POST /api/v1/projects/{project_id}/crawler-events/import` | `monitoring.execute` |
| L3 访问事件 | `POST /api/v1/projects/{project_id}/traffic-events/import` | `monitoring.execute` |

前端通过同源 BFF 调用：

- `/internal/workbench/data?kind=crawler-events-import&project_id=<项目 ID>`
- `/internal/workbench/data?kind=traffic-events-import&project_id=<项目 ID>`

不要把 `verified_bot=true` 当成 UA 声明的转写：只有已经按 IP 反查或 CDN 自身验证过的爬虫事件才可置 `true`。UA 只写进 `ua_claimed`。

## 2. 通用格式

请求体必须是：

```json
{
  "source": "cdn_csv",
  "events": [ ... ]
}
```

`events` 为 1–5000 个事件对象；`source` 可选，最长 64 字符。页面上的“来源标识”会写入 `import_source`；事件对象自带 `import_source` 时优先使用后者。

页面支持三种粘贴格式：

1. JSON 数组：
   ```json
   [{"page_url":"https://www.gdccai.com/a","occurred_at":"2026-11-19T08:00:00+08:00"}]
   ```
2. `{ "events": [...] }` 包装对象；
3. JSONL（一行一个事件对象），适合从日志文件直接粘贴。

当前入口不接受 CSV；CDN/埋点导出的 CSV 请先按字段表转成 JSON 数组。`occurred_at` 使用带时区的 ISO 8601，例如 `2026-11-19T08:00:00+08:00` 或 `2026-11-19T00:00:00Z`。

## 3. L2 爬虫事件字段

| 字段 | 必填 | 类型 / 约束 | 说明 |
| --- | --- | --- | --- |
| `page_url` | 是 | string，1–2048 | 被访问的官网 URL；匹配时忽略 http/https 和末尾斜杠 |
| `occurred_at` | 是 | datetime | 带时区 ISO 8601 |
| `ua_claimed` | 否 | string，≤512 | 日志里的 UA 声明，不作为验证依据 |
| `source_ip` | 否 | string，≤64 | 来源 IP，用于反查验证 |
| `verified_bot` | 否 | bool，默认 false | 仅经 IP 反查/CDN 验证后填 true |
| `http_status` | 否 | int，100–599 | 响应状态码 |
| `bytes` | 否 | int，≥0 | 响应字节数 |
| `import_source` | 否 | string，≤64 | 覆盖本次请求的 `source` |

示例：

```json
{
  "source": "cdn_csv",
  "events": [
    {
      "page_url": "https://www.gdccai.com/faq/a",
      "ua_claimed": "Bytespider",
      "source_ip": "203.0.113.10",
      "verified_bot": true,
      "http_status": 200,
      "bytes": 1024,
      "occurred_at": "2026-11-19T08:00:00+08:00"
    }
  ]
}
```

响应：

```json
{"data": {"imported": 1, "matched_pages": 1}}
```

`matched_pages` 是按 `public_pages.url` / `canonical_url` 匹配到的去重页面数；未匹配事件仍会入库，`public_page_id` 为空。

## 4. L3 访问事件字段

| 字段 | 必填 | 类型 / 约束 | 说明 |
| --- | --- | --- | --- |
| `landing_url` | 是 | string，1–2048 | 落地页 URL |
| `occurred_at` | 是 | datetime | 带时区 ISO 8601 |
| `visitor_session_id` | 否 | string，≤64 | 访问会话 ID；用于与线索 `session_id` 对齐 |
| `utm_source` | 否 | string，≤128 | 来源渠道 |
| `utm_campaign` | 否 | string，≤128 | 活动标识 |
| `referrer` | 否 | string，≤2048 | 来源页 |
| `is_bot` | 否 | bool，默认 false | 是否为 bot 访问；人类访问应填 false |
| `import_source` | 否 | string，≤64 | 覆盖本次请求的 `source` |

示例：

```json
{
  "source": "ga4_export",
  "events": [
    {
      "visitor_session_id": "s-1",
      "landing_url": "https://www.gdccai.com/faq/a",
      "utm_source": "doubao",
      "utm_campaign": "geo-test",
      "referrer": "https://www.doubao.com/",
      "is_bot": false,
      "occurred_at": "2026-11-19T09:00:00+08:00"
    }
  ]
}
```

响应：

```json
{"data": {"imported": 1}}
```

## 5. 导入后的口径

- L2 事件进入 `crawler_events`；只有 `verified_bot=true` 的事件计入“已验证 bot / 被爬页面”。
- L3 事件进入 `traffic_events`；`is_bot=false` 才计入漏斗里的“人类访问”，`traffic_events` 总数包含 bot。
- 两类事件都按项目隔离，导入不会创建发布渠道、不会修改页面台账的 L1 字段。
- 每次导入写一条审计：L2 为 `crawler_events.import`，L3 为 `traffic_events.import`。

## 6. 命令行示例

PowerShell：

```powershell
$TOKEN = (Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8001/api/v1/auth/login" `
  -ContentType "application/json" `
  -Body '{"username":"geo_admin","password":"geo-admin-dev"}').data.access_token
$HEADERS = @{ Authorization = "Bearer $TOKEN" }
$PROJECT_ID = "<项目 ID>"
$BODY = Get-Content .\crawler-events.json -Raw
Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8001/api/v1/projects/$PROJECT_ID/crawler-events/import" `
  -Headers $HEADERS -ContentType "application/json" -Body $BODY
```

L3 同理，把路径换成 `traffic-events/import`。

## 7. 常见失败

| 返回 | 原因 |
| --- | --- |
| `401` | 未登录或令牌失效 |
| `403` | 没有项目 `monitoring.execute` 权限 |
| `422` | `events` 为空/超过 5000 条，或必填字段缺失、日期格式错误、布尔值不是 bool |
| `404` | 项目不存在或无访问权限 |

页面不会把 422 的原始英文 Pydantic 错误直接当业务成功；导入失败会显示在页面错误条中。
