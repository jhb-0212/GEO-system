# AI 平台入口自助接入说明（后端 MVP）

> 适用：系统管理员 / 运营配置人员。2026-11-13 首次实现，当前已开放 `openai_compatible`（DeepSeek、火山方舟、千帆 ERNIE 对话模型等）、`yuanbao_search`（腾讯云元宝 SearchPro）、`deepseek_web_search`（DeepSeek Responses 服务端联网工具）、`doubao_search`（火山方舟 Responses + `web_search`）与 `wenxin_search`（千帆 AI 搜索，旧产品，仅留档）五种协议。文心主路径是 `openai_compatible` + `ernie-5.1`，不是 `wenxin_search`。
> 2026-11-18 起，API Key **可以在系统里直接填写**（加密落库、接口与日志不回显），不再要求运维每次改 `.env` 重启；旧的 `credential_ref` 环境变量路径继续有效，优先级低于系统内填写。

## 零、目录批次（2026-11-13）

`backend/scripts/seed_platform_catalog.py` 管理 15 个国内监测候选入口：

- 首轮 4 个：豆包、腾讯元宝、DeepSeek、百度文心；文心主入口是千帆 ERNIE 对话模型（API），不是网页端或千帆 AI 搜索；
- 扩展 6 个：Kimi、千问、夸克、秘塔AI搜索、百度AI搜、360纳米AI；
- 探测 5 个：智谱清言、讯飞星火、微信搜一搜AI、知乎直答、小红书点点。

扩展 6 个和探测 5 个的目录初次落库时先以 `protocol=custom`、引擎和入口均 `is_active=false` 登记，不参与 `generate_tasks`。因此初始 24 格基线仍是 4×6=24，不会变成 15×6；2026-11-20 启用 Kimi、千问、百度AI搜后调整为 6×7=42。官方入口、联网能力、来源可见性、访问限制、最近核验日期由运营核验后补；未接协议前不会伪造调用。

其中 Kimi、千问、秘塔、360 智脑、智谱清言、讯飞星火这 6 个 API 平台，可由 `backend/scripts/seed_platform_api_entries.py` 原地升级为 `openai_compatible` 入口：地址、默认模型、密钥变量名写在脚本里，入口仍默认停用，不进入当前采集基线；智谱等两段式平台的模型名可在入口直接改，不锁死脚本默认值。Kimi、千问、秘塔、360 智脑、智谱、讯飞均已接入联网/引用适配器，种子标记 `supports_search=true`；讯飞星火走星辰 MaaS Chat Completions，`supports_search=true` 时请求体带 `tools:[{"type":"web_search","web_search":{"enable":true}}]`，使用 `max_completion_tokens`，默认关闭 thinking；智谱走两段式：先独立 `POST /api/paas/v4/web_search` 取结构化来源，再用入口 `model_name` 调 Chat Completions；代码不绑定具体模型，默认给免费模型，也可在入口改成 `glm-5.3-flashx` 或其他模型。执行 `--apply` 后只需补 Key 并逐个 `test-connection`，通过后再决定是否启用。目录脚本已做了同名/同类型入口去重，不会重复补占位；只想补单个平台时用 `--only-code <engine_code>`，避免误改已启用平台。2026-11-20 讯飞 Key 已在系统内加密保存，真实联网探针通过（200；同一问题关闭/开启搜索的 prompt_tokens 为 38/3588），响应无结构化引用，入口仍停用。2026-11-21 更换新 Key 后智谱真实联网已通过：独立 `/web_search` 200，系统 `test-connection` 8.6s（回答 381 字、来源 5 条），真实业务适配器回答 279 字、引用 10 条；当前模型为免费 `glm-4-flash-250414`，`glm-5.3-flashx` 仍 429/`1113`，FlashX 包未绑定，入口待运营确认启用。

2026-11-20 16:24 运营确认启用 Kimi、千问：两家 `AiEngine` 与 API `AiEngineEntry` 均置 `is_active=true`，写入 `audit_logs.action=engine.activate`；`_active_engine_entries(require_search=True)` 实际选中 DeepSeek、豆包、Kimi、千问、文心、元宝、百度AI搜 7 个 API 入口。批量基线按 **ACTIVE 题目 × ACTIVE 且可联网入口 × 每格采样次数** 动态计算，当前为 6×7=42；未激活题目不进入分母，停用平台后下一次生成自动缩格。新建库仍按种子默认停用，生产启用需单独确认。
2026-11-20 另新增 **秘塔 API** 入口（`openai_compatible`、`https://metaso.cn/api/v1`、`fast`、系统内加密 Key）；真实 `test-connection` 已通过（1.8s；业务问题回答 1561 字、引用 8 条），`last_verified_at` 已写入。入口和引擎仍保持停用，不改变当前 6×7=42 采集基线；运营确认启用后才纳入采集。
2026-11-20 新增 **360 智脑 AI 搜索 API** 入口（`openai_compatible`、`https://api.360.cn/v1/search/aisearch`、`360gpt-pro`、`QIHU360_API_KEY`）。请求固定 `search_mode=required`、`enable_corner_markers=true`、`max_refer_search_items=20`；响应从顶层 `references` 取标题/链接/摘要/发布时间，正文 `[[n](url)]` 角标作兜底并按 URL 去重。Key 已系统内加密保存，真实 `test-connection` 通过（18.4s；回答 1392 字、references 10 条），`last_verified_at` 已写入；入口默认停用，运营确认后再启用。

