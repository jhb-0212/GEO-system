# 指标字典（GEO 测量口径）

> 目的：每个对外出现的数字都能回答「分子是什么、分母是什么、哪些样本被排除」。本文件是唯一口径源；后端常量与报告页文案都必须与这里一致，改口径先改本文件。

## 0. 三条硬规则

1. **不合成总分**：报告只给分项数字，不折算「综合评分 / 健康度 / 等级」。分项之间不可加、不可比大小。
2. **分母必须披露**：任何百分比都同时返回分子、分母与样本数；分母为 0 时返回 `null` 并写明「无有效样本」，不用 0 假装有数据。
3. **失败与待复核不混入分母**：`failed`、`manual_review`、`no_answer_surface`、`pending / running` 一律单列计数，不参与任何比率计算。

## 1. 样本基座

- **有效样本**（`valid_answers`）：`monitoring_samples.status ∈ {hit, miss}`。
- 默认过滤：当前项目 + 当前账号可见范围；可选过滤 `round_id / engine_id / question_id / start_at / end_at / answer_kind / question_type`。
- **答案口径不得混算**：`answer`（生成回答）与 `search_result`（检索结果）各自独立分母；报告默认按「全部样本」但会在 scope 里标出实际口径。
- **题目分区**：`brand` 题是产品功能验证、`general` 题是自然发现率，默认不合并。

## 2. 五个分项

| # | 指标 | 分子 | 分母 | 数据来源 |
|---|---|---|---|---|
| 1 | 提及率 | `brand_mentioned = true` 的有效样本数 | 有效样本数 | `monitoring_samples.brand_mentioned` |
| 2 | 首推率 | `brand_list_rank = 1` 的有效样本数 | 有效样本数 | `monitoring_samples.brand_list_rank` |
| 3 | 信源覆盖 | 品牌自有域名命中的已复核引用去重域名数 | 已复核引用去重域名总数 | `monitoring_citations.source_category = brand_owned` |
| 4 | 竞品位次 | 品牌位次不劣于最优竞品位次的样本数 | 同时有品牌位次与竞品位次的样本数 | `brand_list_rank` + `monitoring_competitor_mentions.position` |
| 5 | 引用上下文质量 | 标题或摘要出现品牌名/别名的已复核引用数 | 已复核引用总数 | `monitoring_citations.title / snippet` × 品牌词表 |

补充口径：

- **首推率的分母仍是全部有效样本**，不是「提及了品牌的样本」。理由：首推是相对全部回答的稀缺度，换分母会让不同引擎之间不可比。
- **信源覆盖**只算 `review_status = manual_confirmed` 的引用；未复核引用进不了分母，也不进分子。`source_category` 未识别的引用仍计入分母，这是「覆盖不足」的真实来源。
- **竞品位次**只在「同一条回答里品牌与至少一个竞品都有位次」时计分；只有一方有位次的样本两边都不计入，避免用缺失值凑分母。
- **引用上下文质量**用品牌正式名 + 别名做包含匹配（大小写不敏感），命中标题或摘要即算「上下文提到品牌」；它衡量的是「引用页面是否围绕品牌上下文」，不等于页面质量评级。

## 2.1 三分口径（cited / mentioned_only / absent）

同一条有效样本只能落一档，三档相加严格等于 `valid_answers`：

| 档位 | 判定 | 用途 |
|---|---|---|
| `cited` | `brand_mentioned = true` **且** 存在 `is_brand_related = true`、`review_status = manual_confirmed` 的引用（带 URL） | 唯一的流量入口口径；「被提到」不等于「带链接」 |
| `mentioned_only` | `brand_mentioned = true` 但没有任何已复核带 URL 引用 | 有认知、无可追溯来源 |
| `absent` | `brand_mentioned = false` | 品类问题里完全没有品牌 |

- 引擎 `supports_citation = false` 时引用不可观测，该引擎的样本一律只可能进 `mentioned_only`，**不能因为看不到链接就判成没被引用**。
- `brand_cited_rate = cited / valid_answers`；`citation_rate`（现有引用率）口径不同：它按「基地相关且已复核引用」计，不要求点名提及，两者不可互相替代。

## 2.2 份额口径（sov 与 sov_detail）

- **`sov`（条目口径，保留）**：`brand_mentioned_answers / (brand_mentioned_answers + competitor_mentions)`，按样本-实体条目计数。
- **`sov_detail`（样本口径，对外讲份额用这个）**：分母 = 「提到品牌或任一竞品的去重有效回答」；每个实体分子 = 自己被提及的样本数。
- 一个回答同时提到品牌与竞品时，双方各计 1，因此**各方份额相加可能超过 100%**——它衡量曝光普遍度，不是互斥投票，不做归一化。
- 没有竞品提及时 `sov = 100%` 只表示"这批样本里没识别到竞品"，不代表市场份额。

