"""初始化种子数据：角色、AI 引擎目录、首期试点项目、渠道目录、6 道标准问题、指标口径。

特点：可重复执行（重复运行不会产生重复数据），只补缺失的，不覆盖已有业务改动。

用法（在 backend 目录下）：
    .venv\\Scripts\\python.exe scripts\\seed.py
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
from app.models import (  # noqa: E402
    AiEngine,
    AiEngineEntry,
    Channel,
    MetricDefinition,
    Project,
    Question,
    QuestionVersion,
    Role,
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
    (RoleCode.ADMIN, "管理员", "项目配置、用户与权限、全部业务操作"),
    (RoleCode.EDITOR, "运营/编辑", "题库、监测任务、内容选题与分发排期"),
    (RoleCode.REVIEWER, "审核", "稿件签发与审批，记录可追溯"),
    (RoleCode.VIEWER, "只读", "只读查看，不可写入"),
    (RoleCode.LEAD_OPS, "招生/客服", "仅线索相关数据的读写"),
]

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
    ("boss", "BOSS 直聘", ChannelCategory.INSTITUTION, "zhipin.com"),
]

# 6 道标准问题先用占位文本建立版本链，真实问法待运营确认后按新版本追加，不改旧版本
QUESTION_SEED = [
    ("Q01", QuestionType.BRAND, "【占位待定】广州基地全称与主营方向是什么？", "招生咨询"),
    ("Q02", QuestionType.BRAND, "【占位待定】广州基地的实训课程有哪些、怎么报名？", "课程咨询"),
    ("Q03", QuestionType.BRAND, "【占位待定】广州基地地址、联系方式与资质如何核验？", "信任核验"),
    ("Q04", QuestionType.GENERAL, "【占位待定】广州有哪些值得推荐的 AI/新媒体实训机构？", "自然发现"),
    ("Q05", QuestionType.GENERAL, "【占位待定】零基础转行做短视频运营，广州哪里可以系统学？", "需求匹配"),
    ("Q06", QuestionType.GENERAL, "【占位待定】广州本地的实训机构课程价格与就业服务怎么样？", "比价与决策"),
]

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


def seed_questions(session, project: Project) -> int:
    created = 0
    existing = {row.code for row in session.scalars(select(Question).where(Question.project_id == project.id))}
    for code, qtype, text, audience in QUESTION_SEED:
        if code in existing:
            continue
        question = Question(
            project_id=project.id,
            code=code,
            title=text,
            question_type=qtype,
            audience=audience,
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
    return created


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
    try:
        roles = seed_roles(session)
        seed_admin_user(session)
        engines = seed_engines(session)
        project = seed_project(session)
        channels = seed_channels(session, project)
        questions = seed_questions(session, project)
        metrics = seed_metrics(session, project)
        session.commit()

        print("种子数据完成（仅统计本次新增）：")
        print(f"  角色 +{roles}，引擎 +{engines}，项目 {project.code}，渠道 +{channels}，问题 +{questions}，口径 +{metrics}")
        print("  管理员账号默认 geo_admin / geo-admin-dev ，生产部署前必须改密码")
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    main()
