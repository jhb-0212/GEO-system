"""从「库表 ↔ 后端接口 ↔ 前端代理 ↔ 页面」四方交叉，生成链路能力矩阵与缺口清单。

用法（仓库根目录）：
    backend\\.venv\\Scripts\\python.exe backend\\scripts\\audit_capability.py
    backend\\.venv\\Scripts\\python.exe backend\\scripts\\audit_capability.py --strict   # 有缺口时退出码 1
    backend\\.venv\\Scripts\\python.exe backend\\scripts\\audit_capability.py --check --strict  # 不写文件，校验已提交矩阵
输出：
    docs/链路能力矩阵.md

数据来源（全部读真实产物，不靠人工摘抄）：
    1. 库内实际表结构        —— app.db.session.engine
    2. 接口路径与方法        —— docs/openapi.json
    3. 接口权限码            —— backend/app/api/*.py 里的 require_permission(...)
    4. 前端代理 kind         —— frontend/app/internal/workbench/data/route.ts
    5. 工作台页面 section    —— frontend/lib/workbench/navigation.ts
下表里的映射表是本脚本的"契约声明"：新表要接入时在这里登记，脚本会据此判定缺口。
"""

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

from sqlalchemy import text

BACKEND_DIR = Path(__file__).resolve().parents[1]
ROOT_DIR = BACKEND_DIR.parent
FRONTEND_DIR = ROOT_DIR / "frontend"
DOCS_DIR = ROOT_DIR / "docs"
OPENAPI_PATH = DOCS_DIR / "openapi.json"
DATA_ROUTE = FRONTEND_DIR / "app" / "internal" / "workbench" / "data" / "route.ts"
NAVIGATION = FRONTEND_DIR / "lib" / "workbench" / "navigation.ts"

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.db.session import engine  # noqa: E402

# ---------------------------------------------------------------- 映射声明

SYSTEM_LEVEL = {
    "users", "roles", "permissions", "role_permissions", "projects",
    "ai_engines", "ai_engine_entries",
}
MIGRATION_META = {"alembic_version"}

# 系统级表 → 全局接口段（/api/v1/<段>）
SYSTEM_RESOURCE: dict[str, str | None] = {
    "projects": "projects",
    "users": "auth",
    "ai_engines": "engines",
    "ai_engine_entries": "engines",
    "roles": None,
    "permissions": None,
    "role_permissions": None,
}

# 表 → 项目内接口资源段（openapi 里 /api/v1/projects/{project_id}/<slug>）
TABLE_RESOURCE: dict[str, str] = {
    "audit_logs": "audit-logs",
    "channel_aliases": "channels",
    "channels": "channels",
    "competitors": "competitors",
    "content_items": "contents",
    "content_plans": "plans",
    "content_reviews": "content-versions",
    "content_version_citations": "content-versions",
    "content_version_keywords": "content-versions",
    "content_version_questions": "content-versions",
    "content_versions": "content-versions",
    "evidence_files": "evidence",
    "faqs": "faqs",
    "keywords": "keywords",
    "leads": "leads",
    "materials": "materials",
    "media_quotes": "media-quotes",
    "metric_definitions": "metric-definitions",
    "monitoring_citations": "citations",
    "monitoring_rounds": "monitoring",
    "monitoring_samples": "monitoring",
    "monitoring_tasks": "monitoring",
    "project_members": "members",
    "public_pages": "pages",
    "brand_profiles": "brand-profile",
    "budget_approvals": "budget-approvals",
    "publish_accounts": "publish",
    "publish_attempts": "publish",
    "publish_receipts": "publish",
    "publish_tasks": "publish",
    "publish_visibility_checks": "stats",
    "question_keywords": "questions",
    "question_versions": "questions",
    "questions": "questions",
    "answer_fact_claims": "fact-claims",
    "channel_approvals": "channels",
    "citation_source_reviews": "citations",
    "content_version_facts": "content-versions",
    "correction_tasks": "correction-tasks",
    "crawler_events": "crawler-events",
    "fact_versions": "facts",
    "facts": "facts",
    "monitoring_execution_attempts": "monitoring",
    "monitoring_retest_plans": "monitoring",
    "monthly_report_snapshots": "stats",
    "oauth_authorization_states": "oauth",
    "oauth_connections": "oauth",
    "opportunities": "opportunities",
    "page_approvals": "page-approvals",
    "question_version_keywords": "questions",
    "stat_snapshots": "stats",
    "traffic_events": "traffic-events",
}

