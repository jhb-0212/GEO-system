"""R-01 待办周期时间事实源（entered_todo_at）的行为与结构守卫。

覆盖四类证据：
1. 四象限写入：只在跨越待办集合边界时写入/清空，集合内部迁移与普通更新不刷新；
2. 事实组合条件：状态或来源缺失取并集，判定与 SQL 口径逐字对齐；
3. 预警状态机：重开边已从转换表删除，非法重开统一 409（task_rejected）；
4. 单一写入口：除 todo_clock 外，任何模块不得直接给 entered_todo_at 赋值。
"""

from __future__ import annotations

import ast
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import app
from app.core.errors import TaskRejectedError
from app.models import Fact
from app.models.enums import (
    AlertEventStatus,
    FactStatus,
    FactType,
    KnowledgeCandidateStatus,
    KnowledgeParseStatus,
    PublishTaskStatus,
    TaskStatus,
)
from app.services import todo_clock
from app.services.state_machine import ALERT_EVENT_TRANSITIONS, ensure_alert_event_transition

# ---------- 1. 四象限 ----------


def test_sync_cycle_keeps_time_inside_set():
    stamp = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)
    obj = SimpleNamespace(entered_todo_at=stamp)
    todo_clock.sync_cycle(obj, old_in=True, new_in=True)
    assert obj.entered_todo_at == stamp


def test_sync_cycle_ignores_outside_to_outside():
    obj = SimpleNamespace(entered_todo_at=None)
    todo_clock.sync_cycle(obj, old_in=False, new_in=False)
    assert obj.entered_todo_at is None


def test_sync_cycle_writes_on_entry():
    obj = SimpleNamespace(entered_todo_at=None)
    now = datetime(2026, 11, 26, 3, 0, tzinfo=timezone.utc)
    todo_clock.sync_cycle(obj, old_in=False, new_in=True, now=now)
    assert obj.entered_todo_at == now


def test_sync_cycle_clears_on_exit():
    obj = SimpleNamespace(entered_todo_at=datetime(2026, 10, 1, tzinfo=timezone.utc))
    todo_clock.sync_cycle(obj, old_in=True, new_in=False)
    assert obj.entered_todo_at is None


def test_reentry_records_new_time():
    old = datetime(2026, 10, 1, tzinfo=timezone.utc)
    new = datetime(2026, 11, 26, tzinfo=timezone.utc)
    obj = SimpleNamespace(entered_todo_at=old)
    todo_clock.sync_cycle(obj, old_in=True, new_in=False)
    todo_clock.sync_cycle(obj, old_in=False, new_in=True, now=new)
    assert obj.entered_todo_at == new


# ---------- 2. 组合条件 ----------


@pytest.mark.parametrize(
    ("status", "document", "url", "expected"),
    [
        (FactStatus.DRAFT, None, None, True),
        (FactStatus.PENDING_REVIEW, None, None, True),
        (FactStatus.APPROVED, "白皮书.pdf", None, False),
        (FactStatus.APPROVED, None, None, True),
        (FactStatus.APPROVED, "", "", True),
        # 纯空白在 SQL nullif 下不是 NULL，必须与查询侧同口径视为“有来源”
        (FactStatus.APPROVED, "   ", None, False),
        (FactStatus.EXPIRED, "白皮书.pdf", "https://example.com", False),
        (FactStatus.EXPIRED, None, None, True),
    ],
)
def test_fact_membership_truth_table(status, document, url, expected):
    fact = SimpleNamespace(approval_status=status, source_document=document, source_url=url)
    assert todo_clock.fact_in_todo(fact) is expected


def test_fact_approve_exits_only_when_source_complete():
    stamp = datetime(2026, 11, 1, tzinfo=timezone.utc)
    fact = SimpleNamespace(
        approval_status=FactStatus.PENDING_REVIEW,
        source_document="白皮书.pdf",
        source_url=None,
        entered_todo_at=stamp,
    )
    todo_clock.apply_fact_status(fact, FactStatus.APPROVED)
    assert fact.entered_todo_at is None


def test_fact_approve_stays_when_source_missing():
    stamp = datetime(2026, 11, 1, tzinfo=timezone.utc)
    fact = SimpleNamespace(
        approval_status=FactStatus.PENDING_REVIEW,
        source_document=None,
        source_url=None,
        entered_todo_at=stamp,
    )
    todo_clock.apply_fact_status(fact, FactStatus.APPROVED)
    assert fact.entered_todo_at == stamp


