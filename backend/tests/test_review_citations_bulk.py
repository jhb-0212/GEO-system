"""批量复核脚本的两个关键约束：权限守卫与 URL 域名解析。

守卫的语义必须与 `PATCH /citations/{id}` 一致：只有本项目的 `evidence.review`
持有者（project_admin / reviewer）或被系统管理员才能改复核状态。脚本化批量操作
最容易出的问题就是"顺手把权限绕过去"，所以这条单独锁。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.enums import RoleCode
from scripts.review_citations_bulk import _check_permission, _domain_of


def test_domain_of_prefers_stored_value() -> None:
    assert _domain_of("https://zhuanlan.zhihu.com/p/1", "ZHuanlan.ZhiHu.com") == "zhuanlan.zhihu.com"


def test_domain_of_falls_back_to_hostname() -> None:
    assert _domain_of("https://zhuanlan.zhihu.com/p/1", None) == "zhuanlan.zhihu.com"
    assert _domain_of("http://gz.bendibao.com/edu/1.shtm", "") == "gz.bendibao.com"


def test_domain_of_survives_broken_url() -> None:
    assert _domain_of("not-a-url", None) == ""


def test_check_permission_allows_reviewer(db, project_factory, user_factory, member_factory) -> None:
    project = project_factory("perm-rv")
    user = user_factory("u-rv")
    member_factory(project, user, RoleCode.REVIEWER)
    assert _check_permission(db, user, project) is None


def test_check_permission_allows_system_admin(db, project_factory, user_factory) -> None:
    project = project_factory("perm-adm")
    user = user_factory("u-adm", is_system_admin=True)
    assert _check_permission(db, user, project) is None


def test_check_permission_denies_editor(db, project_factory, user_factory, member_factory) -> None:
    project = project_factory("perm-ed")
    user = user_factory("u-ed")
    member_factory(project, user, RoleCode.EDITOR)
    reason = _check_permission(db, user, project)
    assert reason is not None and "evidence.review" in reason


def test_check_permission_denies_non_member(db, project_factory, user_factory) -> None:
    project = project_factory("perm-out")
    user = user_factory("u-out")
    reason = _check_permission(db, user, project)
    assert reason is not None and "不是项目" in reason