**仅应用内入口、不自动采集**：夸克、秘塔AI搜索、百度AI搜、360纳米AI、微信搜一搜AI、知乎直答、小红书点点共 7 条 `app_search` / `custom` 入口。2026-11-21 已补齐官方入口与访问备注，并通过 `POST /api/v1/engines/{engine_id}/entries/{entry_id}/verify` 写入 `last_verified_at`：夸克 `https://www.quark.cn/s`、秘塔 `https://metaso.cn/`、百度AI搜 `https://chat.baidu.com/`、360纳米AI `https://www.n.cn/`、微信搜一搜 `https://search.weixin.qq.com/`、知乎直答 `https://zhida.zhihu.com/`、小红书点点 `https://www.xiaohongshu.com/ai_chat`。入口均保持停用，不进入当前 42 格基线；只能人工采样，不承诺自动采集。2026-11-21 已建“应用内 7×6 人工采样（2026-11-21）”轮次（`d2a32cf3-cc6b-4c4a-a637-d4a4335de620`，`running`，42 条 `pending` 任务）；`app_search` 任务禁止 `/execute`，只能通过任务手测样本接口录入，调度器对含应用内任务的轮次跳过自动补任务。核验只证明入口可达与访问路径成立，不等同检索质量验收。该测试轮及其 24 条样本已在 2026-11-21 交付清理中整轮删除，当前交付库不再包含该轮。

