"""Release identity helpers shared by manifest generation and deployment verification."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[2]
SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
IMAGE_REF_RE = re.compile(r"^[a-z0-9][a-z0-9._/-]*@sha256:[0-9a-f]{64}$")


class ReleaseError(RuntimeError):
    """A release identity check failed closed."""


def find_git() -> str:
    candidate = os.environ.get("GIT_EXECUTABLE") or shutil.which("git")
    if candidate:
        return candidate
    for path in (
        r"C:\Program Files\Git\cmd\git.exe",
        r"C:\Program Files\Git\bin\git.exe",
        "/usr/bin/git",
        "/usr/local/bin/git",
    ):
        if Path(path).is_file():
            return path
    return "git"


def git(*args: str, cwd: Path = ROOT_DIR) -> str:
    result = subprocess.run(
        [find_git(), *args],
        cwd=cwd,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise ReleaseError((result.stderr or result.stdout).strip() or f"git {' '.join(args)} failed")
    return result.stdout.strip()


def require_sha1(label: str, value: str) -> str:
    value = (value or "").strip()
    if not SHA1_RE.fullmatch(value):
        raise ReleaseError(f"{label} 不是 40 位小写 commit/tree SHA：{value!r}")
    return value


def require_digest(label: str, value: str) -> str:
    value = (value or "").strip()
    if not DIGEST_RE.fullmatch(value):
        raise ReleaseError(f"{label} 不是 sha256:<64 hex>：{value!r}")
    return value


def require_image_ref(label: str, ref: str, expected_repo: str, digest: str) -> str:
    ref = (ref or "").strip()
    if not IMAGE_REF_RE.fullmatch(ref):
        raise ReleaseError(f"{label} 不是 digest-pinned 镜像引用：{ref!r}")
    if not ref.startswith(expected_repo + "@"):
        raise ReleaseError(f"{label} 必须属于 {expected_repo}：{ref!r}")
    if not ref.endswith("@" + digest):
        raise ReleaseError(f"{label} 的 digest 与 repo_digest 不一致：{ref!r}")
    return ref


def repo_slug(cwd: Path = ROOT_DIR) -> tuple[str, str]:
    """Return (owner, repo) from the origin remote, independent of token/SSH form."""
    url = git("remote", "get-url", "origin", cwd=cwd).strip()
    if url.startswith("git@github.com:"):
        path = url.split(":", 1)[1]
    elif "github.com/" in url:
        path = url.split("github.com/", 1)[1]
    else:
        raise ReleaseError(f"origin 不是 GitHub 仓库：{url!r}")
    path = path.removesuffix(".git").strip("/")
    parts = path.split("/")
    if len(parts) != 2 or not all(parts):
        raise ReleaseError(f"无法从 origin 解析 owner/repo：{url!r}")
    return parts[0], parts[1]


def parse_remote_tag(output: str, tag: str) -> tuple[str, str]:
    """Parse `git ls-remote origin refs/tags/<tag>` into (tag_object, commit)."""
    ref = f"refs/tags/{tag}"
    rows: dict[str, str] = {}
    for line in output.splitlines():
        parts = line.split("\t")
        if len(parts) != 2:
            continue
        sha, name = parts[0].strip(), parts[1].strip()
        if name in (ref, ref + "^{}"):
            rows[name] = sha
    tag_object = require_sha1(f"remote tag object {tag}", rows.get(ref, ""))
    commit = require_sha1(f"remote peeled commit {tag}", rows.get(ref + "^{}", ""))
    return tag_object, commit


def read_remote_tag(tag: str, cwd: Path = ROOT_DIR) -> tuple[str, str]:
    # Ask for all tags: an exact pattern may omit the peeled `^{}` companion line
    # on some Git versions, which would make annotated tags look lightweight.
    return parse_remote_tag(git("ls-remote", "origin", "refs/tags/*", cwd=cwd), tag)


def tree_snapshot_sha256(listing: str) -> str:
    """Deterministic digest of `git ls-tree -r --full-tree <commit>` output."""
    return hashlib.sha256(((listing + "\n") if listing else "").encode("utf-8")).hexdigest()


def load_json(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise ReleaseError(f"{label} 不存在：{path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ReleaseError(f"{label} 不是合法 JSON：{exc}") from exc
    if not isinstance(data, dict):
        raise ReleaseError(f"{label} 顶层必须是对象")
    return data


def validate_manifest_static(manifest: dict[str, Any]) -> list[str]:
    """Validate schema independent of Docker. Returns a list of failures."""
    failures: list[str] = []
    if manifest.get("schema_version") != 2:
        failures.append("schema_version 必须为 2")
    if not str(manifest.get("tag", "")).startswith("v"):
        failures.append("tag 必须是 v*")
    for field in ("tag_object_sha", "commit", "source_tree_sha"):
        try:
            require_sha1(field, str(manifest.get(field, "")))
        except ReleaseError as exc:
            failures.append(str(exc))
    snapshot = str(manifest.get("source_snapshot_sha256", ""))
    if not re.fullmatch(r"[0-9a-f]{64}", snapshot):
        failures.append("source_snapshot_sha256 必须是 64 位小写 hex")
    if manifest.get("build_environment") != "github-actions":
        failures.append("build_environment 必须为 github-actions")
    ci = manifest.get("ci")
    if not isinstance(ci, dict):
        failures.append("ci 必须是对象")
    else:
        if ci.get("workflow") != "backend-ci":
            failures.append("ci.workflow 必须为 backend-ci")
        if ci.get("head_sha") != manifest.get("commit"):
            failures.append("ci.head_sha 必须等于 manifest.commit")
        if ci.get("conclusion") != "success":
            failures.append("ci.conclusion 必须为 success")
        if not str(ci.get("run_id", "")).strip():
            failures.append("ci.run_id 不能为空")
        if not str(ci.get("run_url", "")).startswith("https://"):
            failures.append("ci.run_url 必须是 https URL")
    images = manifest.get("images")
    if not isinstance(images, dict):
        failures.append("images 必须是对象")
        return failures
    for key, repo_suffix in (("backend", "geo-backend"), ("frontend", "geo-frontend")):
        item = images.get(key)
        if not isinstance(item, dict):
            failures.append(f"images.{key} 必须是对象")
            continue
        digest = str(item.get("repo_digest", ""))
        try:
            require_digest(f"images.{key}.repo_digest", digest)
        except ReleaseError as exc:
            failures.append(str(exc))
        ref = str(item.get("ref", ""))
        if not IMAGE_REF_RE.fullmatch(ref):
            failures.append(f"images.{key}.ref 不是 digest-pinned 引用")
        elif not ref.endswith("@" + digest):
            failures.append(f"images.{key}.ref 与 repo_digest 不一致")
        elif f"/{repo_suffix}@" not in ref:
            failures.append(f"images.{key}.ref 仓库名不以 {repo_suffix} 结尾")
        if item.get("revision") != manifest.get("commit"):
            failures.append(f"images.{key}.revision 必须等于 manifest.commit")
    return failures
