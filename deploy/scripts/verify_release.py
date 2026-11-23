"""部署版本核验：容器 OCI revision label 必须等于 RELEASE_COMMIT。

只读检查，不启动/修改容器。它回答的是“实际跑的是不是发布版本”，不能用
release manifest 或 CI 日志代替。

用法（仓库根目录，生产 compose 已启动后）：
    set RELEASE_COMMIT=<release-tag 解析出的 commit>   # PowerShell: $env:RELEASE_COMMIT="..."
    python deploy/scripts/verify_release.py
    python deploy/scripts/verify_release.py --manifest deploy/releases/v0.1.0.json
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_COMPOSE = ROOT_DIR / "deploy" / "docker-compose.prod.yml"
DEFAULT_ENV_FILE = ROOT_DIR / "deploy" / ".env.prod"
DEFAULT_SERVICES = ("api", "worker", "beat", "frontend")


def find_docker() -> str:
    candidate = os.environ.get("DOCKER_EXECUTABLE") or shutil.which("docker")
    if candidate:
        return candidate
    for path in (
        r"C:\Program Files\Docker\Docker\resources\bin\docker.exe",
        "/usr/bin/docker",
        "/usr/local/bin/docker",
    ):
        if Path(path).is_file():
            return path
    return "docker"


def run(command: list[str]) -> str:
    result = subprocess.run(
        command,
        cwd=ROOT_DIR,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout).strip())
    return result.stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description="校验生产容器 revision label 与 RELEASE_COMMIT")
    parser.add_argument("--expected", default=os.environ.get("RELEASE_COMMIT"))
    parser.add_argument("--manifest", type=Path, help="release manifest；给出时同时校验 commit 字段")
    parser.add_argument("--compose-file", type=Path, default=DEFAULT_COMPOSE)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--service", action="append", dest="services", help="可重复；默认 api/worker/beat/frontend")
    args = parser.parse_args()

    expected = (args.expected or "").strip()
    if not expected:
        print("FAIL 版本核验：未设置 RELEASE_COMMIT（或 --expected），拒绝用未知版本通过")
        return 1

    if args.manifest:
        if not args.manifest.is_file():
            print(f"FAIL 版本核验：manifest 不存在：{args.manifest}")
            return 1
        try:
            manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            print(f"FAIL 版本核验：manifest 不是合法 JSON：{exc}")
            return 1
        if manifest.get("commit") != expected:
            print(
                f"FAIL 版本核验：manifest.commit={manifest.get('commit')} "
                f"不等于 RELEASE_COMMIT={expected}"
            )
            return 1

    if not args.compose_file.is_file():
        print(f"FAIL 版本核验：compose 文件不存在：{args.compose_file}")
        return 1

    docker = find_docker()
    services = args.services or list(DEFAULT_SERVICES)
    failures: list[str] = []
    checked: list[tuple[str, str]] = []
    for service in services:
        try:
            compose_cmd = [
                docker,
                "compose",
                "-f",
                str(args.compose_file),
                "--env-file",
                str(args.env_file),
                "ps",
                "-q",
                service,
            ]
            container_id = run(compose_cmd)
            if not container_id:
                failures.append(f"{service}: 没有运行中的容器")
                continue
            for one_id in container_id.splitlines():
                one_id = one_id.strip()
                if not one_id:
                    continue
                revision = run(
                    [
                        docker,
                        "inspect",
                        "--format",
                        '{{index .Config.Labels "org.opencontainers.image.revision"}}',
                        one_id,
                    ]
                )
                checked.append((f"{service}:{one_id[:12]}", revision))
                if revision != expected:
                    failures.append(
                        f"{service}:{one_id[:12]}: label={revision!r}，期望={expected!r}"
                    )
        except RuntimeError as exc:
            failures.append(f"{service}: {exc}")
            continue

    print("部署版本核验：RELEASE_COMMIT =", expected)
    for service, revision in checked:
        print(f"  {service}: {revision}")
    if failures:
        print("FAIL 部署版本核验：")
        for item in failures:
            print(f"  - {item}")
        return 1
    print("OK 部署版本核验：所有已检查容器 label 与 RELEASE_COMMIT 一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())