def test_fact_clearing_source_reenters():
    fact = SimpleNamespace(
        approval_status=FactStatus.APPROVED,
        source_document="白皮书.pdf",
        source_url=None,
        entered_todo_at=None,
    )
    old_in = todo_clock.fact_in_todo(fact)
    fact.source_document = None
    todo_clock.sync_cycle(fact, old_in=old_in, new_in=todo_clock.fact_in_todo(fact))
    assert fact.entered_todo_at is not None


# ---------- 3. 各实体集合内部 / 跨界 ----------


def test_publish_internal_move_keeps_time():
    stamp = datetime(2026, 11, 1, tzinfo=timezone.utc)
    task = SimpleNamespace(status=PublishTaskStatus.PENDING, entered_todo_at=stamp)
    todo_clock.apply_publish_status(task, PublishTaskStatus.NEEDS_REVIEW)
    assert task.status == PublishTaskStatus.NEEDS_REVIEW
    assert task.entered_todo_at == stamp


def test_publish_leaving_clears_time():
    task = SimpleNamespace(
        status=PublishTaskStatus.NEEDS_REVIEW,
        entered_todo_at=datetime(2026, 11, 1, tzinfo=timezone.utc),
    )
    todo_clock.apply_publish_status(task, PublishTaskStatus.CANCELLED)
    assert task.entered_todo_at is None


def test_monitoring_failure_enters_and_done_clears():
    task = SimpleNamespace(status=TaskStatus.PENDING, entered_todo_at=None)
    todo_clock.apply_task_status(task, TaskStatus.FAILED)
    entered = task.entered_todo_at
    assert entered is not None
    todo_clock.apply_task_status(task, TaskStatus.DONE)
    assert task.entered_todo_at is None


def test_monitoring_uncertain_stays_inside_set():
    stamp = datetime(2026, 11, 1, tzinfo=timezone.utc)
    task = SimpleNamespace(status=TaskStatus.RUNNING, entered_todo_at=None)
    todo_clock.apply_task_status(task, TaskStatus.UNCERTAIN)
    entered = task.entered_todo_at
    assert entered is not None
    assert task.entered_todo_at == entered
    todo_clock.apply_task_status(task, TaskStatus.PENDING)
    assert task.entered_todo_at is None


def test_parse_internal_moves_keep_time_and_ready_clears():
    stamp = datetime(2026, 11, 1, tzinfo=timezone.utc)
    document = SimpleNamespace(parse_status=KnowledgeParseStatus.PARSING, entered_todo_at=stamp)
    todo_clock.apply_parse_status(document, KnowledgeParseStatus.FAILED)
    assert document.entered_todo_at == stamp
    todo_clock.apply_parse_status(document, KnowledgeParseStatus.PENDING)
    assert document.entered_todo_at == stamp
    todo_clock.apply_parse_status(document, KnowledgeParseStatus.PARSING)
    assert document.entered_todo_at == stamp
    todo_clock.apply_parse_status(document, KnowledgeParseStatus.READY)
    assert document.entered_todo_at is None


def test_reparse_after_ready_records_new_cycle():
    """READY→PENDING 是合法边但当前无生产写入点（R-01 已记录该缺口）。

    规则本身必须成立：从集合外重新进入集合，必须写入新时间而不是继承旧值。
    """
    document = SimpleNamespace(parse_status=KnowledgeParseStatus.READY, entered_todo_at=None)
    now = datetime(2026, 11, 26, tzinfo=timezone.utc)
    todo_clock.apply_parse_status(document, KnowledgeParseStatus.PENDING, now=now)
    assert document.entered_todo_at == now


def test_candidate_accept_clears():
    stamp = datetime(2026, 11, 1, tzinfo=timezone.utc)
    candidate = SimpleNamespace(status=KnowledgeCandidateStatus.SUGGESTED, entered_todo_at=stamp)
    todo_clock.apply_candidate_status(candidate, KnowledgeCandidateStatus.ACCEPTED)
    assert candidate.entered_todo_at is None


# ---------- 4. 预警状态机收口 ----------