# 资源段 → 工作台 section（None = 没有工作台页面，如公开站）
RESOURCE_SECTION: dict[str, str | None] = {
    "audit-logs": "activity",
    "brand-profile": "brand",
    "budget-approvals": "budget",
    "channels": "channels",
    "citations": "samples",
    "competitors": "competitors",
    "content-versions": "reviews",
    "contents": "publishing",
    "evidence": "samples",
    "faqs": "faq",
    "keywords": "questions",
    "leads": "leads",
    "materials": "materials",
    "media-quotes": "quotes",
    "members": "members",
    "metric-definitions": "metrics",
    "monitoring": "monitoring",
    "pages": None,
    "plans": "plans",
    "publish": "publishing",
    "questions": "questions",
    "stats": "statistics",
    "engines": "engines",
    "projects": "projects",
    "fact-claims": "facts",
    "correction-tasks": "facts",
    "crawler-events": "site-diagnostics",
    "traffic-events": "site-diagnostics",
    "oauth": "publishing",
    "page-approvals": "publishing",
}

# 资源段 → 前端代理 kind（仅用于展示，不作为缺口判定）
RESOURCE_KIND: dict[str, str] = {
    "audit-logs": "(无独立 kind)",
    "brand-profile": "brand-profile",
    "budget-approvals": "budget-approvals / budget-review",
    "channels": "channels",
    "citations": "citations",
    "competitors": "competitors",
    "content-versions": "content-versions",
    "contents": "content-item / content-version-create",
    "evidence": "(无独立 kind)",
    "faqs": "faqs / faq",
    "keywords": "keywords / keyword",
    "leads": "(leads-export)",
    "materials": "materials",
    "media-quotes": "quotes / quote / quote-review",
    "members": "members / member / member-candidates",
    "metric-definitions": "metric-definitions / metric-definition",
    "monitoring": "rounds / tasks / samples",
    "pages": "(公开站，非工作台)",
    "plans": "plans / plan",
    "publish": "publish-tasks / publish-accounts",
    "questions": "questions / question / question-versions",
    "stats": "stats-overview 等 5 个",
    "fact-claims": "fact-claims",
    "correction-tasks": "correction-tasks",
    "crawler-events": "crawler-events",
    "traffic-events": "traffic-events",
    "oauth": "oauth",
    "page-approvals": "page-approvals",
}

# 后端模块文件 → 资源段
MODULE_RESOURCE: dict[str, str] = {
    "audit": "audit-logs",
    "budget_approvals": "budget-approvals",
    "channels": "channels",
    "citations": "citations",
    "competitors": "competitors",
    "content": "content-versions",
    "engines": "engines",
    "evidence": "evidence",
    "facts": "facts",
    "faqs": "faqs",
    "keywords": "keywords",
    "leads": "leads",
    "materials": "materials",
    "members": "members",
    "metrics": "metric-definitions",
    "monitoring": "monitoring",
    "opportunities": "opportunities",
    "oauth": "oauth",
    "page_approvals": "page-approvals",
    "pages": "pages",
    "plans": "plans",
    "projects": "projects",
    "publishing": "publish",
    "questions": "questions",
    "quotes": "media-quotes",
    "site_diagnostics": "site-diagnostics",
    "stats": "stats",
    "tasks": "tasks",
}

# 一个后端模块可能服务多个资源段；权限码按模块文件统计，这里只补多资源映射。
RESOURCE_MODULE: dict[str, str] = {
    "fact-claims": "facts",
    "correction-tasks": "facts",
    "crawler-events": "site_diagnostics",
    "traffic-events": "site_diagnostics",
}

# 明确豁免（数据由服务/Worker 写入，不对外提供逐条 CRUD 接口）
EXEMPT: dict[str, str] = {
    "import_batches": "导入批次，写入由导入脚本负责",
    "outbox_events": "事务性 Outbox，Worker 消费，不对外暴露",
    "monitoring_competitor_mentions": "竞品提及由监测流程落库，无独立维护接口",
    "monitoring_brand_mentions": "旧版品牌提及留档表，当前统计走样本聚合字段，无独立接口",
    "monitoring_execution_attempts": "任务执行尝试由 Worker 落库，属于执行审计，无对外 CRUD",
    "monitoring_source_profiles": "信源画像由引用归因流程落库，无独立维护接口",
}