**模型切换**：`model_name` 是入口级字段，可在 AI 平台工作台的入口编辑或 `PATCH /api/v1/engines/{engine_id}/entries/{entry_id}` 中单独修改；同一入口的 `encrypted_secret` / `credential_ref` 不需要重填。切换后必须重跑 `test-connection`，确认新模型可调用、仍支持联网且能返回预期回答/来源。Kimi 走 Responses `web_search`，换 Kimi 模型时保持 `entry_url=https://api.moonshot.cn/v1` 即可由适配器拼 `/responses`。千问联网入口也已切到同 Key 的 Responses `web_search`，`entry_url` 保持 `https://dashscope.aliyuncs.com/compatible-mode/v1` 即可由适配器拼 `/responses`；此时模型必须支持 Responses 的 `web_search` 工具，`qwen-mt-uni` 不支持联网，两个 `-realtime` 模型走 Realtime API，不能直接当作当前普通联网入口使用。`qwen3.8-omni-flash` 在 Responses 下支持 `tools:[{"type":"web_search"}]`；旧 Chat 路径下才需要 `search_options.search_strategy=agent`，系统采集不再走该路径。360 智脑换模型时保持 `entry_url=https://api.360.cn/v1/search/aisearch`，模型必须是平台已开通且可用于 AI 搜索的模型，默认 `360gpt-pro`。智谱入口采用两段式：`/web_search` 与 `model_name` 解耦，入口可填 `glm-4-flash-250414`、`glm-5.3-flashx`、`glm-5.3` 等任意模型，改模型不需要改代码；搜索能力取决于独立搜索接口的余额/资源包，模型 tokens 资源包不抵扣搜索调用。切换模型后仍须重跑 `test-connection`，确认回答与来源都真实返回。

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
- **Kimi API** 仍记 `openai_compatible`，但入口 `supports_search=true` 时走 `POST /v1/responses`：`tools:[{"type":"web_search"}]` + `include:["web_search_call.action.sources"]`，返回**生成回答 + 网页来源**（`answer_kind=answer`）。K3 是强制思考模型，适配器设 `max_output_tokens=16000`、`reasoning_effort=low`，避免推理过程吃光输出预算导致无最终回答；不再使用已进入下线周期的 Chat Completions `$web_search` 内置工具。2026-11-20 已用真实 Key 验证：回答 667 字、引用 9 条。
- **千问百炼 API** 仍记 `openai_compatible`，入口 `supports_search=true` 时走同 Key 的 `POST /compatible-mode/v1/responses`：`tools:[{"type":"web_search"}]`，从 `output[].type=web_search_call` 的 `action.sources`（`type=url` + `url`）归一成引用（`answer_kind=answer`）。适配器设 `max_output_tokens=16000`，因为千问该预算同时覆盖思考与回答；不再发送 Chat `enable_search` / `search_options`，也不再期待 `search_info`。2026-11-20 直连验证：`max_output_tokens=16000` 时状态 `completed`、回答 2712 字、来源 86 条；`2000` 时为 `incomplete`。系统采集已切到该适配器；当前真实入口探针返回 HTTP 400 `Arrearage`（百炼账户欠费），需账户恢复正常后重跑 `test-connection` 和真实采集，才能把引用落库作为业务验收。
- **360 智脑 AI 搜索 API** 记 `openai_compatible`：`entry_url=https://api.360.cn/v1/search/aisearch`、`model_name=360gpt-pro`、`credential_ref=QIHU360_API_KEY`；请求固定 `search_mode=required`、`enable_corner_markers=true`、`max_refer_search_items=20`，响应 `choices[0].message.content` 为生成回答，顶层 `references` 归一成引用；若平台未返回 `references`，从正文 `[[n](url)]` 角标兜底，按 URL 去重。Key 已系统内加密保存，真实探针通过（18.4s；回答 1392 字、references 10 条），入口仍默认停用，运营确认后启用。
- **智谱 GLM API** 记 `openai_compatible`，但走两段式：`entry_url=https://open.bigmodel.cn/api/paas/v4`（也兼容官方 `https://api.z.ai/api/paas/v4`）、`credential_ref=ZHIPU_API_KEY`；第一步 `POST /web_search`（`search_query` ≤70 字符、`search_engine=search_pro`、`search_intent=false`、`count=10`、`content_size=high`）取 `search_result[]` 的 `title/link/media/publish_date/content`，第二步把来源注入上下文，用入口 `model_name` 调 `POST /chat/completions`。**入口不锁定模型**：代码里没有 `glm-4-flash-250414` 之类硬编码，`model_name` 可填任意智谱模型；`glm-5.3-flashx` 也能走同一链路，不再依赖模型内置 `web_search`。2026-11-21 更换新 Key 后真实联网已通过：独立 `/web_search` 200；系统 `test-connection` 8.6s，回答 381 字、来源 5 条；真实业务问题用适配器跑通，回答 279 字、引用 10 条，`answer_kind=answer`，`last_verified_at` 已写入。当前入口模型仍是免费 `glm-4-flash-250414`；同一 Key 的 `glm-5.3-flashx` 仍返回 429/`1113`，说明 300 万 FlashX 资源包未绑定该 Key 所属账户。300 万 token 只抵扣模型 tokens，不抵扣 `/web_search` 搜索调用；搜索走独立搜索资源包/余额。入口保持停用，待运营确认启用。
- **秘塔 API** 记 `openai_compatible`：`entry_url=https://metaso.cn/api/v1`、`model_name=fast`、`credential_ref=METASO_API_KEY`；`POST /api/v1/chat/completions` 返回生成回答，`choices[0].message.citations`（兼容 `sources/references/search_results`）归一成带标题/链接/摘要/发布时间的引用（`answer_kind=answer`）。2026-11-20 已用系统内加密 Key 完成真实探针（1.8s；业务问题回答 1561 字、引用 8 条），入口默认停用；运营确认后再启用。注意：旧域名 `api.metaso.cn` 在本机不可达，官方可用基址是 `https://metaso.cn/api/v1`。
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
- 这是“元宝搜索可见性”，不是“元宝生成式回答”。当前 42 格基线中该平台的结果只能说明检索结果是否提及品牌/竞品、引用了哪些 URL，不能与 DeepSeek/豆包/文心的回答质量直接等同。
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
- 真实 42 格基线已启用 7 个 API 入口（DeepSeek、豆包、Kimi、千问、文心、元宝、百度AI搜）；跑数仍需 7 家凭据/配额齐全，且千问百炼账户需处于正常付费状态（当前探针返回 `Arrearage` 欠费拒绝）；本地 Ollama smoke 只证明链路，不是平台业务基线。
- 秘塔 API 已完成代码 + 库配置，并已用真实 Key 跑通 `test-connection`（1.8s；业务问题回答 1561 字、引用 8 条）；入口仍保持停用，当前基线 6×7=42，运营确认启用后变为 6×8=48。
- 智谱 API 已完成两段式代码（独立 `/web_search` + 入口 `model_name` 回答，不锁模型）+ 库配置；2026-11-21 更换新 Key 后真实联网通过：`test-connection` 8.6s（回答 381 字、来源 5 条），真实业务适配器回答 279 字、引用 10 条，`last_verified_at` 已写入。当前入口模型为免费 `glm-4-flash-250414`；同一 Key 的 `glm-5.3-flashx` 仍 429/`1113`（FlashX 包未绑定）。入口仍停用，待运营确认启用；不能因为 FlashX 未通就否掉已通过的搜索链路。
