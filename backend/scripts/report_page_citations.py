"""对照「公司站登记页 × 被引用」：哪些已登记页面真的被 AI 引用过。

背景：公开站下线后，对外页面全在公司官网，`public_pages` 登记了 sitemap 里的真实页面
（当前 69 条，其中 60 条是问答式新闻稿）。但 `monitoring_citations` 里的引用只记录了
原始 URL 与域名，两者从没对过账——所以「某类问题开始被引用了」这件事一直看不出来。

本脚本只读不写：把引用 URL 归一到「域名 + 路径」，与登记页 URL 同一口径比对，输出：
1. 每篇登记稿被引用几次（0 次的也列出来，这才是绝大多数）；
2. 按题面类型（口碑/师资/就业/选址/课程/报名）汇总，看哪类内容开始被引；
3. 没对上的引用域名排行——这些是第三方来源，占比高说明官网还没进检索集。

用法（backend 目录下，先设 PYTHONPATH）：
    .\\.venv\\Scripts\\python.exe scripts\\report_page_citations.py
    .\\.venv\\Scripts\\python.exe scripts\\report_page_citations.py --json out.json
    .\\.venv\\Scripts\\python.exe scripts\\report_page_citations.py --only-cited

口径说明：归一化只做去 scheme、去 www.、小写、去尾斜杠、丢 query/fragment。
不把 https 与 http 视作不同页面（官网 https 证书主机名不匹配，登记 URL 多为 http），
否则同一页会因协议不同被判成两页，引用会漏计。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import MonitoringCitation, Project, PublicPage


def normalize(url: str | None) -> str:
    """把 URL 压成 `域名/路径`，用于跨页面比对。"""
    if not url:
        return ""
    value = url.strip().lower()
    if "://" not in value:
        value = f"https://{value}"
    parsed = urlparse(value)
    host = (parsed.hostname or "").removeprefix("www.").rstrip(".")
    path = parsed.path.rstrip("/") or "/"
    return f"{host}{path}"


# 题面分类：按标题关键词判断这篇稿在回答哪类问题。
# 顺序有意义——「就业吗/薪资」要先于泛化的「怎么样」，否则会被归进「其他」。
TOPIC_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("就业与薪资", re.compile(r"就业|薪资|工资|offer|入职|去向")),
    ("报名与费用", re.compile(r"报名|学费|费用|缴费|先学后付|条件|要求")),
    ("师资与课程", re.compile(r"师资|讲师|老师|课程|课时|班型|录播|小班|对比|区别")),
    ("口碑与可信度", re.compile(r"靠谱|专业吗|正规|可信|值得信赖|口碑|评价|认可|实力|怎么样|哪家好|踩坑")),
    ("选址与场地", re.compile(r"番禺|广州|深圳|选址|场地|地址|到校|交通")),
]


# 品牌名里自带「就业」二字（「AI数字人才就业实训基地」），不剥掉会把所有稿子都判成
# 「就业与薪资」。分类前先删品牌词，只看真正的问题部分。
BRAND_NOISE = re.compile(r"(广东省?|广州|深圳|番禺区?)?(AI)?数字人才就业(实训)?(基地|机构|企业|公司|中心|服务商|渠道)?")
BRAND_EXTRA = re.compile(r"(广东省?成才人工智能产业孵化有限公司|AIGC漫剧培训(服务)?(机构|公司|企业)?|AI技能就业班)")


def classify(title: str) -> str:
    cleaned = BRAND_EXTRA.sub(" ", title or "")
    cleaned = BRAND_NOISE.sub(" ", cleaned)
    for name, pattern in TOPIC_RULES:
        if pattern.search(cleaned):
            return name
    return "其他"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-code", default="gz-base", help="项目 code，默认 gz-base")
    parser.add_argument("--json", dest="json_path", help="把结果写成 JSON 到这个路径")
    parser.add_argument("--only-cited", action="store_true", help="只列被引用过的页面")
    args = parser.parse_args()

    engine = create_engine(settings.database_url)
    with Session(engine) as db:
        project = db.scalar(select(Project).where(Project.code == args.project_code))
        if project is None:
            print(f"找不到项目 {args.project_code}", file=sys.stderr)
            return 2

        pages = db.scalars(
            select(PublicPage).where(PublicPage.project_id == project.id)
        ).all()
        citations = db.scalars(
            select(MonitoringCitation).where(MonitoringCitation.project_id == project.id)
        ).all()

        # 页面归一索引；同一归一结果只保留第一条，避免登记表里重复 URL 把计数拆开。
        page_index: dict[str, PublicPage] = {}
        for page in pages:
            key = normalize(page.url)
            page_index.setdefault(key, page)

        cited: Counter[str] = Counter()
        unmatched_domains: Counter[str] = Counter()
        for citation in citations:
            key = normalize(citation.normalized_url or citation.raw_url)
            if key in page_index:
                cited[key] += 1
            else:
                # 前缀匹配兜住带参数/子路径的引用（如 /news/show-x.html?from=search）。
                for page_key in page_index:
                    if page_key != "/" and key.startswith(page_key):
                        cited[page_key] += 1
                        break
                else:
                    unmatched_domains[citation.domain or normalize(key).split("/")[0]] += 1

        topics: dict[str, dict[str, int]] = defaultdict(lambda: {"pages": 0, "cited_pages": 0, "citations": 0})
        rows = []
        for page in pages:
            key = normalize(page.url)
            count = cited.get(key, 0)
            topic = classify(page.title)
            topics[topic]["pages"] += 1
            topics[topic]["citations"] += count
            if count:
                topics[topic]["cited_pages"] += 1
            rows.append(
                {
                    "slug": page.slug,
                    "title": page.title,
                    "url": page.url,
                    "page_type": str(page.page_type),
                    "topic": topic,
                    "citations": count,
                }
            )

        rows.sort(key=lambda item: (-item["citations"], item["title"]))

        total_citations = len(citations)
        matched_citations = sum(cited.values())
        print(f"项目：{args.project_code}（{project.name}）")
        print(f"登记页：{len(pages)} 条    引用：{total_citations} 条")
        print(f"引用命中登记页：{matched_citations} 条    未命中：{total_citations - matched_citations} 条")
        print()
        print("按题面类型：")
        for topic, stat in sorted(topics.items(), key=lambda kv: (-kv[1]["citations"], kv[0])):
            print(
                f"  {topic:<8} 页 {stat['pages']:>3} 篇 / 被引 {stat['cited_pages']:>3} 篇"
                f" / 引用 {stat['citations']:>3} 条"
            )
        print()
        print("页面明细：")
        for row in rows:
            if args.only_cited and not row["citations"]:
                continue
            mark = f"{row['citations']:>3} 次" if row["citations"] else "    0 次"
            print(f"  {mark}  [{row['topic']}] {row['title']}")
        if unmatched_domains:
            print()
            print("未命中的引用域名（第三方来源）：")
            for domain, count in unmatched_domains.most_common(10):
                print(f"  {count:>3} 次  {domain}")

        if args.json_path:
            payload = {
                "project_code": args.project_code,
                "registered_pages": len(pages),
                "total_citations": total_citations,
                "matched_citations": matched_citations,
                "topics": dict(topics),
                "pages": rows,
                "unmatched_domains": dict(unmatched_domains),
            }
            Path(args.json_path).write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print()
            print(f"JSON 已写入 {args.json_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