# ---------------------------------------------------------------- 采集


def query(sql: str) -> list[tuple]:
    with engine.connect() as conn:
        return [tuple(row) for row in conn.execute(text(sql))]


def load_tables() -> tuple[list[str], set[str]]:
    tables = [
        row[0]
        for row in query(
            "select c.relname from pg_class c join pg_namespace n on n.oid=c.relnamespace "
            "where n.nspname='public' and c.relkind='r' order by c.relname"
        )
    ]
    with_project = {
        row[0]
        for row in query(
            "select table_name from information_schema.columns "
            "where table_schema='public' and column_name='project_id'"
        )
    }
    return tables, with_project


def load_permission_codes() -> set[str]:
    return {row[0] for row in query("select code from permissions")}


def load_openapi() -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """返回 (项目内资源段 → 方法集合, 全局路径 → 方法集合)。"""
    spec = json.loads(OPENAPI_PATH.read_text(encoding="utf-8"))
    project: dict[str, set[str]] = defaultdict(set)
    global_paths: dict[str, set[str]] = defaultdict(set)
    prefix = "/api/v1/projects/{project_id}/"
    for path, item in spec["paths"].items():
        methods = {m.upper() for m in item if m in {"get", "post", "patch", "delete", "put"}}
        if path.startswith(prefix):
            rest = path[len(prefix):]
            project[rest.split("/")[0]].update(methods)
        elif path.startswith("/api/v1/"):
            global_paths[path[len("/api/v1/"):]].update(methods)
    return project, global_paths


DECORATOR = re.compile(r"@router\.(get|post|patch|delete|put)\(\s*\"([^\"]*)\"")
PREFIX_RE = re.compile(r"APIRouter\(\s*prefix=[\"']([^\"']+)[\"']")
PERM_RE = re.compile(r"require_permission\(\s*\"([^\"]+)\"\s*\)")


def load_api_permissions() -> dict[str, dict[str, set[str]]]:
    """模块 → {"read": {码}, "write": {码}}。"""
    result: dict[str, dict[str, set[str]]] = {}
    for file in sorted((BACKEND_DIR / "app" / "api").glob("*.py")):
        if file.name.startswith("_"):
            continue
        source = file.read_text(encoding="utf-8")
        matches = list(DECORATOR.finditer(source))
        if not matches:
            continue
        read_codes: set[str] = set()
        write_codes: set[str] = set()
        for index, match in enumerate(matches):
            body = source[match.end(): matches[index + 1].start() if index + 1 < len(matches) else len(source)]
            codes = set(PERM_RE.findall(body))
            if match.group(1) == "get":
                read_codes |= codes
            else:
                write_codes |= codes
        result[file.stem] = {"read": read_codes, "write": write_codes}
    return result


def load_frontend() -> tuple[set[str], set[str]]:
    # 导航已抽到 navigation.ts；SECTION_META 的对象键是 page section 的唯一全集。
    # 旧实现只匹配 `id: "xxx"`，但 navigation.ts 早已改成键值对象，导致所有 section 被误报未注册。
    text = NAVIGATION.read_text(encoding="utf-8")
    start = text.find("const SECTION_META")
    end = text.find("} satisfies Record<Section", start)
    block = text[start:end] if start >= 0 and end > start else text
    sections = set(re.findall(r'^\s{2}"?([a-z][a-z-]*)"?:\s*\{', block, re.M))
    if not sections:
        # 兼容旧版导航写法；正常情况下不应走到这里。
        sections = set(re.findall(r'id:\s*"([a-z-]+)"', text))
    kinds = set(re.findall(r'kind\s*===\s*"([a-z-]+)"', DATA_ROUTE.read_text(encoding="utf-8")))
    kinds |= set(re.findall(r'"([a-z]+(?:-[a-z]+)*)"\s*,?\s*"', DATA_ROUTE.read_text(encoding="utf-8")))
    return sections, kinds


# ---------------------------------------------------------------- 组装


