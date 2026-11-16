"""初始化种子数据：角色、AI 引擎目录、首期试点项目、渠道目录、6 道标准问题、指标口径。

特点：可重复执行（重复运行不会产生重复数据），只补缺失的，不覆盖已有业务改动。

用法（在 backend 目录下）：
    .venv\\Scripts\\python.exe scripts\\seed.py
    .venv\\Scripts\\python.exe scripts\\seed.py --technical-baseline
"""

import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from passlib.context import CryptContext  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.core.permissions import PERMISSION_CATALOG, ROLE_PERMISSIONS  # noqa: E402
from app.models import (  # noqa: E402
    AiEngine,
    AiEngineEntry,
    Channel,
    MetricDefinition,
    Permission,
    Project,
    ProjectMember,
    Question,
    QuestionVersion,
    Role,
    RolePermission,
    User,
)
from app.models.enums import (  # noqa: E402
    ChannelCategory,
    ChannelStatus,
    EngineEntryType,
    MetricStatus,
    ProjectStatus,
    QuestionStatus,
    QuestionType,
    RoleCode,
)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

PROJECT_CODE = "gz-base"
PROJECT_NAME = "广州基地"

ROLE_SEED = [
    (RoleCode.SYS_ADMIN, "系统管理员", "创建项目、维护引擎目录、系统级配置；不默认读写项目业务数据"),
    (RoleCode.PROJECT_ADMIN, "项目管理员", "管理本项目成员，只能授予 editor/reviewer/viewer/lead_ops"),
    (RoleCode.EDITOR, "运营/编辑", "题库、监测任务、内容、发布任务、渠道台账"),
    (RoleCode.REVIEWER, "审核", "内容审批与证据复核，不改正文、不发布"),
    (RoleCode.VIEWER, "只读", "只读查看，所有写操作拒绝；导出需 export.data 并留痕"),
    (RoleCode.LEAD_OPS, "招生/客服", "仅本项目线索的读写，其他业务数据不可见"),
]

# 开发/联调用的项目角色账号；生产必须显式设置 SEED_USER_PASSWORD，不落日志。
# 已存在账号只补项目成员关系，不改密码、不改显示名，保证 seed 幂等。
ROLE_USER_SEED = [
    ("geo_editor", "运营编辑（seed）", RoleCode.EDITOR),
    ("geo_reviewer", "审核（seed）", RoleCode.REVIEWER),
    ("geo_lead_ops", "招生客服（seed）", RoleCode.LEAD_OPS),
    ("geo_viewer", "只读（seed）", RoleCode.VIEWER),
]
ROLE_USER_PASSWORD_ENV = "SEED_USER_PASSWORD"
DEV_ROLE_USER_PASSWORD = "geo-user-dev"

ENGINE_SEED = [
    ("doubao", "豆包", "字节跳动", "网页端与应用端入口需分别核验；支持联网搜索"),
    ("yuanbao", "腾讯元宝", "腾讯", "微信/网页入口需分别核验；支持联网搜索"),
    ("deepseek", "DeepSeek", "深度求索", "网页端与官方 API 分别采样"),
    ("wenxin", "百度文心", "百度", "网页端与官方 API 分别采样"),
]

