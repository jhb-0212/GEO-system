"""部署版本核验：manifest、digest-pinned image ref 与实际容器必须一致。

只读检查，不启动/修改容器。权威身份是 `repo_digest`（registry digest），不是
Dockerfile 里可被人工填写的 revision label；label 仍必须等于 manifest.commit。

用法（部署主机、仓库根目录，生产 compose 已启动后）：
    python deploy/scripts/verify_release.py --manifest deploy/releases/v1.0.0.json
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from release_common import (
    ROOT_DIR,
    ReleaseError,
    git,
    read_remote_tag,
    repo_slug,
    require_sha1,
    tree_snapshot_sha256,
    validate_manifest_static,
)

DEFAULT_COMPOSE = ROOT_DIR / "deploy" / "docker-compose.prod.yml"
DEFAULT_ENV_FILE = ROOT_DIR / "deploy" / ".env.prod"
BACKEND_SERVICES = ("migrate", "api", "worker", "beat")
FRONTEND_SERVICES = ("frontend",)


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
        raise ReleaseError((result.stderr or result.stdout).strip() or f"{' '.join(command)} failed")
    return result.stdout.strip()


def compose_base(compose_file: Path, env_file: Path) -> list[str]:
    return [
        find_docker(),
        "compose",
        "-f",
        str(compose_file),
        "--env-file",
        str(env_file),
    ]


def load_manifest(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ReleaseError(f"manifest 不存在：{path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ReleaseError(f"manifest 不是合法 JSON：{exc}") from exc
    if not isinstance(data, dict):
        raise ReleaseError("manifest 顶层必须是对象")
    return data


def verify_source(manifest: dict[str, Any], cwd: Path = ROOT_DIR) -> list[str]:
    failures: list[str] = []
    commit = str(manifest.get("commit", ""))
    try:
        commit = require_sha1("manifest.commit", commit)
        tree = require_sha1("checkout tree", git("rev-parse", f"{commit}^{{tree}}", cwd=cwd))
        if tree != manifest.get("source_tree_sha"):
            failures.append(
                f"checkout tree={tree} 不等于 manifest.source_tree_sha={manifest.get('source_tree_sha')}"
            )
        listing = git("ls-tree", "-r", "--full-tree", commit, cwd=cwd)
        snapshot = tree_snapshot_sha256(listing)
        if snapshot != manifest.get("source_snapshot_sha256"):
            failures.append(
                f"checkout snapshot={snapshot} 不等于 manifest.source_snapshot_sha256="
                f"{manifest.get('source_snapshot_sha256')}"
            )
    except ReleaseError as exc:
        failures.append(f"源码身份核验失败：{exc}")
    return failures


def verify_manifest(manifest: dict[str, Any]) -> list[str]:
    failures = validate_manifest_static(manifest)
    failures.extend(verify_source(manifest))
    tag = str(manifest.get("tag", ""))
    try:
        remote_tag_object, remote_commit = read_remote_tag(tag)
    except ReleaseError as exc:
        failures.append(str(exc))
        return failures
    if remote_tag_object != manifest.get("tag_object_sha"):
        failures.append(
            f"远端 tag object={remote_tag_object} 不等于 manifest.tag_object_sha={manifest.get('tag_object_sha')}"
        )
    if remote_commit != manifest.get("commit"):
        failures.append(
            f"远端 tag commit={remote_commit} 不等于 manifest.commit={manifest.get('commit')}"
        )

    try:
        owner, _repo = repo_slug()
    except ReleaseError as exc:
        failures.append(str(exc))
        return failures
    images = manifest.get("images", {})
    for key, repo_suffix in (("backend", "geo-backend"), ("frontend", "geo-frontend")):
        expected_repo = f"ghcr.io/{owner.lower()}/{repo_suffix}"
        ref = str(images.get(key, {}).get("ref", ""))
        if not ref.startswith(expected_repo + "@"):
            failures.append(f"images.{key}.ref={ref!r} 不属于当前仓库 {expected_repo}")
    return failures


def verify_compose(manifest: dict[str, Any], compose_file: Path, env_file: Path) -> list[str]:
    failures: list[str] = []
    if not compose_file.is_file():
        return [f"compose 文件不存在：{compose_file}"]
    if not env_file.is_file():
        return [f"env 文件不存在：{env_file}"]
    try:
        raw = run(compose_base(compose_file, env_file) + ["config", "--format", "json"])
        config = json.loads(raw)
    except (ReleaseError, json.JSONDecodeError) as exc:
        return [f"docker compose config 失败：{exc}"]

    services = config.get("services")
    if not isinstance(services, dict):
        return ["docker compose config 缺少 services"]
    images = manifest.get("images", {})
    backend_ref = str(images.get("backend", {}).get("ref", ""))
    frontend_ref = str(images.get("frontend", {}).get("ref", ""))
    for name in (*BACKEND_SERVICES, *FRONTEND_SERVICES):
        service = services.get(name)
        if not isinstance(service, dict):
            failures.append(f"compose 缺少服务：{name}")
            continue
        if "build" in service:
            failures.append(f"{name} 仍包含 build；生产编排必须只使用 digest-pinned image")
        expected = backend_ref if name in BACKEND_SERVICES else frontend_ref
        actual = str(service.get("image", ""))
        if actual != expected:
            failures.append(f"{name}.image={actual!r}，期望 {expected!r}")
        if service.get("pull_policy") != "always":
            failures.append(f"{name}.pull_policy 必须为 always")
    return failures


def inspect_container(container_id: str, expected_ref: str, expected_digest: str, expected_commit: str) -> tuple[list[str], dict[str, Any]]:
    failures: list[str] = []
    raw = run([find_docker(), "inspect", container_id])
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ReleaseError(f"docker inspect 输出不是 JSON：{exc}") from exc
    if not isinstance(data, list) or not data:
        raise ReleaseError(f"docker inspect 没有返回容器：{container_id}")
    item = data[0]
    labels = (item.get("Config") or {}).get("Labels") or {}
    revision = labels.get("org.opencontainers.image.revision")
    repo_digests = item.get("RepoDigests") or []
    summary = {
        "container": container_id[:12],
        "revision": revision,
        "repo_digests": repo_digests,
    }
    if revision != expected_commit:
        failures.append(
            f"{container_id[:12]}: revision={revision!r}，期望 {expected_commit!r}"
        )
    if not isinstance(repo_digests, list) or not any(str(d).endswith("@" + expected_digest) for d in repo_digests):
        failures.append(
            f"{container_id[:12]}: RepoDigests={repo_digests!r} 不包含 {expected_digest}"
        )
    if not any(str(d).startswith(expected_ref.rsplit("@", 1)[0] + "@") for d in repo_digests):
        failures.append(
            f"{container_id[:12]}: RepoDigests 不属于 {expected_ref.rsplit('@', 1)[0]}"
        )
    return failures, summary


def verify_containers(manifest: dict[str, Any], compose_file: Path, env_file: Path) -> list[str]:
    failures: list[str] = []
    images = manifest.get("images", {})
    backend_ref = str(images.get("backend", {}).get("ref", ""))
    backend_digest = str(images.get("backend", {}).get("repo_digest", ""))
    frontend_ref = str(images.get("frontend", {}).get("ref", ""))
    frontend_digest = str(images.get("frontend", {}).get("repo_digest", ""))
    commit = str(manifest.get("commit", ""))

    for name in BACKEND_SERVICES + FRONTEND_SERVICES:
        expected_ref = backend_ref if name in BACKEND_SERVICES else frontend_ref
        expected_digest = backend_digest if name in BACKEND_SERVICES else frontend_digest
        selector = "-aq" if name == "migrate" else "-q"
        try:
            container_ids = run(compose_base(compose_file, env_file) + ["ps", selector, name]).splitlines()
        except ReleaseError as exc:
            failures.append(f"{name}: {exc}")
            continue
        container_ids = [one.strip() for one in container_ids if one.strip()]
        if not container_ids:
            failures.append(f"{name}: 没有容器（migrate 必须保留一次性容器供审计）")
            continue
        for container_id in container_ids:
            try:
                item_failures, summary = inspect_container(
                    container_id, expected_ref, expected_digest, commit
                )
            except ReleaseError as exc:
                failures.append(f"{name}:{container_id[:12]}: {exc}")
                continue
            failures.extend(f"{name}:{failure}" for failure in item_failures)
            print(
                f"  {name}:{summary['container']} revision={summary['revision']} "
                f"RepoDigests={summary['repo_digests']}"
            )
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description="校验 release manifest、digest-pinned image 与实际容器")
    parser.add_argument("--manifest", type=Path, required=True, help="release manifest 路径")
    parser.add_argument("--compose-file", type=Path, default=DEFAULT_COMPOSE)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    args = parser.parse_args()

    try:
        manifest = load_manifest(args.manifest)
    except ReleaseError as exc:
        print(f"FAIL 部署版本核验：{exc}")
        return 1

    failures = verify_manifest(manifest)
    if failures:
        print("FAIL 部署版本核验：manifest/tag 身份不一致")
        for item in failures:
            print(f"  - {item}")
        return 1

    failures = verify_compose(manifest, args.compose_file, args.env_file)
    if failures:
        print("FAIL 部署版本核验：compose 与 manifest 不一致")
        for item in failures:
            print(f"  - {item}")
        return 1

    print(f"部署版本核验：tag={manifest.get('tag')} commit={manifest.get('commit')}")
    print(f"  backend={manifest['images']['backend']['ref']}")
    print(f"  frontend={manifest['images']['frontend']['ref']}")
    failures = verify_containers(manifest, args.compose_file, args.env_file)
    if failures:
        print("FAIL 部署版本核验：容器身份不一致")
        for item in failures:
            print(f"  - {item}")
        return 1
    print("OK 部署版本核验：所有容器 revision 与 RepoDigest 均与 manifest 一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())
