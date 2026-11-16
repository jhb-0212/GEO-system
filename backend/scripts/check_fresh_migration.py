"""在临时空库上验证 Alembic 迁移链，可选跑种子与全量测试。

用法（在 backend 目录）：
    .venv\\Scripts\\python.exe scripts\\check_fresh_migration.py
    .venv\\Scripts\\python.exe scripts\\check_fresh_migration.py --with-tests

脚本只创建/删除 `geo_migration_check_*` 临时库，不碰开发库；失败时默认保留临时库，
方便查看现场，成功或显式 `--drop-on-failure` 才删除。
"""

import argparse
import os
import subprocess
import sys
import uuid
from pathlib import Path

import psycopg
from sqlalchemy.engine import make_url

BACKEND_DIR = Path(__file__).resolve().parents[1]
ROOT_DIR = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import settings  # noqa: E402


def _admin_connection(url):
    return psycopg.connect(
        host=url.host,
        port=url.port,
        user=url.username,
        password=url.password,
        dbname="postgres",
        autocommit=True,
    )


def _run(command: list[str], *, cwd: Path, env: dict[str, str]) -> None:
    print("+", " ".join(command))
    subprocess.run(command, cwd=cwd, env=env, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--with-tests", action="store_true", help="迁移后执行 seed + pytest")
    parser.add_argument("--drop-on-failure", action="store_true", help="失败时也删除临时库")
    args = parser.parse_args()

    source_url = make_url(settings.database_url)
    db_name = f"geo_migration_check_{uuid.uuid4().hex[:8]}"
    temp_url = source_url.set(database=db_name)
    env = {**os.environ, "DATABASE_URL": temp_url.render_as_string(hide_password=False)}
    created = False
    failed = False

    try:
        with _admin_connection(source_url) as conn:
            conn.execute(f'CREATE DATABASE "{db_name}"')
        created = True
        print(f"created {db_name}")

        _run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=ROOT_DIR,
            env=env,
        )
        _run(
            [sys.executable, "-m", "alembic", "check"],
            cwd=ROOT_DIR,
            env=env,
        )
        _run(
            [sys.executable, "scripts/seed.py"],
            cwd=BACKEND_DIR,
            env=env,
        )
        if args.with_tests:
            _run(
                [sys.executable, "-m", "pytest", "tests", "-q"],
                cwd=BACKEND_DIR,
                env=env,
            )
        print(f"fresh migration OK: {db_name}")
        return 0
    except Exception:
        failed = True
        raise
    finally:
        if created and (not failed or args.drop_on_failure):
            with _admin_connection(source_url) as conn:
                conn.execute(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)')
            print(f"dropped {db_name}")
        elif created:
            print(f"kept {db_name} for inspection")


if __name__ == "__main__":
    raise SystemExit(main())