# 渠道目录：按方案 4.8 的类别配置，code 用稳定的英文短码
CHANNEL_SEED = [
    ("own-site", "基地官网", ChannelCategory.OWN_SITE, "gz-base.com"),
    ("own-course", "课程页", ChannelCategory.OWN_SITE, None),
    ("own-faq", "FAQ", ChannelCategory.OWN_SITE, None),
    ("own-case", "作品案例", ChannelCategory.OWN_SITE, None),
    ("wechat-mp", "微信公众号", ChannelCategory.CONTENT_PLATFORM, "mp.weixin.qq.com"),
    ("zhihu", "知乎", ChannelCategory.CONTENT_PLATFORM, "zhihu.com"),
    ("xiaohongshu", "小红书", ChannelCategory.CONTENT_PLATFORM, "xiaohongshu.com"),
    ("baijiahao", "百家号", ChannelCategory.CONTENT_PLATFORM, "baijiahao.baidu.com"),
    ("toutiao", "头条号", ChannelCategory.CONTENT_PLATFORM, "toutiao.com"),
    ("sohu", "搜狐号", ChannelCategory.CONTENT_PLATFORM, "sohu.com"),
    ("netease", "网易号", ChannelCategory.CONTENT_PLATFORM, "163.com"),
    ("tencent-open", "腾讯内容开放平台", ChannelCategory.CONTENT_PLATFORM, "om.qq.com"),
    ("weibo", "微博", ChannelCategory.CONTENT_PLATFORM, "weibo.com"),
    ("channels-video", "视频号", ChannelCategory.VIDEO, "channels.weixin.qq.com"),
    ("douyin", "抖音", ChannelCategory.VIDEO, "douyin.com"),
    ("bilibili", "哔哩哔哩", ChannelCategory.VIDEO, "bilibili.com"),
    ("kuaishou", "快手", ChannelCategory.VIDEO, "kuaishou.com"),
    ("zcool", "站酷", ChannelCategory.VIDEO, "zcool.com.cn"),
    ("csdn", "CSDN", ChannelCategory.COMMUNITY, "csdn.net"),
    ("juejin", "稀土掘金", ChannelCategory.COMMUNITY, "juejin.cn"),
    ("woshipm", "人人都是产品经理", ChannelCategory.COMMUNITY, "woshipm.com"),
    ("baike-baidu", "百度百科", ChannelCategory.ENCYCLOPEDIA, "baike.baidu.com"),
    ("baike-sogou", "搜狗百科", ChannelCategory.ENCYCLOPEDIA, "baike.sogou.com"),
    ("wenku-baidu", "百度文库", ChannelCategory.ENCYCLOPEDIA, "wenku.baidu.com"),
    ("zhidao-baidu", "百度知道", ChannelCategory.ENCYCLOPEDIA, "zhidao.baidu.com"),
    ("dayoo", "广州日报大洋网", ChannelCategory.LOCAL_MEDIA, "dayoo.com"),
    ("southcn", "南方网", ChannelCategory.LOCAL_MEDIA, "southcn.com"),
    ("nanfangplus", "南方+", ChannelCategory.LOCAL_MEDIA, "nfplus.com"),
    ("ycwb", "羊城晚报金羊网", ChannelCategory.LOCAL_MEDIA, "ycwb.com"),
    ("gztv", "广州广播电视台", ChannelCategory.LOCAL_MEDIA, "gztv.com"),
    ("36kr", "36氪", ChannelCategory.INDUSTRY_MEDIA, "36kr.com"),
    ("tmtpost", "钛媒体", ChannelCategory.INDUSTRY_MEDIA, "tmtpost.com"),
    ("jiqizhixin", "机器之心", ChannelCategory.INDUSTRY_MEDIA, "jiqizhixin.com"),
    ("qbitai", "量子位", ChannelCategory.INDUSTRY_MEDIA, "qbitai.com"),
    ("leiphone", "雷峰网", ChannelCategory.INDUSTRY_MEDIA, "leiphone.com"),
    ("partner-school", "合作院校官网", ChannelCategory.INSTITUTION, None),
    ("partner-assoc", "行业协会官网", ChannelCategory.INSTITUTION, None),
    ("public-employment", "公共就业平台", ChannelCategory.INSTITUTION, None),
    ("company-careers", "企业招聘官网", ChannelCategory.INSTITUTION, None),
    ("boss", "BOSS 直聘", ChannelCategory.INSTITUTION, "zhipin.com"),
    ("zhaopin", "智联招聘", ChannelCategory.INSTITUTION, "zhaopin.com"),
    ("51job", "前程无忧", ChannelCategory.INSTITUTION, "51job.com"),
]

# 6 道标准问题先用占位文本建立版本链，真实问法待运营确认后按新版本追加，不改旧版本。
# 五元组：code、题型、占位问法、人群、意图。
# 早期 seed 把“招生咨询/课程咨询…”写进了 audience，实际那是意图；这里保留
# LEGACY_AUDIENCE_BY_CODE 仅用于把历史 seed 行迁移成正确的 audience + intent，
# 已经人工改过 audience 的行不会被覆盖。
QUESTION_SEED = [
    ("Q01", QuestionType.BRAND, "【占位待定】广州基地全称与主营方向是什么？", "零基础转行者", "了解基地资质与主营方向"),
    ("Q02", QuestionType.BRAND, "【占位待定】广州基地的实训课程有哪些、怎么报名？", "意向学员", "咨询课程内容与报名方式"),
    ("Q03", QuestionType.BRAND, "【占位待定】广州基地地址、联系方式与资质如何核验？", "决策期学员及家长", "核验地址、联系方式与办学资质"),
    ("Q04", QuestionType.GENERAL, "【占位待定】广州有哪些值得推荐的 AI/新媒体实训机构？", "正在选机构的学员", "寻找广州 AI/新媒体实训机构"),
    ("Q05", QuestionType.GENERAL, "【占位待定】零基础转行做短视频运营，广州哪里可以系统学？", "零基础转行短视频运营者", "寻找系统课程与实操训练"),
    ("Q06", QuestionType.GENERAL, "【占位待定】广州本地的实训机构课程价格与就业服务怎么样？", "比价阶段学员及家长", "比较课程价格与就业服务"),
]

