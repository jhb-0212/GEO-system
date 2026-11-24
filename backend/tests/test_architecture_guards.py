"""架构闸门：用测试锁住「不许再恶化」的三条规则。

为什么是闸门而不是重构：
api 层现有 41 个文件直接写 `select(`、220 处 `db.commit/execute`，一次性搬完不现实，
但「新的查询不许再写在 api」可以从今天开始生效。所以这里不做零容忍断言，而是
按文件比对基线：**只能变少、不能变多**。基线用 `GEO_ARCH_REGEN=1` 重新生成。

四条规则：
1. `services/**` 不得 `from app.api`（服务层反向依赖路由层会让预检无法在 worker/CLI 里跑）；
2. 每个 api 文件的 `select(` 次数不得超过基线（口径只许下沉，不许再分叉）；
3. 每个 api 文件的 `.status =` 直接赋值次数不得超过基线（状态迁移必须经 state_machine）；
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
STATUS_ASSIGN_PATTERN = re.compile(r"\.status\s*=\s*[^=]")


def _api_files() -> list[Path]:
    api_dir = APP_ROOT / "api"
    return sorted(path for path in api_dir.rglob("*.py") if path.name != "__init__.py")


def _counts() -> dict[str, dict[str, int]]:
    result = {}
    for path in _api_files():
        text = path.read_text(encoding="utf-8")
        result[path.relative_to(APP_ROOT).as_posix()] = {
            "select": len(SELECT_PATTERN.findall(text)),
            "status_assign": len(STATUS_ASSIGN_PATTERN.findall(text)),
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


def test_api_select_count_does_not_exceed_baseline():
    current = _counts()
    baseline = _baseline()
    if os.environ.get("GEO_ARCH_REGEN") == "1":
        BASELINE_PATH.write_text(
            json.dumps(current, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return
    regressions = []
    for file, counters in current.items():
        allowed = baseline.get(file, {"select": 0, "status_assign": 0})
        if counters["select"] > allowed.get("select", 0):
            regressions.append(
                f"{file}: select() {counters['select']} > 基线 {allowed.get('select', 0)}"
            )
    assert regressions == [], (
        "api 层新增了直接写库的查询，请把查询下沉到 services：\n" + "\n".join(regressions)
    )


def test_api_status_assignment_does_not_exceed_baseline():
    current = _counts()
    baseline = _baseline()
    if os.environ.get("GEO_ARCH_REGEN") == "1":
        return
    regressions = []
    for file, counters in current.items():
        allowed = baseline.get(file, {"select": 0, "status_assign": 0})
        if counters["status_assign"] > allowed.get("status_assign", 0):
            regressions.append(
                f"{file}: .status 直接赋值 {counters['status_assign']} > 基线 {allowed.get('status_assign', 0)}"
            )
    assert regressions == [], (
        "状态迁移必须经 services/state_machine，不能在 api 里直接赋值：\n" + "\n".join(regressions)
    )


MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations" / "versions"


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