def test_alert_transitions_have_no_reopen_edge():
    assert ALERT_EVENT_TRANSITIONS[AlertEventStatus.OPEN] == frozenset(
        {AlertEventStatus.ACKNOWLEDGED, AlertEventStatus.RESOLVED}
    )
    assert AlertEventStatus.OPEN not in ALERT_EVENT_TRANSITIONS[AlertEventStatus.ACKNOWLEDGED]
    assert ALERT_EVENT_TRANSITIONS[AlertEventStatus.RESOLVED] == frozenset()


@pytest.mark.parametrize(
    "current", [AlertEventStatus.ACKNOWLEDGED, AlertEventStatus.RESOLVED]
)
def test_alert_reopen_is_rejected(current):
    with pytest.raises(TaskRejectedError) as error:
        ensure_alert_event_transition(current, AlertEventStatus.OPEN)
    assert "alert_event" in str(error.value)


def test_alert_forward_edges_still_work():
    assert (
        ensure_alert_event_transition(AlertEventStatus.OPEN, AlertEventStatus.ACKNOWLEDGED)
        == AlertEventStatus.ACKNOWLEDGED
    )
    assert (
        ensure_alert_event_transition(AlertEventStatus.ACKNOWLEDGED, AlertEventStatus.RESOLVED)
        == AlertEventStatus.RESOLVED
    )


# ---------- 5. 单一写入口守卫 ----------


def test_only_todo_clock_assigns_entered_todo_at():
    """除写入口本身，任何模块不得直接给 entered_todo_at 赋值。

    创建时的关键字参数（Fact(... entered_todo_at=...)）属于建立初始周期，不受此限制；
    这里约束的是运行期的赋值写入，防止绕过四象限判定刷新周期起点。
    """
    offenders: list[str] = []
    app_dir = Path(app.__file__).resolve().parent
    for path in app_dir.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                targets = node.targets
            elif isinstance(node, ast.AugAssign):
                targets = [node.target]
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                targets = [node.target]
            else:
                continue
            for target in targets:
                if isinstance(target, ast.Attribute) and target.attr == "entered_todo_at":
                    if path.name != "todo_clock.py":
                        offenders.append(f"{path.name}:{node.lineno}")
    assert offenders == []


# ---------- 5b. 写入点清单守卫 ----------

BACKEND_DIR = Path(__file__).resolve().parents[1]
SCAN_ROOTS = (BACKEND_DIR / "app", BACKEND_DIR / "scripts")
APPLY_NAMES = {
    "apply_publish_status",
    "apply_task_status",
    "apply_fact_status",
    "apply_parse_status",
    "apply_candidate_status",
}

# 允许的写入点：文件 -> (apply 调用, 关键字写入, 直接赋值)，必须逐项相等。
# 新增任何一处都必须同时更新本清单并说明理由，否则测试失败。
EXPECTED_WRITE_SITES: dict[str, dict[str, int]] = {
    "app/api/facts.py": {"apply": 4, "keyword": 1, "assign": 0},
    "app/api/monitoring.py": {"apply": 2, "keyword": 1, "assign": 0},
    # 发布执行段下沉到 services/publish_execution.py 供“人工执行 + 到点自动发”共用，
    # api 只保留转人工/回执等入口自身的状态写入。
    "app/api/publishing.py": {"apply": 6, "keyword": 1, "assign": 0},
    "app/services/publish_execution.py": {"apply": 5, "keyword": 0, "assign": 0},
    "app/services/distribution_dispatch.py": {"apply": 0, "keyword": 1, "assign": 0},
    "app/services/knowledge_base.py": {"apply": 6, "keyword": 3, "assign": 0},
    "app/services/monitoring_collection.py": {"apply": 9, "keyword": 0, "assign": 0},
    "app/services/todo_clock.py": {"apply": 0, "keyword": 0, "assign": 1},
    # C2-4 联调夹具：只为“今天窗口的四条边界”造样本事实，属开发/验收脚本，
    # 不在请求链路里执行；业务写入仍必须走 todo_clock。
    "scripts/c2_live_fixture.py": {"apply": 0, "keyword": 1, "assign": 0},
}