LEGACY_AUDIENCE_BY_CODE = {
    "Q01": "招生咨询",
    "Q02": "课程咨询",
    "Q03": "信任核验",
    "Q04": "自然发现",
    "Q05": "需求匹配",
    "Q06": "比价与决策",
}

METRIC_SEED = [
    ("brand_mention_rate", "品牌提及率", "正确提及基地的有效回答数 ÷ 有效回答数"),
    ("citation_rate", "引用率", "含基地相关且已复核来源链接的有效回答数 ÷ 有效回答数"),
    ("sample_completion_rate", "样本完成率", "已完成采样的测试组合数 ÷ 计划测试组合数"),
]


def seed_roles(session) -> int:
    created = 0
    existing = {row.code for row in session.scalars(select(Role))}
    for code, name, desc in ROLE_SEED:
        if code in existing:
            continue
        session.add(Role(code=code, name=name, description=desc))
        created += 1
    session.flush()
    return created


def seed_permissions(session) -> int:
    """写入能力码目录（只补缺失，不改已有名称说明）。"""
    created = 0
    existing = {row.code for row in session.scalars(select(Permission))}
    for code, name, scope, desc in PERMISSION_CATALOG:
        if code in existing:
            continue
        session.add(Permission(code=code, name=name, scope=scope, description=desc))
        created += 1
    session.flush()
    return created


def seed_role_permissions(session) -> int:
    """按能力矩阵补角色—能力映射；可重复执行。"""
    created = 0
    role_by_code = {row.code: row for row in session.scalars(select(Role))}
    perm_by_code = {row.code: row for row in session.scalars(select(Permission))}
    existing = {
        (row.role_id, row.permission_id) for row in session.scalars(select(RolePermission))
    }
    for role_code, codes in ROLE_PERMISSIONS.items():
        role = role_by_code.get(role_code)
        if role is None:
            continue
        for code in codes:
            perm = perm_by_code.get(code)
            if perm is None:
                continue
            if (role.id, perm.id) in existing:
                continue
            session.add(RolePermission(role_id=role.id, permission_id=perm.id))
            created += 1
    session.flush()
    return created


def seed_admin_user(session) -> None:
    """建一个开发用系统管理员账号；生产环境未显式给密码时拒绝创建，避免弱密码上线。"""
    username = os.getenv("SEED_ADMIN_USERNAME", "geo_admin")
    password = os.getenv("SEED_ADMIN_PASSWORD")

    if settings.app_env.lower() in {"prod", "production"} and not password:
        raise SystemExit(
            "生产环境必须显式设置 SEED_ADMIN_PASSWORD，拒绝使用默认开发密码创建管理员"
        )

    existing = session.scalar(select(User).where(User.username == username))
    if existing:
        # 已存在的账号只补系统管理员标记，不改密码
        if not existing.is_system_admin:
            existing.is_system_admin = True
        return

    session.add(
        User(
            username=username,
            display_name="系统管理员",
            password_hash=pwd_context.hash(password or "geo-admin-dev"),
            is_active=True,
            is_system_admin=True,
        )
    )


def seed_project_admin_membership(session, project: Project) -> int:
    """给首期项目补一个项目管理员成员，保证首轮联调有可操作账号。

    只授予 project_admin，绝不把 sys_admin 写进 project_members：
    sys_admin 那行角色只是能力映射字典，系统权限只认 users.is_system_admin。
    """
    username = os.getenv("SEED_ADMIN_USERNAME", "geo_admin")
    user = session.scalar(select(User).where(User.username == username))
    role = session.scalar(select(Role).where(Role.code == RoleCode.PROJECT_ADMIN))
    if user is None or role is None:
        return 0

    existing = session.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project.id,
            ProjectMember.user_id == user.id,
        )
    )
    if existing is not None:
        return 0

    session.add(
        ProjectMember(
            project_id=project.id,
            user_id=user.id,
            role_id=role.id,
            is_active=True,
            granted_by=user.id,
        )
    )
    return 1


