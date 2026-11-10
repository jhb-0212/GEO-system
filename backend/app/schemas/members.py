"""项目成员的请求模型。"""

import uuid

from pydantic import BaseModel

from app.models.enums import RoleCode


class MemberGrant(BaseModel):
    user_id: uuid.UUID
    role_code: RoleCode


class MemberRoleChange(BaseModel):
    role_code: RoleCode