def render_methods(methods: set[str]) -> str:
    order = ["GET", "POST", "PATCH", "PUT", "DELETE"]
    return " / ".join(m for m in order if m in methods) or "—"


def build_matrix(
    tables: list[str],
    with_project: set[str],
    project_resources: dict[str, set[str]],
    global_paths: dict[str, set[str]],
    api_perms: dict[str, dict[str, set[str]]],
    valid_codes: set[str],
    sections: set[str],
) -> tuple[list[str], list[str], list[str]]:
    """返回 (表格行, 缺口清单, 未登记表)。纯函数，便于自检。"""
    module_by_resource = {resource: module for module, resource in MODULE_RESOURCE.items()}

    rows: list[str] = []
    gaps: list[str] = []
    unmapped: list[str] = []

    for table in tables:
        if table in MIGRATION_META:
            rows.append(f"| `{table}` | 迁移元数据 | — | — | — | — | 迁移元数据 |")
            continue
        if table in SYSTEM_LEVEL:
            resource = SYSTEM_RESOURCE.get(table)
            methods: set[str] = set()
            if resource:
                for path, verbs in global_paths.items():
                    if path == resource or path.startswith(resource + "/"):
                        methods |= verbs
            rows.append(
                f"| `{table}` | 系统级 | {render_methods(methods)} | — | 系统级，豁免页面 | — | 系统级 |"
            )
            continue

        resource = TABLE_RESOURCE.get(table)
        if table in EXEMPT:
            rows.append(
                f"| `{table}` | 项目级 | — | — | — | — | 豁免：{EXEMPT[table]} |"
            )
            continue
        if not resource:
            unmapped.append(table)
            rows.append(f"| `{table}` | 项目级 | 未登记 | — | 未登记 | — | **映射缺失** |")
            continue

        methods = project_resources.get(resource, set())
        module = RESOURCE_MODULE.get(resource) or module_by_resource.get(resource)
        codes_read = sorted(api_perms.get(module, {}).get("read", set())) if module else []
        codes_write = sorted(api_perms.get(module, {}).get("write", set())) if module else []
        section = RESOURCE_SECTION.get(resource)
        kind = RESOURCE_KIND.get(resource, "—")

        perm_text = " / ".join(filter(None, [
            f"读：{'、'.join(codes_read)}" if codes_read else "",
            f"写：{'、'.join(codes_write)}" if codes_write else "",
        ])) or "—"
        section_text = f"`{section}`" if section else "—"
        if section and section not in sections:
            section_text = f"`{section}`（前端未注册）"

        if not methods:
            verdict = "**缺接口**"
            gaps.append(f"`{table}` 无项目内接口（期望资源段 `{resource}`）")
        elif section is None:
            verdict = "完整（无工作台页面）"
        elif section not in sections:
            verdict = "**缺页面**"
            gaps.append(f"`{table}` 有接口但 section `{section}` 未在前端注册")
        else:
            verdict = "完整"

        for code in codes_read + codes_write:
            if code not in valid_codes:
                gaps.append(f"`{table}` 使用未入库权限码 `{code}`")

        rows.append(
            f"| `{table}` | 项目级 | {render_methods(methods)} | {perm_text} | {section_text} | {kind} | {verdict} |"
        )

    return rows, gaps, unmapped


def self_test() -> int:
    """用合成输入验证缺口判定确实会报错（避免"永远全绿"的假通过）。"""
    failures = 0
    sections, _kinds = load_frontend()
    required_sections = {"overview", "monitoring", "site-diagnostics", "statistics"}
    if not required_sections <= sections:
        missing = sorted(required_sections - sections)
        print(f"FAIL section parser：缺少 {missing}，解析结果={sorted(sections)}")
        failures += 1
    else:
        print(f"PASS section parser：解析到 {len(sections)} 个 section")

    cases = [
        ("resource 不存在", {"tmp_table": "no-such-resource"}, {"tmp_table"}),
        ("section 未注册", {"tmp_table": "competitors"}, {"tmp_table"}, {"competitors": {"GET"}}, set()),
        ("映射缺失", {"tmp_table": None}, {"tmp_table"}),
    ]
    for name, mapping, project_tables, *rest in cases:
        TABLE_RESOURCE.clear()
        TABLE_RESOURCE.update({"tmp_table": mapping["tmp_table"]} if mapping["tmp_table"] else {})
        rows, gaps, unmapped = build_matrix(
            ["tmp_table"],
            project_tables,
            rest[0] if rest else {},
            {},
            {},
            set(),
            rest[1] if len(rest) > 1 else {"competitors"},
        )
        ok = bool(gaps or unmapped)
        print(f"{'PASS' if ok else 'FAIL'} {name}：gaps={gaps} unmapped={unmapped}")
        failures += 0 if ok else 1
    return 1 if failures else 0


