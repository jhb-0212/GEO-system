"""公司站登记页 × 引用 对照脚本的纯函数测试。

守两个真实踩过的坑：
1. URL 归一必须抹平 http/https 与尾斜杠——官网 https 证书主机名不匹配、登记用 http，
   不抹平会让同一页被判成两页，引用漏计；
2. 题面分类必须先剥掉品牌名——品牌名里自带「就业」二字，否则 60 篇稿子会全部落进
   「就业与薪资」，分类就变成摆设。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.report_page_citations import classify, normalize


def test_normalize_strips_scheme_www_trailing_slash_and_query() -> None:
    assert normalize("https://www.gdccai.com/news/show-3411058.html?from=search") == (
        "gdccai.com/news/show-3411058.html"
    )
    assert normalize("http://gdccai.com/news/show-3411058.html/") == (
        "gdccai.com/news/show-3411058.html"
    )
    assert normalize("www.gdccai.com/about/") == "gdccai.com/about"
    assert normalize(None) == ""
    assert normalize("") == ""


def test_normalize_keeps_root_path() -> None:
    assert normalize("https://www.gdccai.com/") == "gdccai.com/"


def test_classify_ignores_brand_name_employment_word() -> None:
    """品牌名含「就业」，不应把所有稿子都判成就业类。"""
    assert classify("广东省成才人工智能产业孵化有限公司专业吗靠谱吗") == "口碑与可信度"
    assert classify("广东省AI数字人才就业实训基地技术实力如何") == "口碑与可信度"


def test_classify_matches_real_question_part() -> None:
    assert classify("AI数字人才就业实训基地报名要求有哪些，先学后付方案可信吗") == "报名与费用"
    assert classify("AI数字人才就业实训基地师资力量强不强，讲师来自哪些企业？") == "师资与课程"
    assert classify("广东AI数字人才就业实训基地就业情况如何，AIGC班学员薪资揭秘") == "就业与薪资"
    assert classify("番禺区广东省成才人工智能产业孵化有限公司靠谱吗") == "口碑与可信度"


def test_classify_falls_back_to_other() -> None:
    assert classify("AI 大模型领航实训班") == "其他"
    assert classify("") == "其他"