## 2.3 引用源覆盖（source-coverage）

- **范围**：近 N 天（默认 90）的有效样本（`hit/miss`）里，`review_status = manual_confirmed` 的引用。
- **分母**：Top N 已复核引用域名（默认 20），**不是全网域名**——长尾会稀释覆盖率，对外无解释力。
- **覆盖判定**：域名为自有域名（`brand_profiles.owned_domains` 或 `source_category = brand_owned`），**或**有发布回执落在该域名家族（`zhuanlan.zhihu.com` 与 `zhihu.com` 同族）。
- **缺口判定**：该域名有竞品引用、我们没有任何回执落在该域名、且不是自有域名。只列前 10。
- 该指标回答「该投哪里」，不替代渠道台账，也不做「应该投多少」的推算。

## 2.4 回执三态（可访问 / 已被收录 / 已被引用）

同一条回执 URL 回答三个独立问题，**互不推导**：

| 态 | 怎么来 | 判定 |
|---|---|---|
| 可访问 | `POST /stats/publish-receipts/reachability-check` 回抓页面本身 | `2xx/3xx/401/403/429` → 可访问（存在，只是挡爬）；`404/410` → 不可访问；其余状态码与超时/网络失败 → `null`（不下结论） |
| 已被收录 | 浏览器实检搜索引擎结果页 | `visibility_matched` 三档（已收录 / 未收录 / 未检测），失败记 `visibility_error_code` 不算未收录 |
| 已被引用 | 只认 `review_status = manual_confirmed` 的引用 | `cited` 布尔 |

- 回抓失败（超时、DNS、TLS）**只写 `reachability_error`，不覆盖上一次的 `last_reachable`**——网络抖动不该改写历史事实。
- 403/429 判为「可访问」是有意的：那是反爬拦截而非页面消失，它能解释「能访问但检不到收录」。
- 三个态都是单条回执的事实，不做任何合成比率相加；`reachable_rate` 只按「已回抓且结论非空」的条数算分母，`null` 显示「无数据」。

## 2.5 信源分级（T0–T3）与多源交叉验证

**分级是站点属性，不是内容质量分，也不参与任何加权合成。** 每条结论都带命中规则，可逐条复核：

| 顺序 | 规则 | 判定 | 档位 |
|---|---|---|---|
| 1 | `owned_domain` / `category:brand_owned` | 命中 `brand_profiles.owned_domains` | T0 |
| 2 | `domain:gov_cn` / `domain:edu_cn` | `*.gov.cn`、`*.edu.cn` | T0 |
| 3 | `category:institution:non_official_domain` | 标了政府/院校类别但域名不是官方域（民办培训站） | T2 |
| 4 | `whitelist:T1` / `category:reference` | 大模型高频引用平台与参考站白名单 | T1 |
| 5 | `whitelist:T2` | 垂类媒体与综合门户白名单 | T2 |
| 6 | `default:T3` | 长尾、个人站、聚合站、未识别域名 | T3 |

- **同站折叠**：`zhuanlan.zhihu.com`、`mp.weixin.qq.com` 折到白名单主域，一个子域/多页只算一个信源；不按陌生域名做猜测式归并。
- **白名单是代码常量**，加站要改代码并走提交，不做后台可编辑——避免分级被随手调松。
- **多源交叉验证**按回答计数：分母是「有我方已复核引用的回答」，分子分三档——`single_source`（1 个站）、`multi_source`（≥2 个不同站）、`multi_high_tier`（≥2 个不同 T0/T1 站）。同一条回答里同站多页只算一次。
- 只输出计数与比率，**不换算成「可信度得分」**，也不与提及率/引用率相乘。

## 2.6 信源 × 内容形态矩阵（source-matrix）

- **口径**：近 N 天有效样本里，已复核引用按「站点 × `page_type`」交叉；站点同样折叠到主域，默认只看 T0/T1/T2（`tiers=` 可改，非法档位忽略并回显）。
- **输出**：每个站点的引用条数、形态分布、主形态及其占比、状态（自有 / 已覆盖 / 缺口 / 未触碰），以及全局形态分布。
- **只能当事实用**：形态份额反映「这个站上什么页更容易被引用」，**不换算成投放条数或推荐优先级**；不给形态匹配度评分。
- **已知缺口**：重判前约六成已复核引用的 `page_type` 是 `other`。`page-type-r1`（URL 路径规则）把真实库 412 条的 other 从 247 降到 136；`page-type-content-r1`（标题/摘要词表）再降到 67（16%）。剩余 other 是 URL 与标题都无形态词的长尾页，矩阵页仍会提示该缺口——**宁可不判，也不把长尾硬塞进某个形态**。
- **重判规则（两种模式）**：
  - `mode=path`（`page-type-r1`）：按「URL 路径 → 站点 → 标题」顺序命中（`/question`、`/rank`、`/course`、`douyin`、公众号优先 article 等）。
  - `mode=content`（`page-type-content-r1`）：只读标题与摘要词表，12 个形态各带强词（权重 2）与弱词（权重 1）；要求最高分 ≥2 且领先次高分 ≥1，否则 `other` + `content:ambiguous`。已修两个误判：`怎么样` 是评价问法不算 how_to；`岗位` 单独出现只算 1 分，recruitment 需 `招聘/在招/岗位职责`。
  - 每条写 `classification_rule_version` 与命中规则；只重判 `page_type=other`，`page_type_source=manual` 的行永不覆盖。预览 `GET /citations/page-type-preview?mode=` 不写库，`POST /citations/page-type-reclassify?mode=` 才写，审计 `citations.page_type.reclassify` 带 `mode`。