def seed_project_role_users(session, project: Project) -> tuple[int, int]:
    """给首期项目补 editor/reviewer/lead_ops/viewer 四个联调账号。

    幂等规则：
    - 账号已存在：不改密码、不改 display_name、不改系统管理员标记；
    - 项目成员已存在：不覆盖 role_id/is_active；
    - 只补缺失的账号和成员关系。
    生产环境必须显式设置 SEED_USER_PASSWORD，避免默认弱密码上线。
    """
    password = os.getenv(ROLE_USER_PASSWORD_ENV)
    if settings.app_env.lower() in {"prod", "production"} and not password:
        raise SystemExit(
            f"生产环境必须显式设置 {ROLE_USER_PASSWORD_ENV}，拒绝使用默认开发密码创建角色账号"
        )

    role_by_code = {row.code: row for row in session.scalars(select(Role))}
    admin_username = os.getenv("SEED_ADMIN_USERNAME", "geo_admin")
    admin = session.scalar(select(User).where(User.username == admin_username))
    granted_by = admin.id if admin is not None else None
    created_users = 0
    created_memberships = 0

    for username, display_name, role_code in ROLE_USER_SEED:
        role = role_by_code.get(role_code)
        if role is None:
            # 角色行缺失说明迁移未跑全；seed_roles 已在前一步补，仍缺则跳过，避免脏外键。
            continue

        user = session.scalar(select(User).where(User.username == username))
        if user is None:
            user = User(
                username=username,
                display_name=display_name,
                password_hash=pwd_context.hash(password or DEV_ROLE_USER_PASSWORD),
                is_active=True,
                is_system_admin=False,
            )
            session.add(user)
            session.flush()
            created_users += 1

        existing = session.scalar(
            select(ProjectMember).where(
                ProjectMember.project_id == project.id,
                ProjectMember.user_id == user.id,
            )
        )
        if existing is not None:
            continue

        session.add(
            ProjectMember(
                project_id=project.id,
                user_id=user.id,
                role_id=role.id,
                is_active=True,
                granted_by=granted_by,
            )
        )
        created_memberships += 1

    session.flush()
    return created_users, created_memberships


def seed_engines(session) -> int:
    created = 0
    existing = {row.code: row for row in session.scalars(select(AiEngine))}
    for code, name, vendor, note in ENGINE_SEED:
        if code in existing:
            continue
        engine = AiEngine(
            code=code,
            name=name,
            vendor=vendor,
            supports_search=True,
            supports_citation=True,
            access_note=note,
            is_active=True,
        )
        session.add(engine)
        session.flush()
        # 先按“网页用户端”建一条入口，API 入口待官方授权后补充
        session.add(
            AiEngineEntry(
                engine_id=engine.id,
                entry_type=EngineEntryType.WEB_USER,
                name=f"{name}网页端",
                supports_search=True,
                access_note="入口地址与联网能力待运营核验后填写",
                is_active=True,
            )
        )
        created += 1
    return created


def seed_project(session) -> Project:
    project = session.scalar(select(Project).where(Project.code == PROJECT_CODE))
    if project:
        return project
    project = Project(
        code=PROJECT_CODE,
        name=PROJECT_NAME,
        status=ProjectStatus.ACTIVE,
        description="首期广州基地试点项目，由 seed 建立，可在后台改名与补配置",
        timezone="Asia/Shanghai",
    )
    session.add(project)
    session.flush()
    return project


def seed_channels(session, project: Project) -> int:
    created = 0
    existing = {row.code for row in session.scalars(select(Channel).where(Channel.project_id == project.id))}
    for code, name, category, domain in CHANNEL_SEED:
        if code in existing:
            continue
        session.add(
            Channel(
                project_id=project.id,
                code=code,
                name=name,
                category=category,
                status=ChannelStatus.CANDIDATE,
                primary_domain=domain,
                is_active=True,
            )
        )
        created += 1
    return created


