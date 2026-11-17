"""能力矩阵：能力码目录 + 角色映射，是权限判断与种子数据的唯一事实来源。

接口只认能力码（permission code），不认角色名；调整角色不动代码，只改这里的映射。
"""

from app.models.enums import PermissionScope, RoleCode

# (code, 名称, 作用域, 说明)
PERMISSION_CATALOG: list[tuple[str, str, PermissionScope, str]] = [
    # 系统级：只有系统管理员持有
    ("project.create", "创建项目", PermissionScope.SYSTEM, "新建项目、修改项目状态"),
    ("engine.manage", "维护引擎目录", PermissionScope.SYSTEM, "AI 引擎与入口的增改、核验"),
    # 项目级：允许运营/项目管理员人工核验入口，但不授予目录增改
    ("engine.verify", "核验引擎入口", PermissionScope.PROJECT, "人工核验 web_user/app_search 入口"),
    # 项目级：按项目成员角色授予
    ("project.member.manage", "管理项目成员", PermissionScope.PROJECT, "增删成员、变更角色"),
    ("project.read", "查看项目", PermissionScope.PROJECT, "读取项目基础信息与该项目的资源列表"),
    ("question.read", "查看题库", PermissionScope.PROJECT, "读取问题与版本"),
    ("question.write", "维护题库", PermissionScope.PROJECT, "新增问题、追加版本、调整状态"),
    ("monitoring.read", "查看监测数据", PermissionScope.PROJECT, "轮次、任务、样本、引用"),
    ("monitoring.execute", "触发采样执行", PermissionScope.PROJECT, "手动触发采样任务"),
    ("evidence.read", "查看证据文件", PermissionScope.PROJECT, "下载截图与附件"),
    ("evidence.review", "证据人工复核", PermissionScope.PROJECT, "确认或驳回引用归属"),
    ("content.read", "查看内容", PermissionScope.PROJECT, "读取母稿、渠道稿与版本"),
    ("content.write", "编辑内容正文", PermissionScope.PROJECT, "新建内容、追加版本、修改正文"),
    ("content.review", "审核签发", PermissionScope.PROJECT, "通过或驳回内容版本并留痕"),
    ("publish.read", "查看发布任务", PermissionScope.PROJECT, "发布任务与回执"),
    ("publish.execute", "执行发布", PermissionScope.PROJECT, "创建发布任务、记录发布尝试"),
    ("channel.read", "查看渠道台账", PermissionScope.PROJECT, "渠道分类、域名映射"),
    ("channel.write", "维护渠道台账", PermissionScope.PROJECT, "修改渠道分类与状态"),
    ("competitor.write", "维护竞品台账", PermissionScope.PROJECT, "新增、修改竞品与启停状态"),
    ("brand.manage", "维护品牌口径", PermissionScope.PROJECT, "配置品牌正式名、别名、唯一标识与自有域名"),
    ("lead.read", "查看线索", PermissionScope.PROJECT, "线索明细"),
    ("lead.write", "维护线索", PermissionScope.PROJECT, "录入与跟进线索"),
    ("stats.read", "查看统计看板", PermissionScope.PROJECT, "品牌提及率、引用率、样本完成率"),
    ("metric.manage", "维护指标口径", PermissionScope.PROJECT, "新增指标口径版本、停用旧版本"),
    ("export.data", "导出数据", PermissionScope.PROJECT, "导出 CSV，必须写审计"),
    ("audit.read", "查看审计日志", PermissionScope.PROJECT, "审计留痕查询"),
]

# 项目级“读”能力集合：只读角色与项目管理员共用
PROJECT_READ_CODES = [
    "project.read",
    "question.read",
    "monitoring.read",
    "evidence.read",
    "content.read",
    "publish.read",
    "channel.read",
    "lead.read",
    "stats.read",
]

# 角色 → 能力
ROLE_PERMISSIONS: dict[RoleCode, list[str]] = {
    # 系统管理员只管系统级配置，不默认读写项目业务数据
    RoleCode.SYS_ADMIN: ["project.create", "engine.manage"],
    # 项目管理员：管成员 + 审批 + 全项目只读 + 渠道台账维护 + 审计，不改正文、不执行发布
    RoleCode.PROJECT_ADMIN: [
        "project.member.manage",
        *PROJECT_READ_CODES,
        "content.review",
        "evidence.review",
        "channel.write",
        "competitor.write",
        "brand.manage",
        "metric.manage",
        "engine.verify",
        "export.data",
        "audit.read",
    ],
    # 运营/编辑：业务写操作，无审批、无成员管理、无线索明细
    RoleCode.EDITOR: [
        "project.read",
        "question.read",
        "question.write",
        "monitoring.read",
        "monitoring.execute",
        "evidence.read",
        "content.read",
        "content.write",
        "publish.read",
        "publish.execute",
        "channel.read",
        "channel.write",
        "competitor.write",
        "brand.manage",
        "metric.manage",
        "engine.verify",
        "stats.read",
        "export.data",
    ],
    # 审核：只审批与复核，不改正文、不发布
    RoleCode.REVIEWER: [
        "project.read",
        "question.read",
        "monitoring.read",
        "evidence.read",
        "evidence.review",
        "content.read",
        "content.review",
        "stats.read",
        "audit.read",
    ],
    # 只读：全部读能力 + 导出能力（导出必须留痕）
    RoleCode.VIEWER: [*PROJECT_READ_CODES, "export.data"],
    # 招生/客服：只有线索
    RoleCode.LEAD_OPS: ["project.read", "lead.read", "lead.write"],
}

# 管理类能力：任何角色都不得通过“授予成员”把这些能力传出去
MANAGEMENT_PERMISSIONS = frozenset({"project.create", "engine.manage", "project.member.manage"})

# 项目管理员可授予的角色白名单（审核意见明确列举）
GRANTABLE_ROLE_CODES = frozenset(
    {RoleCode.EDITOR, RoleCode.REVIEWER, RoleCode.VIEWER, RoleCode.LEAD_OPS}
)


def permissions_for(role: RoleCode) -> frozenset[str]:
    return frozenset(ROLE_PERMISSIONS.get(role, []))


def system_permissions() -> frozenset[str]:
    return permissions_for(RoleCode.SYS_ADMIN)


def can_grant(actor_role: RoleCode, target_role: RoleCode) -> bool:
    """授予约束：目标角色必须在白名单内，且不得携带任何管理类能力。

    这样既挡住“项目管理员把自己或系统管理员授出去”，也挡住把成员管理权转授他人；
    业务角色（编辑/审核/只读/招生）本身不含管理能力，由项目管理员正常授予。
    """
    if target_role not in GRANTABLE_ROLE_CODES:
        return False
    return not (permissions_for(target_role) & MANAGEMENT_PERMISSIONS)