def _scan_write_sites() -> tuple[dict[str, dict[str, int]], set[str], set[str]]:
    counts: dict[str, dict[str, int]] = {}
    writers: set[str] = set()
    scanned_paths: set[str] = set()
    for root in SCAN_ROOTS:
        for path in sorted(root.rglob("*.py")):
            rel = path.relative_to(BACKEND_DIR).as_posix()
            scanned_paths.add(rel)
            tree = ast.parse(path.read_text(encoding="utf-8"))
            hits = {"apply": 0, "keyword": 0, "assign": 0}
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    func = node.func
                    name = None
                    if isinstance(func, ast.Name) and func.id in APPLY_NAMES:
                        name = func.id
                    elif isinstance(func, ast.Attribute) and func.attr in APPLY_NAMES:
                        name = func.attr
                    if name is not None:
                        hits["apply"] += 1
                    for keyword in node.keywords:
                        if keyword.arg == "entered_todo_at":
                            hits["keyword"] += 1
                if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
                    if isinstance(node, ast.Assign):
                        targets = node.targets
                    elif isinstance(node, ast.AugAssign):
                        targets = [node.target]
                    else:
                        targets = [node.target] if node.value is not None else []
                    for target in targets:
                        if isinstance(target, ast.Attribute) and target.attr == "entered_todo_at":
                            hits["assign"] += 1
            if any(hits.values()):
                counts[rel] = hits
                writers.add(rel)
    return counts, writers, scanned_paths


def test_entered_todo_write_sites_match_allowlist():
    counts, writers, scanned_paths = _scan_write_sites()
    assert counts == EXPECTED_WRITE_SITES, (
        "写入点清单漂移，新增/删除的写入必须显式评审：\n"
        f"实际={counts}\n期望={EXPECTED_WRITE_SITES}"
    )
    # 扫描范围必须覆盖全部生产代码目录，而不是只看当前已知目录
    for required in ("app/api", "app/services", "app/models", "app/db", "app/core", "scripts"):
        assert any(path.startswith(required) for path in scanned_paths), (
            f"扫描未覆盖 {required}，写入点清单不完整"
        )
    assert len(scanned_paths) > 300, f"扫描文件数异常（{len(scanned_paths)}），可能漏扫目录"


# ---------- 5c. 迁移守卫 ----------


