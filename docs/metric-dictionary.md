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
- **已知缺口**：重判前约六成已复核引用的 `page_type` 是 `other`；跑一轮 `page-type-r1` 规则重判后降至约三成（真实库 412 条：other 247→136，article 121→217）。剩余 other 是 URL 路径与标题都无强信号的长尾站，矩阵页仍会提示该缺口——**宁可不判，也不把长尾硬塞进某个形态**。
- **重判规则**：`page-type-r1` 按「URL 路径 → 站点 → 标题」顺序命中（`/question`、`/rank`、`/course`、`douyin`、公众号 `/s?` 等），每条写 `classification_rule_version` 与命中规则；只重判 `page_type=other`，`page_type_source=manual` 的行永不覆盖。预览接口 `GET /citations/page-type-preview` 不写库，`POST /citations/page-type-reclassify` 才写，并落审计 `citations.page_type.reclassify`。

## 3. 披露项（不算分，只给事实）

- 排除样本明细：失败 / 待复核 / 无回答面 / 未完成，按失败码再细分。
- 竞品位次均值：品牌平均位次、最优竞品平均位次，各自附样本数。
- 引用页面类型分布：取已复核引用的 `page_type` 前 3 类。

## 4. 禁止事项

- 不得把提及率、首推率、信源覆盖、竞品位次、上下文质量相加或相乘得出「综合 GEO 得分」。
- 不得用「行业均值」「竞品基准」倒推评级；未采集到的基线一律写「未采集」。
- 不得把小样本（分母 < 10）的比率当成结论；报告只呈现数字，结论由人下。
