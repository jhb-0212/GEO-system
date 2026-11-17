"""角色能力解析的 fail-closed 行为。"""

from sqlalchemy import delete, select

from app.models import Role, RolePermission
from app.models.enums import RoleCode
from app.services.access import role_permission_codes


def test_empty_role_permission_mapping_does_not_fall_back_to_code_matrix(db):
    """role_permissions 已有数据时，某角色空映射是明确收窄，不能回退代码矩阵。"""
    role = db.scalar(select(Role).where(Role.code == RoleCode.VIEWER))
    assert role is not None

    db.execute(delete(RolePermission).where(RolePermission.role_id == role.id))
    db.flush()

    assert role_permission_codes(db, role) == frozenset()