def _load_migration(module_name: str):
    import importlib.util

    path = (
        Path(__file__).resolve().parents[2] / "migrations" / "versions" / f"{module_name}.py"
    )
    spec = importlib.util.spec_from_file_location(f"_m_{module_name}", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_r01_migration_rejects_definition_drift():
    """已存在列必须校验类型/时区/可空/默认值；不符立即失败，不得静默跳过。"""
    import sqlalchemy as sa

    module = _load_migration("r01a2b3c4d5e_todo_entered_at")
    good = {"type": sa.DateTime(timezone=True), "nullable": True, "default": None}
    module._assert_column_matches(good, "publish_tasks")

    for bad, reason in (
        ({"type": sa.DateTime(timezone=False), "nullable": True, "default": None}, "无时区"),
        ({"type": sa.DateTime(timezone=True), "nullable": False, "default": None}, "可空"),
        ({"type": sa.DateTime(timezone=True), "nullable": True, "default": "now()"}, "默认值"),
        ({"type": sa.String(32), "nullable": True, "default": None}, "类型"),
    ):
        with pytest.raises(RuntimeError) as error:
            module._assert_column_matches(bad, "publish_tasks")
        assert reason in str(error.value)

    class _Inspector:
        def __init__(self, tables):
            self._tables = tables

        def get_table_names(self):
            return self._tables

    module._assert_table_exists(_Inspector(["publish_tasks"]), "publish_tasks")
    with pytest.raises(RuntimeError) as missing:
        module._assert_table_exists(_Inspector(["publish_tasks"]), "facts")
    assert "不存在" in str(missing.value)


def test_r01_backfill_preserves_existing_values(db, project_factory, user_factory):
    """回填只填 NULL：预置非 NULL 值的行必须逐字保留，重复执行不改结果。"""
    import sqlalchemy as sa

    from app.models import (
        AuditLog,
        Channel,
        ContentItem,
        ContentVersion,
        FactVersion,
        KnowledgeCandidateFact,
        KnowledgeDocument,
        Material,
        PublishAccount,
        PublishTask,
    )
    from app.models.enums import (
        ChannelCategory,
        ContentKind,
        ContentStatus,
        FactVersionAction,
        KnowledgeCandidateStatus,
        KnowledgeParseStatus,
        MaterialCategory,
        PublishMode,
        PublishTaskStatus,
    )

    module = _load_migration("r01a2b3c4d5e_todo_entered_at")
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"r01-bf-{suffix}")
    user = user_factory(f"r01-bf-user-{suffix}")
    preset = datetime(2026, 3, 4, 5, 6, 7, tzinfo=timezone.utc)
    audit_ts = datetime(2026, 5, 1, 1, 0, tzinfo=timezone.utc)
    material_ts = datetime(2026, 4, 1, 0, 0, tzinfo=timezone.utc)
    fact_ts = datetime(2026, 2, 1, 0, 0, tzinfo=timezone.utc)

    # --- 发布：预置 / NULL 各一条，NULL 那条有可回溯审计 ---
    channel = Channel(
        project_id=project.id, code=f"r01-{suffix}", name="回填渠道",
        category=ChannelCategory.CONTENT_PLATFORM,
    )
    db.add(channel)
    db.flush()
    account = PublishAccount(project_id=project.id, channel_id=channel.id, account_name="回填账号")
    db.add(account)
    db.flush()

    def _publish_task(entered):
        item = ContentItem(
            project_id=project.id, kind=ContentKind.MASTER, title=f"回填稿-{suffix}",
            status=ContentStatus.APPROVED,
        )
        db.add(item)
        db.flush()
        version = ContentVersion(
            project_id=project.id, item_id=item.id, version_no=1, body="正文",
            content_hash=uuid.uuid4().hex, status=ContentStatus.APPROVED,
        )
        db.add(version)
        db.flush()
        task = PublishTask(
            project_id=project.id, version_id=version.id, channel_id=channel.id,
            account_id=account.id, task_key=f"k-{uuid.uuid4().hex[:6]}",
            idempotency_key=f"i-{uuid.uuid4().hex[:6]}", publish_mode=PublishMode.MANUAL,
            status=PublishTaskStatus.PENDING, created_at=datetime.now(timezone.utc),
            entered_todo_at=entered,
        )
        db.add(task)
        db.flush()
        return task

    task_preset = _publish_task(preset)
    task_null = _publish_task(None)
    db.add(
        AuditLog(
            project_id=project.id, action="publish.task_create",
            target_type="publish_task", target_id=task_null.id, created_at=audit_ts,
        )
    )
    db.flush()

    for round_no in (1, 2):
        db.execute(sa.text(module._PUBLISH_BACKFILL_SQL))
        db.flush()
        db.refresh(task_preset)
        db.refresh(task_null)
        assert task_preset.entered_todo_at == preset, f"第 {round_no} 轮覆盖了预置值"
        assert task_null.entered_todo_at == audit_ts, f"第 {round_no} 轮未按审计回填"

    # --- 知识文档 / 候选：同一素材、一条预置一条 NULL ---
    material_preset = Material(
        project_id=project.id, title=f"素材A-{suffix}", file_name="a.pdf", byte_size=1,
        checksum="x", storage_key="k1", category=MaterialCategory.DOCUMENT,
        created_at=material_ts,
    )
    material_null = Material(
        project_id=project.id, title=f"素材B-{suffix}", file_name="b.pdf", byte_size=1,
        checksum="x", storage_key="k2", category=MaterialCategory.DOCUMENT,
        created_at=material_ts,
    )
    db.add_all([material_preset, material_null])
    db.flush()
    doc_preset = KnowledgeDocument(
        project_id=project.id, material_id=material_preset.id,
        parse_status=KnowledgeParseStatus.FAILED, entered_todo_at=preset,
    )
    doc_null = KnowledgeDocument(
        project_id=project.id, material_id=material_null.id,
        parse_status=KnowledgeParseStatus.FAILED,
    )
    db.add_all([doc_preset, doc_null])
    db.flush()

    for round_no in (1, 2):
        db.execute(sa.text(module._DOC_BACKFILL_SQL))
        db.flush()
        db.refresh(doc_preset)
        db.refresh(doc_null)
        assert doc_preset.entered_todo_at == preset, f"第 {round_no} 轮覆盖了文档预置值"
        assert doc_null.entered_todo_at == material_ts, f"第 {round_no} 轮未按素材时间回填"

    cand_preset = KnowledgeCandidateFact(
        project_id=project.id, document_id=doc_preset.id, claim_text="预置候选",
        fingerprint=f"fp-{suffix}-1", status=KnowledgeCandidateStatus.SUGGESTED,
        evidence_text="证据一", suggested_fact_type=FactType.CERTIFICATION,
        suggested_fact_key=f"ck-{suffix}-1",
        created_at=audit_ts, entered_todo_at=preset,
    )
    cand_null = KnowledgeCandidateFact(
        project_id=project.id, document_id=doc_null.id, claim_text="待回填候选",
        fingerprint=f"fp-{suffix}-2", status=KnowledgeCandidateStatus.SUGGESTED,
        evidence_text="证据二", suggested_fact_type=FactType.CERTIFICATION,
        suggested_fact_key=f"ck-{suffix}-2",
        created_at=audit_ts,
    )
    db.add_all([cand_preset, cand_null])
    db.flush()

    for round_no in (1, 2):
        db.execute(sa.text(module._CANDIDATE_BACKFILL_SQL))
        db.flush()
        db.refresh(cand_preset)
        db.refresh(cand_null)
        assert cand_preset.entered_todo_at == preset, f"第 {round_no} 轮覆盖了候选预置值"
        assert cand_null.entered_todo_at == audit_ts, f"第 {round_no} 轮未按创建时间回填"

    # --- 事实：按 FactVersion 重放，同样只填 NULL ---
    def _fact(entered):
        fact = Fact(
            project_id=project.id, fact_type=FactType.CERTIFICATION,
            fact_key=f"bf-{uuid.uuid4().hex[:6]}", fact_value="值", version_no=1,
            created_by=user.id, source_document="doc.pdf", entered_todo_at=entered,
        )
        db.add(fact)
        db.flush()
        db.add(
            FactVersion(
                project_id=project.id, fact_id=fact.id, version_no=1,
                action=FactVersionAction.CREATED,
                snapshot={
                    "approval_status": "draft",
                    "source_document": "doc.pdf",
                    "source_url": "",
                },
                created_at=fact_ts,
            )
        )
        db.flush()
        return fact

    fact_preset = _fact(preset)
    fact_null = _fact(None)
    for round_no in (1, 2):
        module._backfill_facts(db)
        db.flush()
        db.refresh(fact_preset)
        db.refresh(fact_null)
        assert fact_preset.entered_todo_at == preset, f"第 {round_no} 轮覆盖了事实预置值"
        assert fact_null.entered_todo_at == fact_ts, f"第 {round_no} 轮未按版本重放回填"


