"""架构闸门：用测试锁住「不许再恶化」的四条规则。

为什么是闸门而不是重构：api 层历史上直接写库、直接改状态的地方太多，一次性搬完不现实，
但「新的查询不许再写在 api」「新的状态写入不许绕过状态机」可以从今天开始生效。
所以这里不做零容忍断言，而是按文件比对基线：**只能变少、不能变多**。
基线用 `GEO_ARCH_REGEN=1` 重新生成。

四条规则：
1. `services/**` 不得 `from app.api`（服务层反向依赖路由层会让预检无法在 worker/CLI 里跑）；
2. 每个文件的 `select(` 次数不得超过基线（口径只许下沉到 services，不许再分叉）；
3. 状态写入必须经 `state_machine`：api 与 services **都扫**，
   `.status =` 的右手边（前后各两行窗口内）必须出现 `ensure_`；
   确实不是迁移的写入（如「条目状态是当前版本的镜像」）要显式登记在
   `BARE_STATUS_EXEMPTIONS` 并写明理由，且每个文件只允许登记一次的条数上限。
   —— 只扫 api 是漏洞：状态写入一搬进 service，这个闸门就看不见了。
4. 模型里的每张表都必须出现在迁移链里（历史上靠 `scripts/create_*_tables.py` 建过 12 张表，
   新库跑完 `alembic upgrade head` 会缺表，整条链路 500）。
"""

import json
import os
import re
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1] / "app"
BASELINE_PATH = Path(__file__).resolve().parent / "architecture_baseline.json"

SELECT_PATTERN = re.compile(r"\bselect\(")
STATUS_ASSIGN_PATTERN = re.compile(r"\.\w*status\s*=\s*[^=]")
ENSURE_PATTERN = re.compile(r"\bensure_[a-z_]+\(")
# R-01 起，状态写入统一经 todo_clock 的 apply_* 入口（内部仍调 ensure_*）。
# 闸门接受这两种"经过状态机"的写法；apply_* 内部是否真的调用 ensure_* 由
# test_todo_clock_applies_call_state_machine 反向锁死，避免入口变成逃生舱。
STATE_GUARDED_PATTERN = re.compile(
    r"\b(?:ensure_[a-z_]+|apply_(?:publish|task|fact|parse|candidate)_status)\("
)

# 不是状态迁移、但确实要写 .status 的地方。键是相对 app/ 的路径，值是 (理由, 允许条数)。
BARE_STATUS_EXEMPTIONS: dict[str, tuple[str, int]] = {
    "services/content_status.py": (
        "条目状态是当前版本的镜像，不是独立迁移：版本状态已过 state_machine，"
        "这里只把它同步到列表页展示的条目上，避免条目与版本状态分叉。",
        1,
    ),
    "services/alerts.py": (
        "webhook_status 记的是「外部 webhook 送达结果」，不是业务状态机，"
        "取值 not_configured / sent / failed 由推送回执决定，没有迁移语义。",
        1,
    ),
    "services/reachability.py": (
        "last_reachability_status 记的是最近一次探测的 HTTP 状态码，是观测数据，"
        "不是状态机的状态字段。",
        1,
    ),
}


def _app_files() -> list[Path]:
    files: list[Path] = []
    for sub in ("api", "services"):
        files.extend(p for p in (APP_ROOT / sub).rglob("*.py") if p.name != "__init__.py")
    return sorted(files)


def _status_assignments(lines: list[str]) -> list[int]:
    """返回 `x.status =` / `x.parse_status =` 这类属性赋值的行号（0 基）。

    跳过注释行与 docstring 内部：口径只看真正写属性的代码，说明文字里出现的
    `review_status = 'manual_confirmed'` 不算写入。字段名不限于 status —— 只扫 .status
    会漏掉 parse_status / approval_status 这些同样代表生命周期状态的字段（真实踩过）。
    """
    hits: list[int] = []
    in_docstring = False
    for index, line in enumerate(lines):
        if '"""' in line:
            # 同一行成对的 docstring（"""..."""）不算进入区间
            in_docstring = line.count('"""') % 2 == 1 and not in_docstring
            continue
        if in_docstring:
            continue
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if STATUS_ASSIGN_PATTERN.search(line):
            hits.append(index)
    return hits


def _counts() -> dict[str, dict[str, int]]:
    result = {}
    for path in _app_files():
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()
        hits = _status_assignments(lines)
        bare = 0
        for index in hits:
            # 前后各两行：`ensure_x(...)` 常和赋值分行写（多行实参、条件表达式）
            window = "\n".join(lines[max(0, index - 2) : index + 3])
            if not STATE_GUARDED_PATTERN.search(window):
                bare += 1
        result[path.relative_to(APP_ROOT).as_posix()] = {
            "select": len(SELECT_PATTERN.findall(text)),
            "status_assign": len(hits),
            "status_bare": bare,
        }
    return result


def _baseline() -> dict[str, dict[str, int]]:
    if not BASELINE_PATH.exists():
        return {}
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


def test_services_do_not_import_api_layer():
    offenders = []
    for path in (APP_ROOT / "services").rglob("*.py"):
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith("from app.api") or stripped.startswith("import app.api"):
                offenders.append(f"{path.relative_to(APP_ROOT).as_posix()}:{line_no}")
    assert offenders == [], f"服务层不得反向依赖 api 层：{offenders}"


