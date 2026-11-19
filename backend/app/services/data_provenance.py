"""P16 数据来源清点：原型/模拟状态与历史本地数据。

这个服务只做只读清点，不修改任何业务表：
- 项目与账号按明确的命名标记归类，避免把 `gz-base` 误判成原型；
- 历史本地数据以 `import_batches` 为唯一依据，只有 `completed` 且 `delta` 为正的批次才算残留；
- `rolled_back` 批次保留在清单里，作为“已回滚、未保留原文”的证据，但不计入残留行数。
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ImportBatch, Project, User
from app.models.enums import ImportBatchStatus

PROTOTYPE_MARKERS = (
    "demo",
    "mock",
    "prototype",
    "test",
    "edge",
    "sample",
    "演示",
    "测试",
    "原型",
    "模拟",
    "样例",
    "边界",
)
SEED_MARKERS = ("seed",)
PROBE_MARKERS = ("probe",)
DEMO_MARKERS = ("demo", "演示", "原型", "模拟")
LEGACY_SOURCE = "legacy_local"


def _matched_markers(text: str, markers: tuple[str, ...]) -> list[str]:
    lowered = text.casefold()
    return [marker for marker in markers if marker.casefold() in lowered]


def _classify_project(project: Project) -> tuple[str, list[str]]:
    markers = _matched_markers(f"{project.code} {project.name}", PROTOTYPE_MARKERS)
    if markers:
        return "test_or_prototype", markers
    return "production", []


def _classify_user(user: User) -> str:
    text = f"{user.username} {user.display_name}"
    if _matched_markers(text, PROBE_MARKERS):
        return "probe"
    if _matched_markers(text, SEED_MARKERS):
        return "seed"
    if _matched_markers(text, DEMO_MARKERS):
        return "demo"
    return "normal"


def _batch_delta(batch: ImportBatch) -> dict[str, int]:
    counts = batch.counts if isinstance(batch.counts, dict) else {}
    delta = counts.get("delta") if isinstance(counts, dict) else None
    if not isinstance(delta, dict):
        return {}
    return {
        str(key): int(value)
        for key, value in delta.items()
        if isinstance(value, int) and not isinstance(value, bool)
    }


def _is_retained(batch: ImportBatch, delta: dict[str, int]) -> bool:
    return batch.status == ImportBatchStatus.COMPLETED and any(value > 0 for value in delta.values())


def collect_data_provenance(db: Session) -> dict:
    projects = db.scalars(select(Project).order_by(Project.created_at, Project.code)).all()
    users = db.scalars(select(User).order_by(User.username)).all()
    batches = db.execute(
        select(ImportBatch, Project.code)
        .join(Project, Project.id == ImportBatch.project_id)
        .order_by(ImportBatch.created_at, ImportBatch.id)
    ).all()

    project_rows: list[dict] = []
    classification_counts: dict[str, int] = {}
    for project in projects:
        classification, markers = _classify_project(project)
        classification_counts[classification] = classification_counts.get(classification, 0) + 1
        project_rows.append(
            {
                "id": str(project.id),
                "code": project.code,
                "name": project.name,
                "status": project.status.value if hasattr(project.status, "value") else str(project.status),
                "classification": classification,
                "markers": markers,
            }
        )

    user_rows: list[dict] = []
    seed_accounts = 0
    probe_accounts = 0
    demo_accounts = 0
    for user in users:
        classification = _classify_user(user)
        if classification == "seed":
            seed_accounts += 1
        elif classification == "probe":
            probe_accounts += 1
        elif classification == "demo":
            demo_accounts += 1
        user_rows.append(
            {
                "id": str(user.id),
                "username": user.username,
                "display_name": user.display_name,
                "classification": classification,
            }
        )

    legacy_rows: list[dict] = []
    retained_rows: dict[str, int] = {}
    retained_batches = 0
    for batch, project_code in batches:
        delta = _batch_delta(batch)
        retained = _is_retained(batch, delta)
        if retained:
            retained_batches += 1
            for table, value in delta.items():
                if value > 0:
                    retained_rows[table] = retained_rows.get(table, 0) + value
        counts = batch.counts if isinstance(batch.counts, dict) else {}
        source_rows = counts.get("source_rows")
        legacy_rows.append(
            {
                "id": str(batch.id),
                "project_code": project_code,
                "source_system": batch.source_system,
                "mapping_version": batch.mapping_version,
                "status": batch.status.value if hasattr(batch.status, "value") else str(batch.status),
                "source_rows": source_rows if isinstance(source_rows, int) else None,
                "delta": delta,
                "retained": retained,
                "started_at": batch.started_at,
                "finished_at": batch.finished_at,
                "rollback_note": batch.rollback_note,
            }
        )

    prototype_projects = classification_counts.get("test_or_prototype", 0)
    return {
        "generated_at": datetime.now(timezone.utc),
        "summary": {
            "projects_total": len(projects),
            "projects_by_classification": classification_counts,
            "prototype_projects": prototype_projects,
            "seed_accounts": seed_accounts,
            "probe_accounts": probe_accounts,
            "demo_accounts": demo_accounts,
            "legacy_batches_total": len(legacy_rows),
            "legacy_batches_retained": retained_batches,
            "retained_legacy_rows": retained_rows,
        },
        "projects": project_rows,
        "users": user_rows,
        "legacy_imports": legacy_rows,
    }