- **标题补齐（content 模式的前置）**：真实库 923 条引用只有 16 条带标题，content 模式无从判定。`POST /citations/page-title-backfill?limit=100&apply=` 逐条回抓页面自带 `<title>`/`<meta description>`：按 header → meta → utf-8 → gb18030 解码；401/403/429 记 `blocked`，取不到就留空，**不做推测**。真实库首轮 231 条无标题 other 补回 198 条（86%），补完 content 模式才判出 100 条。审计 `citations.title.backfill`。

## 2.7 内容新鲜度（content-freshness）

- **口径**：以 `publish_receipts.received_at`（最近一条回执）作为「已发布」的唯一证据；距生成时刻超过 N 个月（默认 18）判 `stale`。
- **四种状态**：`fresh` / `stale` / `unpublished`（没有任何回执）/ `published_unverified`（发布任务标了 published 但无回执）。只有前两者进新鲜度分母。
- **不落库**：过期标记实时计算，不写字段——口径或时钟一变，不会留下历史假标记。
- **渠道维度**：母稿与渠道稿分开算；渠道行只统计挂在该渠道上的稿件，未挂渠道的单列 `unassigned`。返回 `过期率 = stale / (fresh + stale)`，无已发布内容时为空值。
- **真实库（14 条内容）**：已发布 4 条、全部新鲜，未发布 10 条，过期 0 条。数据量小，只作事实呈现，不据此下「内容老化」结论。

## 2.8 验收契约（acceptance-contract）

- **三率独立**：提及率 / 引用率 / 正向率，各自一个分母，**不相加、不合成综合分**。
- **分母同源**：直接调用 `services/stats.py::overview()`，与统计总览同一口径（有效回答 = hit/miss 样本；引用率只算可观测引用引擎）。
- **正向率**：只认 `sentiment_labels`（挂在已复核引用上），正向 / 已标注；当前真实库 0 条标注 → 返回 `null` 并标 `not_collected`，**不用代理口径、不填 0%**。
- **连续采集**：从今天按项目时区往回数，连续有有效样本的天数；断一天归零，目标默认 30 天。
- **交付态**：`ready.contract_ok = 三率齐全 且 连续天数达标`；缺哪项由 `ready.missing` 点名。
- **引用来源结构披露**：被引页按 `source_category` 计数，社交/UGC·电商·其他合计为「低可信来源」并披露占比；`unknown`（类别未识别）单列。两者只作披露，不参与率的加减。
- **真实库（90 天）**：有效回答 117、提及率 19.66%、引用率 6.84%（8 条回答）、正向率未采集、连续采集 0 天（最近有效样本 11-21）。被引 28 条中 27 条来源类别未识别（96.4%），社交/UGC 1 条——**下一步是补来源归类，不是继续修率**。

## 2.9 品牌相关性补齐 + 情感抽样盲评

**品牌相关性（引用率/正向率的分母前置）**
- `GET /citations/brand-related-candidates` 只预览、不改库；`POST /citations/brand-related-candidates/backfill` 才写，落审计 `citations.brand_related.backfill`。
- 候选依据：已人工复核、当前非品牌相关、且标题/摘要/域名/URL 命中品牌正式名、别名或自有域名；短于 3 字的词（如「成才」）不参与命中，避免误伤。
- **只写 true，不写 false**；auto 状态（未经复核）的行一律不动。
- 真实库：411 条已复核非品牌相关 → 命中 27 条（基地名 19、公司全称 17、短名 4，含重叠），**已全部写入**（changed 27），审计留痕。写入后引用率从 1.03% 升至 6.84%——上升原因是标记补齐，不是 AI 新增引用。