LEGACY_METADATA_MIGRATIONS = {"q3d4e5f6a7b8"}


def _code_without_comments(text: str) -> str:
    import io
    import tokenize

    pieces: list[str] = []
    for token in tokenize.generate_tokens(io.StringIO(text).readline):
        if token.type in (tokenize.COMMENT, tokenize.STRING):
            continue
        pieces.append(token.string)
    return " ".join(pieces)


def test_no_new_migration_depends_on_model_metadata():
    """历史迁移不得引用 Base.metadata 建表。

    q3d4e5f6a7b8 是已提交的既成事实（1a115cf），本轮不改写它；但它导致干净库重放
    结果随当前模型变化。新迁移一律禁止重复这一模式，只能写死当时的 DDL。
    """
    offenders = []
    versions = Path(__file__).resolve().parents[2] / "migrations" / "versions"
    for path in versions.glob("*.py"):
        name = path.name.split("_")[0]
        code = _code_without_comments(path.read_text(encoding="utf-8"))
        if "Base.metadata" in code and name not in LEGACY_METADATA_MIGRATIONS:
            offenders.append(path.name)
    assert offenders == [], f"以下迁移依赖模型元数据，必须改为写死 DDL：{offenders}"


# ---------- 6. 持久化：普通更新不得刷新 ----------


def test_entered_todo_at_survives_ordinary_update(db, project_factory, user_factory):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"r01-fact-{suffix}")
    user = user_factory(f"r01-fact-user-{suffix}")
    stamp = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)
    fact = Fact(
        project_id=project.id,
        fact_type=FactType.CERTIFICATION,
        fact_key=f"key-{suffix}",
        fact_value="初始值",
        version_no=1,
        created_by=user.id,
        entered_todo_at=stamp,
    )
    db.add(fact)
    db.flush()

    fact.fact_value = "普通内容更新"
    db.flush()

    assert fact.entered_todo_at == stamp
