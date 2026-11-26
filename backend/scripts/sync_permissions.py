"""只补齐 RBAC 能力码与角色授权，不执行 `seed.py` 的其他初始化。

背景：`seed.py` 是完整种子（管理员账号、引擎目录、项目业务数据、FAQ、口径…）。
为一个新增能力码整份跑 `seed.py`，会把大量与本次变更无关的副作用一起带进来，
而且这些副作用里有创建账号、写业务种子这类不可静默重放的动作。

本脚本只做两件幂等的事，且都只增不删：

1. 把 `PERMISSION_CATALOG` 里新增的能力码写进 `permissions` 表；
2. 把 `ROLE_PERMISSIONS` 的 (角色, 能力) 授权写进 `role_permissions`。

**只增不删**意味着它不会撤销历史授权。当代码矩阵把某个能力从角色上收窄（例如
`metric.manage` 从 `editor` 移除）时，旧环境里那条授权仍会残留并继续生效，
必须显式传 `--revoke-stale` 才会按代码矩阵删除：脚本会先打印将删除的每一行，再删除，
不做静默清理。

用法（backend 目录）：
    python scripts/sync_permissions.py             # 补齐（幂等，可重复执行）
    python scripts/sync_permissions.py --check     # 只报告差异，不写库；有差异退出码 1
    python scripts/sync_permissions.py --revoke-stale   # 补齐 + 撤销代码矩阵已移除的授权
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import select  # noqa: E402

from app.core.permissions import PERMISSION_CATALOG, ROLE_PERMISSIONS  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.models import Permission, Role, RolePermission  # noqa: E402


def _load_state(session) -> tuple[set[str], set[str], set[tuple[str, str]]]:
    """返回 (库中能力码, 库中角色码, 库中 (角色码, 能力码) 授权对)。"""
    permission_codes = {row.code for row in session.scalars(select(Permission))}
    grants = {
        (role.code.value, permission.code)
        for role, permission in session.execute(
            select(Role, Permission)
            .join(RolePermission, RolePermission.role_id == Role.id)
            .join(Permission, Permission.id == RolePermission.permission_id)
        )
    }
    return permission_codes, grants


def _diff(session) -> tuple[set[str], set[tuple[str, str]], set[tuple[str, str]]]:
    """返回 (库缺失的能力码, 库缺失的授权对, 库中多余(代码矩阵已移除)的授权对)。"""
    permission_codes, grants = _load_state(session)
    catalog = {code for code, *_ in PERMISSION_CATALOG}
    matrix = {(role.value, code) for role, codes in ROLE_PERMISSIONS.items() for code in codes}
    matrix_roles = {role.value for role in ROLE_PERMISSIONS}

    missing_permissions = catalog - permission_codes
    # 缺失授权按「矩阵 - 库」直接算：能力码缺失时这条授权本来就插不进去，
    # 先补能力码、再补授权，两轮后自然收敛。
    missing_grants = matrix - grants
    stale_grants = {
        (role, code) for role, code in grants if role in matrix_roles and (role, code) not in matrix
    }
    return missing_permissions, missing_grants, stale_grants


def main() -> int:
    parser = argparse.ArgumentParser(description="只补齐 RBAC 能力码与角色授权")
    parser.add_argument("--check", action="store_true", help="只报告差异，不写库")
    parser.add_argument(
        "--revoke-stale",
        action="store_true",
        help="同时删除代码矩阵已移除、但库中仍残留的授权（逐行打印后再删）",
    )
    args = parser.parse_args()

    session = SessionLocal()
    try:
        missing_permissions, missing_grants, stale_grants = _diff(session)
        print("RBAC 授权同步：代码矩阵 vs 数据库")
        print(f"  库缺失能力码 {len(missing_permissions)} 个")
        for code in sorted(missing_permissions):
            print(f"    - {code}")
        print(f"  库缺失授权 {len(missing_grants)} 对")
        for role, code in sorted(missing_grants):
            print(f"    - {role} -> {code}")
        print(f"  库残留（矩阵已移除）授权 {len(stale_grants)} 对")
        for role, code in sorted(stale_grants):
            print(f"    - {role} -> {code}")

        if args.check:
            if missing_permissions or missing_grants or stale_grants:
                print("结论：存在差异（--check 不写库）。")
                return 1
            print("结论：库授权与代码矩阵一致。")
            return 0

        # 复用 seed.py 的两个幂等函数，避免第二套写入逻辑
        from scripts.seed import seed_permissions, seed_role_permissions

        created_permissions = seed_permissions(session)
        created_grants = seed_role_permissions(session)

        revoked = 0
        if args.revoke_stale and stale_grants:
            role_by_code = {row.code.value: row for row in session.scalars(select(Role))}
            permission_by_code = {row.code: row for row in session.scalars(select(Permission))}
            for role_code, permission_code in sorted(stale_grants):
                role = role_by_code.get(role_code)
                permission = permission_by_code.get(permission_code)
                if role is None or permission is None:
                    continue
                row = session.scalars(
                    select(RolePermission).where(
                        RolePermission.role_id == role.id,
                        RolePermission.permission_id == permission.id,
                    )
                ).first()
                if row is None:
                    continue
                print(f"  撤销 {role_code} -> {permission_code}")
                session.delete(row)
                revoked += 1

        session.commit()
        print(
            f"完成：能力码 +{created_permissions}，角色授权 +{created_grants}，撤销残留 {revoked}"
        )
        if stale_grants and not args.revoke_stale:
            print(
                "注意：仍有残留授权未撤销（代码矩阵已移除但库中保留）。确认后加 --revoke-stale 重跑。"
            )
        return 0
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    sys.exit(main())