**情感抽样盲评（A）**
- 抽样规则：`hash(round_no + citation_id)` 排序取前 N，规则固定，任何人重跑同一批。
- 双人独立标注：`sentiment_labels` 唯一键从 (project, citation) 放开放到 (project, citation, labeled_by)（迁移 `bd4e5f6a7b8c`）；同一人重复标只留最后一条。
- 共识 = 至少两人同档；分歧进 `disputed`，留待第三次标注或人工仲裁，不自动合并。
- **单人标注不计共识**：只标一次的行进 `pending_second`，既不进正向率分子也不进分母（此前实现误把单人标注计入共识，已修）。
- **共识不足 50 条不出正向率**，只报条数；比率只代表抽样所见，不外推全量。
- 品牌相关样本不足时放宽到全部已复核引用，返回体 `widened=true` 明示。

**负面风险预排序（C）**
- 词表只收明确贬损/投诉表述（差评、踩雷、退款难、骗局、虚假宣传等），命中即列 `hints`。
- 只决定「先看哪条」，**不进任何比率、不评分**；与抽样批分开返回（`sample` / `risk_scan`）。
- 真实库首轮：可抽池 119 条（已放宽），抽样 12 条，负面提示命中 0 条——当前没有明显负面表述，属事实呈现。

**跨轮累计共识（长期可用性）**
- 单轮 12 条、阈值 50 条，单轮永远出不了率；`GET /sentiment/consensus?round_no=12&cumulative=true` 把第 1..N 轮抽样批并集计算，同一引用重复抽中只计一次。
- 契约 `positive_rate` 改为**只认双人同档共识**：单人标注不再能决定验收数字，返回体加 `positive_basis`（`sampled` / `consensus_total` / `disputed` / `widened` / `reason`）。
- 未达 50 条共识时 `positive_rate=null`，`reason` 区分 `not_collected`（无人标）与 `insufficient_consensus`（标了但共识不够）。

## 2.10 来源类别的站点级判定

**为什么按站点判**：412 条已复核引用分布在 134 个站点，逐条标注追不上新增；站点身份是稳定的（知乎是社区、百科是参考站、1688 是电商），判一次覆盖整站。

**三档状态（`GET /citations/source-domains`）**
- `settled`：该站已有已知类别（人工判过），不再重复判。
- `suggested`：命中域名身份表，可一键采纳（`POST /citations/source-domains/apply`，审计 `citations.source_domain.apply`）；每条建议都带站点性质依据。
- `needs_review`：身份不明，按被引条数从多到少排队等人工判；**不自动给类别**。

**纪律**
- 判定依据是「站点本身是什么」，不看某篇文章写了什么；软文/招生/黄页这类身份模糊的站点进人工队列，不靠内容猜。
- 同站传播（`GET /citations/source-category-candidates`）只在同一站点族已有已知类别时才补齐 unknown/other 行，不新增判断、不反向覆盖已知类别。
- 真实库（首轮）：134 站 / 412 条引用，身份表可采纳 12 站（写入 38 条）；此后按站点自证证据再判 31 站（写入 70 条），累计 85 站已判、328 条引用（80%）有类别；剩 49 站待判（多为厂商产品站与无标题的企业站）。
- 契约被引 28 条随之变为：新闻 11、电商 10、内容平台 2、社交 1、未知 4（低可信合计 39.3%、未知 14.3%，两者分开披露）。

## 2.11 站点自证证据（人工判定的前置）

**为什么**：判站点性质不该靠人去开浏览器。`POST /citations/source-domains/evidence` 抓待判站点的**根域首页**标题与 meta description，外加一条被引页面的标题，缓存进 `source_domain_evidence`（迁移 `ce7f8a9b0c1d`），默认不重复抓，`refresh=true` 才重抓。

- 只存「站点自己写的话」，不存任何推断结论；判定仍由人做。
- 抓不到（403/超时/无标题）就记 `blocked`/`error`，留空，不猜。
- 真实库：80 个待判站点 → 70 个抓到自证（87.5%），10 个被反爬或无标题。
- 人工判定入口：`POST /citations/source-domains/classify`，body 为 `{decisions:[{site, category, note}]}`，一站点一条决定、整站生效，审计记 `citations.source_domain.classify`（含依据 note）；判回 `unknown` 被拒绝。

## 3. 披露项（不算分，只给事实）

- 排除样本明细：失败 / 待复核 / 无回答面 / 未完成，按失败码再细分。
- 竞品位次均值：品牌平均位次、最优竞品平均位次，各自附样本数。
- 引用页面类型分布：取已复核引用的 `page_type` 前 3 类。

## 4. 禁止事项

- 不得把提及率、首推率、信源覆盖、竞品位次、上下文质量相加或相乘得出「综合 GEO 得分」。
- 不得用「行业均值」「竞品基准」倒推评级；未采集到的基线一律写「未采集」。
- 不得把小样本（分母 < 10）的比率当成结论；报告只呈现数字，结论由人下。