def seed_questions(session, project: Project) -> tuple[int, int]:
    """新建题目；同时把早期 seed 行里“写在 audience 的意图”迁移为正确画像。

    只处理 audience 仍等于旧 seed 值且 intent 为空的行，人工改过的一律不动。
    """
    created = 0
    backfilled = 0
    existing = {
        row.code: row
        for row in session.scalars(select(Question).where(Question.project_id == project.id))
    }
    for code, qtype, text, audience, intent in QUESTION_SEED:
        question = existing.get(code)
        if question is not None:
            legacy_audience = LEGACY_AUDIENCE_BY_CODE.get(code)
            if (
                question.intent is None
                and legacy_audience is not None
                and question.audience == legacy_audience
            ):
                question.audience = audience
                question.intent = intent
                backfilled += 1
            continue
        question = Question(
            project_id=project.id,
            code=code,
            title=text,
            question_type=qtype,
            audience=audience,
            intent=intent,
            priority=100,
            status=QuestionStatus.DRAFT,
            current_version_no=1,
        )
        session.add(question)
        session.flush()
        session.add(
            QuestionVersion(
                project_id=project.id,
                question_id=question.id,
                version_no=1,
                text=text,
                change_note="seed 初始占位版本，待运营确认正式问法后追加 v2",
            )
        )
        created += 1
    return created, backfilled


def seed_metrics(session, project: Project) -> int:
    created = 0
    effective_from = datetime(2026, 11, 1, tzinfo=timezone.utc)
    existing = {
        (row.code, row.rule_version)
        for row in session.scalars(select(MetricDefinition).where(MetricDefinition.project_id == project.id))
    }
    for code, name, formula in METRIC_SEED:
        if (code, 1) in existing:
            continue
        session.add(
            MetricDefinition(
                project_id=project.id,
                code=code,
                name=name,
                rule_version=1,
                formula=formula,
                effective_from=effective_from,
                status=MetricStatus.ACTIVE,
            )
        )
        created += 1
    return created


def main() -> None:
    session = SessionLocal()
    baseline_result = None
    try:
        roles = seed_roles(session)
        role_code_rows = {row.code for row in session.scalars(select(Role))}
        missing = {code for code, _, _ in ROLE_SEED} - role_code_rows
        if missing:
            # 历史环境里可能还留着旧 code（admin），先提示再继续
            print(f"  注意：以下角色 code 尚未存在，请先执行 alembic upgrade head：{sorted(missing)}")
        permissions = seed_permissions(session)
        role_permissions = seed_role_permissions(session)
        seed_admin_user(session)
        engines = seed_engines(session)
        project = seed_project(session)
        admins = seed_project_admin_membership(session, project)
        role_users, role_memberships = seed_project_role_users(session, project)
        channels = seed_channels(session, project)
        questions, question_backfilled = seed_questions(session, project)
        metrics = seed_metrics(session, project)
        if "--technical-baseline" in sys.argv:
            from app.services.question_baseline import activate_technical_baseline

            baseline_result = activate_technical_baseline(session, project.code)
        session.commit()

        print("种子数据完成（仅统计本次新增/补全）：")
        print(
            f"  角色 +{roles}，能力码 +{permissions}，角色能力映射 +{role_permissions}，"
            f"引擎 +{engines}，项目 {project.code}（项目管理员成员 +{admins}），渠道 +{channels}，"
            f"问题 +{questions}（画像回填 {question_backfilled}），口径 +{metrics}，"
            f"角色账号 +{role_users}（项目角色成员 +{role_memberships}）"
        )
        if baseline_result is not None:
            print(
                f"  技术基线 {baseline_result['baseline']}："
                f"激活 {baseline_result['activated']} 题，新建版本 {baseline_result['created_versions']}"
            )
        username = os.getenv("SEED_ADMIN_USERNAME", "geo_admin")
        if os.getenv("SEED_ADMIN_PASSWORD"):
            print(f"  管理员账号 {username}（密码取自 SEED_ADMIN_PASSWORD，不落日志）")
        else:
            print(f"  管理员账号 {username} / geo-admin-dev（开发默认密码，仅限本地）")
        role_usernames = " / ".join(row[0] for row in ROLE_USER_SEED)
        if os.getenv(ROLE_USER_PASSWORD_ENV):
            print(f"  角色账号 {role_usernames}（密码取自 {ROLE_USER_PASSWORD_ENV}，不落日志）")
        else:
            print(
                f"  角色账号 {role_usernames} / {DEV_ROLE_USER_PASSWORD}"
                "（开发默认密码，仅限本地；生产必须设 SEED_USER_PASSWORD）"
            )
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    main()
