"""RBAC 权限漂移检查：代码矩阵 vs 数据库授权，只检查不修改。

背景：`scripts/seed.py` 的权限初始化只增不删——代码矩阵撤销某个能力后，
运行库里的旧授权仍可能残留并生效。本脚本在 CI 里把这种漂移显式暴露出来，
由人工决定“删库授权”还是“回退代码”，不做自动删除（防止误删运行时
动态授权的记录）。

检查项：
1. 库里存在、代码矩阵已撤销的 (角色, 能力) 授权对 —— 视为权限漂移，退出码 1；
2. 库里有、代码目录/矩阵没有的角色或能力码 —— 同样退出码 1；
3. 代码矩阵有、库里缺失的授权 —— 只输出 warning（seed 幂等可补齐，不算漂移）；
4. 指定 `--doc` 时，检查权限矩阵文档：已知语义行必须引用正确能力码，
   且文档中不得出现代码目录之外的能力码。

用法：
    python scripts/check_permission_drift.py
    python scripts/check_permission_drift.py --doc ../docs/权限矩阵.md
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.permissions import PERMISSION_CATALOG, ROLE_PERMISSIONS  # noqa: E402
from app.models import Permission, Role, RolePermission  # noqa: E402

# 权限矩阵里容易写错的“语义行 → 必须引用的能力码”。
DOC_SEMANTIC_RULES = (
    ("项目资料确认", "project.confirm"),
    ("/projects/{id}/confirm", "project.confirm"),
)
CODE_SPAN_RE = re.compile(r"`([^`]+)`")
CAPABILITY_CODE_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")


def _gha(level: str, message: str) -> None:
    # GitHub Actions 工作流命令：::error / ::warning 注解会直接显示在 PR 页面上。
    print(f"::{level}::{message}")


def check_doc(
    path: Path, catalog_codes: set[str], capability_prefixes: set[str]
) -> list[str]:
    """检查权限矩阵文档的语义引用，不解析角色列，避免把展示文案当成授权事实。"""
    if not path.is_file():
        return [f"权限矩阵文档不存在：{path}"]

    errors: list[str] = []
    seen_codes: set[str] = set()
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        for label, code in DOC_SEMANTIC_RULES:
            if label in line and code not in line:
                errors.append(f"{path}:{lineno}: `{label}` 应引用 `{code}`")
        for span in CODE_SPAN_RE.findall(line):
            code = span.strip()
            if not CAPABILITY_CODE_RE.fullmatch(code):
                continue
            if code.split(".", 1)[0] not in capability_prefixes:
                continue
            seen_codes.add(code)
            if code not in catalog_codes:
                errors.append(f"{path}:{lineno}: 能力码 `{code}` 不在代码目录中")
    missing = sorted(catalog_codes - seen_codes)
    if missing:
        # 文档是当前权限矩阵的说明，不要求覆盖全部系统级能力；缺失只提示，不改授权事实。
        print(f"  [DOC WARN] 权限矩阵未覆盖能力码：{', '.join(missing)}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="RBAC 权限漂移与权限矩阵文档检查")
    parser.add_argument(
        "--doc",
        type=Path,
        help="可选：权限矩阵 Markdown 路径；提供时同时检查文档语义",
    )
    args = parser.parse_args()

    engine = create_engine(settings.database_url, pool_pre_ping=True)
    with Session(engine) as session:
        roles = {row.code.value: row for row in session.scalars(select(Role))}
        perms = {row.code: row for row in session.scalars(select(Permission))}
        pairs = {
            (role.code.value, perm.code)
            for role, perm in session.execute(
                select(Role, Permission)
                .join(RolePermission, RolePermission.role_id == Role.id)
                .join(Permission, Permission.id == RolePermission.permission_id)
            )
        }

    catalog_codes = {code for code, *_ in PERMISSION_CATALOG}
    matrix_roles = {role.value for role in ROLE_PERMISSIONS}
    matrix_pairs = {
        (role.value, code) for role, codes in ROLE_PERMISSIONS.items() for code in codes
    }

    orphan_pairs = sorted(
        (role, code)
        for role, code in pairs
        if role in matrix_roles and (role, code) not in matrix_pairs
    )
    orphan_roles = sorted(set(roles) - matrix_roles)
    orphan_perms = sorted(set(perms) - catalog_codes)
    missing_pairs = sorted(
        (role, code)
        for role, code in matrix_pairs
        if role in roles and code in perms and (role, code) not in pairs
    )
    doc_errors = (
        check_doc(args.doc, catalog_codes, {code.split(".", 1)[0] for code in catalog_codes})
        if args.doc
        else []
    )

    drift = bool(orphan_pairs or orphan_roles or orphan_perms or doc_errors)

    print("权限漂移检查：代码矩阵 vs 数据库授权")
    print(f"  矩阵角色 {len(matrix_roles)}，库角色 {len(roles)}；矩阵授权对 {len(matrix_pairs)}，库授权对 {len(pairs)}")
    if orphan_pairs:
        for role, code in orphan_pairs:
            msg = f"权限漂移：库中 {role} 仍持有 {code}，但代码矩阵已撤销（seed 只增不删，需人工决定删库授权或回退代码）"
            _gha("error", msg)
            print("  [DRIFT] " + msg)
    if orphan_roles:
        msg = f"角色漂移：库中存在代码矩阵未定义的角色 {', '.join(orphan_roles)}"
        _gha("error", msg)
        print("  [DRIFT] " + msg)
    if orphan_perms:
        msg = f"能力漂移：库中存在代码目录未定义的能力码 {', '.join(orphan_perms)}"
        _gha("error", msg)
        print("  [DRIFT] " + msg)
    if missing_pairs:
        for role, code in missing_pairs:
            msg = f"库中缺少矩阵授权 {role}->{code}（seed 幂等可补齐，无需人工处理）"
            _gha("warning", msg)
            print("  [WARN] " + msg)
    for error in doc_errors:
        _gha("error", error)
        print("  [DOC] " + error)

    if drift:
        print("结论：检测到权限漂移或权限矩阵文档错误，退出码 1。请人工决策：删除库中多余授权，或回退代码矩阵，并修正文档。")
        return 1
    print("结论：代码矩阵与库授权一致（或仅存在可补齐的缺失），检查通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