def main() -> int:
    if "--self-test" in sys.argv:
        return self_test()

    tables, with_project = load_tables()
    project_resources, global_paths = load_openapi()
    api_perms = load_api_permissions()
    valid_codes = load_permission_codes()
    sections, _kinds = load_frontend()

    rows, gaps, unmapped = build_matrix(
        tables, with_project, project_resources, global_paths, api_perms, valid_codes, sections
    )

    total = len(tables)
    project_count = sum(1 for t in tables if t in with_project)
    system_count = sum(1 for t in tables if t in SYSTEM_LEVEL)
    migration_count = sum(1 for t in tables if t in MIGRATION_META)
    complete = sum(1 for row in rows if row.rstrip().endswith("| 完整 |") or "| 完整（无工作台页面） |" in row)
    exempt = len(EXEMPT)

    lines = [
        "# 链路能力矩阵（由脚本从库、接口、前端三方交叉生成）",
        "",
        "> 生成脚本：`backend/scripts/audit_capability.py`。判定规则见文末，与文档描述不一致时以本表为准。",
        "",
        "## 核对结论",
        "",
        f"- 表总数：{total}（项目级 {project_count}、系统级 {system_count}、迁移元数据 {migration_count}）",
        f"- 链路完整：{complete} 张；豁免（服务/Worker 写入，无对外 CRUD）：{exempt} 张；缺口：{len(gaps)} 项",
        f"- 映射缺失（新表未在脚本登记）：{len(unmapped)} 张" + (f" —— {', '.join(f'`{t}`' for t in unmapped)}" if unmapped else ""),
        "",
        "## 逐表矩阵",
        "",
        "| 表 | 归属 | 接口方法 | 权限码 | 前端页面 | 代理 kind | 判定 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
        *rows,
        "",
        "## 缺口清单",
        "",
    ]
    lines += [f"- {gap}" for gap in gaps] if gaps else ["- 无"]
    lines += [
        "",
        "## 判定规则",
        "",
        "1. 项目级表必须有项目内接口（`/api/v1/projects/{project_id}/<资源段>` 至少一个方法），否则记「缺接口」。",
        "2. 有接口的项目级表必须有工作台 section，否则记「缺页面」；`public_pages` 等非工作台资源除外。",
        "3. `EXEMPT` 中的表由服务或 Worker 写入，不要求对外 CRUD 接口，逐条写明理由。",
        "4. 系统级表只核对全局接口，不要求工作台页面。",
        "5. 接口使用的权限码必须存在于库内 `permissions` 表，否则记缺口。",
        "6. 新增表时需在脚本顶部 `TABLE_RESOURCE`、`RESOURCE_SECTION`、`RESOURCE_KIND` 登记，未登记会出现在「映射缺失」里。",
        "",
    ]

    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    out = DOCS_DIR / "链路能力矩阵.md"
    generated = "\n".join(lines)

    if "--check" in sys.argv:
        if not out.is_file():
            print(f"MISSING {out}")
            return 1
        if out.read_text(encoding="utf-8") != generated:
            print(f"DRIFT {out}（实测 {total} 表 / 缺口 {len(gaps)} / 映射缺失 {len(unmapped)}）")
            return 1
        print(f"OK {out}（{total} 表 / 缺口 {len(gaps)} / 映射缺失 {len(unmapped)}）")
        return 1 if ("--strict" in sys.argv and (gaps or unmapped)) else 0

    out.write_text(generated, encoding="utf-8")

    print(f"已生成 {out}：{total} 张表，完整 {complete}、豁免 {exempt}、缺口 {len(gaps)}")
    for gap in gaps:
        print(f"  - {gap}")
    if unmapped:
        print("映射缺失：" + "、".join(unmapped))
    if "--strict" in sys.argv and (gaps or unmapped):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