def test_select_count_does_not_exceed_baseline():
    current = _counts()
    baseline = _baseline()
    if os.environ.get("GEO_ARCH_REGEN") == "1":
        BASELINE_PATH.write_text(
            json.dumps(current, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return
    regressions = []
    for file, counters in current.items():
        allowed = baseline.get(file, {})
        if counters["select"] > allowed.get("select", 0):
            regressions.append(
                f"{file}: select() {counters['select']} > 基线 {allowed.get('select', 0)}"
            )
    assert regressions == [], (
        "新增了直接写库的查询，请把查询下沉到 services：\n" + "\n".join(regressions)
    )


def test_status_assignment_count_does_not_exceed_baseline():
    current = _counts()
    baseline = _baseline()
    if os.environ.get("GEO_ARCH_REGEN") == "1":
        return
    regressions = []
    for file, counters in current.items():
        allowed = baseline.get(file, {})
        if counters["status_assign"] > allowed.get("status_assign", 0):
            regressions.append(
                f"{file}: .status 赋值 {counters['status_assign']} > 基线 {allowed.get('status_assign', 0)}"
            )
    assert regressions == [], "状态写入变多了，先看是否该走 state_machine：\n" + "\n".join(regressions)


def test_status_writes_go_through_state_machine():
    """api 与 services 都扫：`.status =` 必须紧邻 `ensure_*`，否则就是绕过状态机。

    这是第 3 条规则真正起作用的地方——只比总数会让「把赋值从 api 挪到 service」看起来
    没有变差，实际上闸门已经失效。
    """
    current = _counts()
    if os.environ.get("GEO_ARCH_REGEN") == "1":
        return
    problems = []
    for file, counters in current.items():
        bare = counters["status_bare"]
        if bare == 0:
            continue
        if file not in BARE_STATUS_EXEMPTIONS:
            problems.append(f"{file}: {bare} 处 .status 赋值没经 state_machine，且未登记豁免")
            continue
        reason, limit = BARE_STATUS_EXEMPTIONS[file]
        if bare > limit:
            problems.append(f"{file}: 裸赋值 {bare} 处 > 豁免上限 {limit}（{reason}）")
    assert problems == [], (
        "状态迁移必须经 services/state_machine（或登记为镜像同步）：\n" + "\n".join(problems)
    )


def test_bare_status_exemptions_are_still_justified():
    """豁免清单不能成为垃圾桶：登记的文件必须仍然真的存在裸赋值，且条数不超上限。"""
    current = _counts()
    stale = []
    for file, (reason, limit) in BARE_STATUS_EXEMPTIONS.items():
        counters = current.get(file)
        if counters is None:
            stale.append(f"{file}: 文件已不存在")
            continue
        if counters["status_bare"] == 0:
            stale.append(f"{file}: 已无裸赋值，请从豁免清单移除（{reason}）")
    assert stale == [], "豁免清单需要清理：\n" + "\n".join(stale)


STATE_MACHINE_PATH = APP_ROOT / "services" / "state_machine.py"
TODO_CLOCK_PATH = APP_ROOT / "services" / "todo_clock.py"
MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations" / "versions"


def test_todo_clock_applies_call_state_machine():
    """apply_* 是状态写入的统一入口，内部必须真的调 ensure_*，不能绕过去。

    否则把 `.status =` 换成 `apply_x_status(...)` 就成了绕过状态机的逃生舱。
    """
    text = TODO_CLOCK_PATH.read_text(encoding="utf-8")
    bodies: dict[str, str] = {}
    for match in re.finditer(r"\ndef (apply_[a-z_]+)\(", text):
        end = text.find("\ndef ", match.end())
        bodies[match.group(1)] = text[match.start() : end if end != -1 else len(text)]
    missing = [name for name, body in bodies.items() if not ENSURE_PATTERN.search(body)]
    assert bodies, "todo_clock 必须提供 apply_* 写入口"
    assert missing == [], f"以下 apply_* 没有调用 ensure_*：{missing}"


def test_every_transition_table_has_an_ensure_entry():
    """每张 *_TRANSITIONS 都要有一个 ensure_* 入口函数用它。

    否则表只是"写在那儿"：调用方要么绕过去裸赋值，要么根本没有校验入口。
    历史上有 5 张表是这种状态（media_order / opportunity_suggestion /
    knowledge_parse / knowledge_candidate 都没有 ensure_*），等于白建。
    """
    text = STATE_MACHINE_PATH.read_text(encoding="utf-8")
    tables = re.findall(r"\n([A-Z][A-Z0-9_]*_TRANSITIONS): dict\[", text)
    bodies: dict[str, str] = {}
    for match in re.finditer(r"\ndef (ensure_[a-z_]+)\(", text):
        end = text.find("\ndef ", match.end())
        bodies[match.group(1)] = text[match.start() : end if end != -1 else len(text)]
    missing = [table for table in tables if not any(table in body for body in bodies.values())]
    assert missing == [], (
        "以下迁移表没有任何 ensure_* 入口（表建了但没人用，等于白建）：\n" + "\n".join(missing)
    )


def test_every_model_table_is_covered_by_migrations():
    """每张表都要在迁移链里出现，否则全新部署会缺表。

    只查表名是否出现在某个迁移文件里：口径宽松但足够挡住「只写脚本、不写迁移」这一类问题。
    """
    import app.models  # noqa: F401  注册所有模型
    from app.db.base import Base

    migrations_text = "\n".join(
        path.read_text(encoding="utf-8") for path in MIGRATIONS_DIR.glob("*.py")
    )
    missing = sorted(name for name in Base.metadata.tables if name not in migrations_text)
    assert missing == [], (
        "以下表没有任何迁移覆盖，请补 alembic 迁移（不要用 scripts/create_*_tables.py 绕过）：\n"
        + "\n".join(missing)
    )
