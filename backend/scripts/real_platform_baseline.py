"""真实平台业务基线跑数脚本（默认 4 平台 24 格，可只跑部分平台）。

边界：
- 只操作库名以 `_smoke` 结尾的临时库，默认跑完 DROP；不碰正式 `geo` 库。
- 不接收、不回显、不落库 API Key；Key 只从进程环境读取，库里只存 `credential_ref`。
- 支持 `openai_compatible`（DeepSeek/豆包/文心）与 `yuanbao_search`（腾讯云 SearchPro/TC3）。
- 元宝返回的是检索结果摘要，不是对话生成答案；结果中该平台按“元宝搜索可见性”
  解读，不能与生成式回答混为一谈。
- 默认要求 4 个平台全部 ready；可用 `--only deepseek,wenxin` 跑部分诊断轮次，
  报告会明确标注 `N/4`，该轮次不会写成 `is_baseline=true`，不能当完整 24 格使用。
- `--reuse` 复用已有 smoke 库，跳过 DROP/重建/迁移/seed；只允许四平台全量，
  旧基线轮次降级为历史轮次，本轮仍按 `round_id` 隔离统计。

用法（仓库根目录）：
    # 1) 复制配置模板，按实际模型名/接入点修改
    Copy-Item backend\\scripts\\real_platforms.example.json backend\\scripts\\real_platforms.json

    # 2) 在 API/Worker 同一进程环境配置 Key（不要写进仓库）
    $env:DEEPSEEK_API_KEY = "..."
    $env:ARK_API_KEY = "..."
    $env:QIANFAN_API_KEY = "..."
    $env:YUANBAO_SECRET_ID = "AKID..."
    $env:YUANBAO_SECRET_KEY = "..."

    # 3) 先做配置检查（不连库、不调用平台）
    .\\backend\\.venv\\Scripts\\python.exe backend\\scripts\\real_platform_baseline.py --check-only

    # 4a) 4 平台全量
    .\\backend\\.venv\\Scripts\\python.exe backend\\scripts\\real_platform_baseline.py --json

    # 4b) 只跑 DeepSeek + 文心，共 12 格
    .\\backend\\.venv\\Scripts\\python.exe backend\\scripts\\real_platform_baseline.py --only deepseek,wenxin

    # 4c) 复用已有 smoke 库：跳过重建/迁移/seed，只跑新一轮 24 格
    #     仅支持四平台全量；成功后库自动保留，不会 DROP
    .\\backend\\.venv\\Scripts\\python.exe backend\\scripts\\real_platform_baseline.py --reuse --json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

import psycopg
from alembic.config import Config
from alembic.script import ScriptDirectory
from psycopg import sql
from sqlalchemy import func, select
from sqlalchemy.engine import make_url

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.credentials import read_credential_env  # noqa: E402

DEFAULT_CONFIG = BACKEND_DIR / "scripts" / "real_platforms.example.json"
DEFAULT_DATABASE_URL = os.getenv(
    "REAL_BASELINE_DATABASE_URL",
    "postgresql+psycopg://geo:geo_dev@localhost:5433/geo_real_baseline_smoke",
)
PLATFORM_ORDER = ("deepseek", "doubao", "wenxin", "yuanbao")
CREDENTIAL_REF_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


def _db_name(database_url: str) -> str:
    name = make_url(database_url).database or ""
    if not name.endswith("_smoke"):
        raise SystemExit(f"拒绝操作非 smoke 库：{name!r}；库名必须以 _smoke 结尾")
    return name


def _admin_conn(database_url: str):
    url = make_url(database_url)
    return psycopg.connect(
        host=url.host or "localhost",
        port=url.port or 5432,
        user=url.username,
        password=url.password,
        dbname="postgres",
        autocommit=True,
    )


def _recreate_database(database_url: str) -> None:
    name = _db_name(database_url)
    with _admin_conn(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                    sql.Identifier(name)
                )
            )
            cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))


def _drop_database(database_url: str) -> None:
    name = _db_name(database_url)
    with _admin_conn(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                    sql.Identifier(name)
                )
            )


def _current_alembic_head() -> str:
    """读取仓库当前 Alembic head，避免 --reuse 在旧 schema 上跑数。"""
    config = Config(str(REPO_ROOT / "alembic.ini"))
    head = ScriptDirectory.from_config(config).get_current_head()
    if not head:
        raise SystemExit("无法读取 Alembic head；检查 alembic.ini 与 migrations/versions")
    return head


def _assert_reusable_database(database_url: str) -> None:
    """--reuse 前置检查：库存在、迁移到 head、seed 过 gz-base，否则拒绝并提示先完整跑一次。"""
    name = _db_name(database_url)
    url = make_url(database_url)
    try:
        conn = psycopg.connect(
            host=url.host or "localhost",
            port=url.port or 5432,
            user=url.username,
            password=url.password,
            dbname=name,
        )
    except psycopg.OperationalError as exc:
        raise SystemExit(
            f"--reuse 目标库 {name!r} 不存在或不可连接；先不带 --reuse 跑一次"
        ) from exc
    with conn:
        with conn.cursor() as cur:
            cur.execute(
                "select 1 from information_schema.tables "
                "where table_schema='public' and table_name='monitoring_rounds'"
            )
            if cur.fetchone() is None:
                raise SystemExit(
                    f"--reuse 目标库 {name!r} 尚未迁移；先不带 --reuse 跑一次"
                )
            cur.execute("select version_num from alembic_version")
            revision_row = cur.fetchone()
            expected_head = _current_alembic_head()
            if revision_row is None or revision_row[0] != expected_head:
                current = revision_row[0] if revision_row else "<empty>"
                raise SystemExit(
                    f"--reuse 目标库 {name!r} 迁移版本 {current} 不是最新 {expected_head}；"
                    "先执行 alembic upgrade head，避免在旧 schema 上跑数"
                )
            cur.execute("select 1 from projects where code='gz-base'")
            if cur.fetchone() is None:
                raise SystemExit(
                    f"--reuse 目标库 {name!r} 没有 gz-base 项目；先不带 --reuse 跑一次"
                )


def _run(command: list[str], *, cwd: Path, env: dict[str, str]) -> None:
    subprocess.run(command, cwd=str(cwd), env=env, check=True)


def _parse_only(value: str | None) -> tuple[str, ...]:
    """解析 --only，保持 PLATFORM_ORDER 顺序；未传则默认 4 个平台。"""
    if not value:
        return PLATFORM_ORDER
    keys = tuple(dict.fromkeys(part.strip() for part in value.split(",") if part.strip()))
    if not keys:
        raise SystemExit("--only 不能为空")
    unknown = [key for key in keys if key not in PLATFORM_ORDER]
    if unknown:
        raise SystemExit(f"--only 含未知平台：{', '.join(unknown)}")
    return tuple(key for key in PLATFORM_ORDER if key in keys)


def _is_full_baseline(platform_count: int) -> bool:
    """只有四平台全量才是正式 baseline；部分跑数只能做诊断轮次。"""
    return platform_count == len(PLATFORM_ORDER)


def _validate_reuse(selected: tuple[str, ...], reuse: bool) -> None:
    """复用基线库只允许四平台全量，避免部分跑覆盖掉已有 24 格基线。"""
    if reuse and len(selected) != len(PLATFORM_ORDER):
        raise SystemExit(
            "--reuse 只支持四平台全量 24 格；部分平台请换一个 smoke 库，或不加 --reuse"
        )


def _load_platforms(path: Path, selected: tuple[str, ...] = PLATFORM_ORDER) -> dict[str, dict[str, Any]]:
    if not path.exists():
        raise SystemExit(f"配置文件不存在：{path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    missing = [key for key in selected if key not in payload]
    if missing:
        raise SystemExit(f"配置缺平台：{', '.join(missing)}")
    unknown = [key for key in payload if key not in PLATFORM_ORDER]
    if unknown:
        raise SystemExit(f"配置含未知平台：{', '.join(unknown)}")
    return {key: payload[key] for key in selected}


def _platform_check(key: str, item: dict[str, Any]) -> dict[str, Any]:
    engine_code = str(item.get("engine_code") or key).strip()
    entry_name = str(item.get("entry_name") or "").strip()
    base_url = str(item.get("base_url") or "").strip()
    model = str(item.get("model") or "").strip()
    credential_ref = str(item.get("credential_ref") or "").strip()
    protocol = str(item.get("protocol") or "openai_compatible").strip()
    issues: list[str] = []

    if protocol not in {
        "openai_compatible",
        "yuanbao_search",
        "doubao_search",
        "deepseek_web_search",
        "wenxin_search",
    }:
        issues.append(
            f"protocol={protocol} 当前不可执行；元宝 SearchPro 用 yuanbao_search，"
            "豆包用 doubao_search，DeepSeek 联网用 deepseek_web_search，"
            "文心一言用 openai_compatible（千帆 ERNIE 对话模型）"
        )
    if not engine_code:
        issues.append("engine_code 为空")
    if not entry_name:
        issues.append("entry_name 为空")
    # 与适配器同源：先读进程环境，再回落到 .env 白名单键；
    # 只用 os.getenv 会把“只写在 .env”的密钥误报为未配置。
    credential_configured = bool(credential_ref and read_credential_env(credential_ref))
    search_protocols = {
        "openai_compatible",
        "yuanbao_search",
        "doubao_search",
        "deepseek_web_search",
        "wenxin_search",
    }
    if protocol in search_protocols:
        if protocol == "openai_compatible" and not base_url:
            issues.append("base_url 为空")
        if protocol in {"openai_compatible", "doubao_search"} and not model:
            issues.append("model 为空")
        if not credential_ref or not CREDENTIAL_REF_RE.match(credential_ref):
            issues.append("credential_ref 必须是全大写环境变量名")
        if protocol == "yuanbao_search":
            secret_key = read_credential_env("YUANBAO_SECRET_KEY")
            credential_configured = credential_configured and bool(secret_key)
            if not secret_key:
                issues.append("环境变量 YUANBAO_SECRET_KEY 未设置")
        if not credential_configured:
            issues.append(f"环境变量 {credential_ref or '<未配置>'} 未设置")

    return {
        "platform": key,
        "engine_code": engine_code,
        "entry_name": entry_name,
        "protocol": protocol,
        "base_url": base_url,
        "model": model,
        "credential_ref": credential_ref,
        "credential_configured": credential_configured,
        "ready": not issues,
        "issues": issues,
    }


def _validate_platforms(platforms: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    return [_platform_check(key, platforms[key]) for key in platforms]


def _run_baseline(args: argparse.Namespace, platforms: dict[str, dict[str, Any]]) -> dict[str, Any]:
    checks = _validate_platforms(platforms)
    blocked = [row for row in checks if not row["ready"]]
    if blocked:
        details = "; ".join(f"{row['platform']}: {' | '.join(row['issues'])}" for row in blocked)
        raise SystemExit(
            f"{len(platforms)} 个所选平台未全部 ready，拒绝跑基线（{len(platforms)}/4）：{details}"
        )

    if args.reuse:
        _assert_reusable_database(args.database_url)
    else:
        _recreate_database(args.database_url)
        env = os.environ.copy()
        env["DATABASE_URL"] = args.database_url
        env.setdefault("SEED_ADMIN_PASSWORD", "geo-admin-dev")
        _run(
            [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", "head"],
            cwd=REPO_ROOT,
            env=env,
        )
        _run(
            [sys.executable, "scripts/seed.py", "--technical-baseline"],
            cwd=BACKEND_DIR,
            env=env,
        )

    os.environ["DATABASE_URL"] = args.database_url
    from app.db.session import SessionLocal, engine as db_engine
    from app.models import (
        AiEngine,
        AiEngineEntry,
        MonitoringRound,
        MonitoringSample,
        MonitoringTask,
        Project,
        Question,
        QuestionVersion,
        User,
    )
    from app.models.enums import (
        EngineEntryType,
        EngineProtocol,
        ProjectStatus,
        QuestionStatus,
        RoundStatus,
    )
    from app.services.monitoring_batch import generate_tasks
    from app.services.monitoring_collection import run_pending_tasks
    from app.services.state_machine import ensure_round_transition
    from app.services.stats import by_engine, by_question, geo_overview

    db = SessionLocal()
    success = False
    try:
        project = db.scalar(
            select(Project).where(
                Project.code == "gz-base",
                Project.status == ProjectStatus.ACTIVE,
            )
        )
        if project is None:
            raise SystemExit("临时库没有 gz-base 项目，seed 未生效")

        question_rows = db.execute(
            select(Question, QuestionVersion)
            .join(
                QuestionVersion,
                (QuestionVersion.question_id == Question.id)
                & (QuestionVersion.version_no == Question.current_version_no),
            )
            .where(
                Question.project_id == project.id,
                QuestionVersion.project_id == project.id,
                Question.status == QuestionStatus.ACTIVE,
            )
            .order_by(Question.code)
        ).all()
        if len(question_rows) != 6:
            raise SystemExit(f"预期 6 道 active 题，实际 {len(question_rows)}")

        configured: dict[str, Any] = {}
        # 部分诊断轮次只启用 --only 选中的平台；其余入口全部停用，避免它们进入批量任务。
        for row in db.scalars(select(AiEngineEntry)).all():
            row.is_active = False
        for key, item in platforms.items():
            engine_code = item["engine_code"]
            engine = db.scalar(select(AiEngine).where(AiEngine.code == engine_code))
            if engine is None:
                raise SystemExit(f"临时库没有平台 {engine_code}")
            protocol = EngineProtocol(item["protocol"])
            entry = db.scalar(
                select(AiEngineEntry)
                .where(
                    AiEngineEntry.engine_id == engine.id,
                    AiEngineEntry.protocol == protocol,
                )
                .order_by(AiEngineEntry.created_at, AiEngineEntry.id)
            )
            if entry is None:
                entry = db.scalar(
                    select(AiEngineEntry)
                    .where(AiEngineEntry.engine_id == engine.id)
                    .order_by(AiEngineEntry.created_at, AiEngineEntry.id)
                )
            if entry is None:
                raise SystemExit(f"平台 {engine_code} 没有入口")
            entry.entry_type = EngineEntryType.API
            entry.protocol = protocol
            entry.entry_url = item["base_url"]
            if item["model"]:
                entry.model_name = item["model"]
            elif item["protocol"] == "yuanbao_search":
                entry.model_name = "yuanbao-search"
            else:
                entry.model_name = None
            entry.credential_ref = item["credential_ref"] or None
            entry.supports_search = bool(item.get("supports_search", False))
            engine.supports_citation = bool(item.get("supports_citation", False))
            entry.is_active = True
            if item["protocol"] == "yuanbao_search":
                entry.access_note = "真实平台 24 格业务基线；元宝为 SearchPro 检索结果，不是对话生成答案"
            elif engine_code == "wenxin" and item["protocol"] == "openai_compatible":
                entry.access_note = (
                    "真实平台 24 格业务基线；千帆 ERNIE 对话模型，"
                    "请求体 web_search:{enable:true} 联网，不是千帆 AI 搜索检索产品"
                )
            elif item["protocol"] == "wenxin_search":
                entry.access_note = "真实平台 24 格业务基线；检索结果口径（search_result），不是生成回答"
            elif item["protocol"] == "deepseek_web_search":
                entry.access_note = (
                    "真实平台 24 格业务基线；DeepSeek Responses 联网工具，生成回答 + url_citation"
                )
            else:
                entry.access_note = "真实平台 24 格业务基线；credential_ref 仅存环境变量名"
            configured[key] = {
                "engine_code": engine_code,
                "entry_id": str(entry.id),
                "protocol": item["protocol"],
                # 口径：生成回答(answer) vs 检索结果(search_result)，两类不得合并算同一个提及率。
                "answer_kind": (
                    "answer"
                    if item["protocol"]
                    in {"openai_compatible", "doubao_search", "deepseek_web_search"}
                    else "search_result"
                ),
            }
        db.flush()

        active_entries = db.execute(
            select(AiEngine, AiEngineEntry)
            .join(AiEngineEntry, AiEngineEntry.engine_id == AiEngine.id)
            .where(AiEngine.is_active.is_(True), AiEngineEntry.is_active.is_(True))
        ).all()
        picked = {engine.id for engine, _entry in active_entries}
        if len(picked) != len(platforms):
            raise SystemExit(
                f"预期 {len(platforms)} 个启用平台，实际 {len(picked)}；先停用非基线入口"
            )

        actor_id = db.scalar(select(User.id).where(User.is_system_admin.is_(True)).limit(1))
        if actor_id is None:
            raise SystemExit("临时库没有系统管理员，无法写批量审计")

        # 每个项目只允许一个 baseline round（部分唯一索引）。复用库时把旧基线
        # 降级为历史轮次，再建新的基线轮次；旧样本按 round_id 隔离，不混入本轮统计。
        if args.reuse:
            previous_baselines = db.scalars(
                select(MonitoringRound).where(
                    MonitoringRound.project_id == project.id,
                    MonitoringRound.is_baseline.is_(True),
                )
            ).all()
            for previous in previous_baselines:
                previous.is_baseline = False
                if previous.status in {RoundStatus.RUNNING, RoundStatus.PLANNING}:
                    previous.status = ensure_round_transition(
                        previous.status, RoundStatus.CLOSED
                    )
            if previous_baselines:
                db.flush()

        max_seq = (
            db.scalar(
                select(func.max(MonitoringRound.seq)).where(
                    MonitoringRound.project_id == project.id
                )
            )
            or 0
        )
        round_row = MonitoringRound(
            project_id=project.id,
            seq=int(max_seq) + 1,
            name=(
                "真实 4 平台 24 格业务基线"
                if _is_full_baseline(len(platforms))
                else f"真实平台部分诊断轮次（{len(platforms)}/4，{len(platforms) * 6} 格）"
            ),
            is_baseline=_is_full_baseline(len(platforms)),
            status=RoundStatus.RUNNING,
        )
        db.add(round_row)
        db.flush()

        batch = generate_tasks(
            db,
            project_id=project.id,
            round_id=round_row.id,
            actor_id=actor_id,
            expected_engine_count=len(platforms),
        )
        run_result = run_pending_tasks(
            db,
            project_id=project.id,
            round_id=round_row.id,
            adapter=None,
            rate_limiter=None,
        )
        round_row.status = ensure_round_transition(
            round_row.status, RoundStatus.COMPLETED
        )
        db.commit()

        sample_rows = db.execute(
            select(MonitoringSample, MonitoringTask)
            .join(MonitoringTask, MonitoringSample.task_id == MonitoringTask.id)
            .where(
                MonitoringSample.project_id == project.id,
                MonitoringTask.round_id == round_row.id,
            )
            .order_by(MonitoringTask.created_at, MonitoringSample.attempt_no)
        ).all()
        samples = [
            {
                "task_id": str(task.id),
                "sample_id": str(sample.id),
                "status": getattr(sample.status, "value", str(sample.status)),
                "failure_code": getattr(sample.failure_code, "value", sample.failure_code),
                "failure_note": sample.failure_note,
                "brand_mentioned": sample.brand_mentioned,
                "answer_kind": getattr(sample.answer_kind, "value", sample.answer_kind),
                "answer_chars": len(sample.raw_answer or ""),
            }
            for sample, task in sample_rows
        ]
        status_counts = {
            status: sum(1 for row in samples if row["status"] == status)
            for status in ("hit", "miss", "failed", "pending", "running", "manual_review")
        }
        overview = geo_overview(db, project.id, round_id=round_row.id)
        answer_platforms = [
            key for key, cfg in configured.items() if cfg["answer_kind"] == "answer"
        ]
        search_platforms = [
            key for key, cfg in configured.items() if cfg["answer_kind"] == "search_result"
        ]
        kind_note = ""
        if answer_platforms and search_platforms:
            kind_note = (
                f" 口径：{len(answer_platforms)} 个平台为生成回答"
                f"（{'/'.join(answer_platforms)}），{len(search_platforms)} 个平台为检索结果"
                f"（{'/'.join(search_platforms)}）；overview.mention_rate 是混合口径，"
                "必须按 by_engine 分平台解读，两类不得合并算一个提及率。"
            )
        success = True
        return {
            "mode": (
                "real-platform-24-cell"
                if _is_full_baseline(len(platforms))
                else f"real-platform-partial-{len(platforms) * 6}-cell"
            ),
            "platform_count": len(platforms),
            "cell_count": len(platforms) * len(question_rows),
            "is_baseline": _is_full_baseline(len(platforms)),
            "database": _db_name(args.database_url),
            "round_id": str(round_row.id),
            "project_code": project.code,
            "platforms": configured,
            "checks": checks,
            "question_count": len(question_rows),
            "engine_count": len(picked),
            "batch": batch,
            "run": run_result,
            "status_counts": status_counts,
            "by_engine": by_engine(db, project.id, round_id=round_row.id),
            "by_question": by_question(db, project.id, round_id=round_row.id),
            "overview": overview,
            "samples": samples,
            "boundary": (
                (
                    "真实 4 平台 24 格业务基线；若 failure_code 非空，按失败原因排查，不用本地模型补数。"
                    if len(platforms) == 4
                    else f"部分诊断轮次：仅 {len(platforms)}/4 平台，共 {len(platforms) * len(question_rows)} 格；"
                    "is_baseline=false，未纳入平台不参与统计，不能当完整 24 格。"
                )
                + kind_note
            ),
        }
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
        db_engine.dispose()
        if success and not args.keep and not args.reuse:
            _drop_database(args.database_url)
        elif not success:
            print(
                f"跑数失败，保留临时库 {_db_name(args.database_url)} 供排查；确认后手工 DROP。",
                file=sys.stderr,
            )
        elif args.reuse:
            print(
                f"复用库 {_db_name(args.database_url)} 已保留（--reuse 不自动 DROP）。",
                file=sys.stderr,
            )


def main() -> int:
    parser = argparse.ArgumentParser(description="真实平台业务基线跑数（默认 4 平台 24 格，可跑部分平台）")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--database-url", default=DEFAULT_DATABASE_URL)
    parser.add_argument(
        "--only",
        help="只跑指定平台，逗号分隔，如 deepseek,wenxin；不传则 4 个平台全跑",
    )
    parser.add_argument("--check-only", action="store_true", help="只检查配置和凭据，不建库、不调用平台")
    parser.add_argument(
        "--reuse",
        action="store_true",
        help="复用已有 smoke 库，跳过重建/迁移/seed；仅支持四平台全量，成功后库自动保留",
    )
    parser.add_argument("--keep", action="store_true", help="保留临时库，便于查样本")
    parser.add_argument("--json", action="store_true", help="输出完整 JSON")
    args = parser.parse_args()

    try:
        selected = _parse_only(args.only)
        _validate_reuse(selected, args.reuse)
        platforms = _load_platforms(args.config, selected)
        checks = _validate_platforms(platforms)
    except Exception as exc:
        print(f"配置读取失败：{exc}", file=sys.stderr)
        return 1

    if args.check_only:
        payload = {
            "mode": "check-only",
            "config": str(args.config),
            "only": list(selected),
            "platform_count": len(selected),
            "all_ready": all(row["ready"] for row in checks),
            "checks": checks,
        }
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(f"selected: {', '.join(selected)} ({len(selected)}/4)")
            for row in checks:
                flag = "READY" if row["ready"] else "BLOCKED"
                print(f"[{flag}] {row['platform']} -> {row['engine_code']} ({row['protocol']})")
                print(f"  url={row['base_url'] or '-'} model={row['model'] or '-'} ref={row['credential_ref'] or '-'} key={'SET' if row['credential_configured'] else 'MISSING'}")
                for issue in row["issues"]:
                    print(f"  - {issue}")
        return 0

    try:
        result = _run_baseline(args, platforms)
    except subprocess.CalledProcessError as exc:
        print(f"子进程失败：{exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"跑数失败：{exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        overview = result["overview"]
        print(f"临时库：{result['database']}")
        print(f"平台 {result['platform_count']}/4 / 格数 {result['cell_count']} / 题目 {result['question_count']}")
        print(f"批量：{result['batch']}")
        print(f"状态：{result['status_counts']}")
        print(f"有效回答：{overview['valid_answers']}；失败样本：{overview['counts']['failed_samples']}")
        print(f"提及率：{overview['mention_rate']}；引用份额：{overview['citation_share']}")
        print(overview["statement"])
        print(result["boundary"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
