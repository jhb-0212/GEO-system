"""生成 CI 发布的 release manifest（schema 2）。

Release 只能由 annotated `v*` tag 触发的 GitHub Actions 构建：本脚本先在 tag
checkout 上做源码身份预检，构建完成后带上 registry digest 与 exact-SHA CI 证据
生成 manifest。它不构建镜像，也不读取调用者的工作区作为源码身份。

用法：
    # 构建前：预检并写 preflight JSON（必须在 tag 触发的 workflow 中运行）
    python deploy/scripts/create_release_manifest.py \
      --tag v1.0.0 --event-sha "$GITHUB_SHA" \
      --preflight-only --output "$RUNNER_TEMP/release-preflight.json"

    # 构建后：生成 manifest（digest 来自 build-push-action 输出）
    python deploy/scripts/create_release_manifest.py \
      --tag v1.0.0 --event-sha "$GITHUB_SHA" \
      --preflight "$RUNNER_TEMP/release-preflight.json" \
      --backend-digest sha256:<digest> --frontend-digest sha256:<digest> \
      --ci-run-id <id> --ci-run-url https://github.com/.../actions/runs/<id> \
      --output "$RUNNER_TEMP/release-manifest.json"
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from release_common import (
    ROOT_DIR,
    ReleaseError,
    find_git,
    git,
    read_remote_tag,
    repo_slug,
    require_digest,
    require_image_ref,
    require_sha1,
    tree_snapshot_sha256,
)

DEFAULT_OUTPUT_DIR = ROOT_DIR / "deploy" / "releases"


def validate_event_sha(commit: str, event_sha: str) -> None:
    """Require the tag's peeled commit to equal the workflow event SHA."""
    normalized = require_sha1("触发事件 github.sha", event_sha)
    if normalized != commit:
        raise ReleaseError(
            f"触发事件 github.sha={normalized} 与 tag peeled commit={commit} 不一致；"
            "tag 可能在触发后被移动"
        )


def _is_ancestor(commit: str, main_commit: str, cwd: Path) -> bool:
    result = subprocess.run(
        [find_git(), "merge-base", "--is-ancestor", commit, main_commit],
        cwd=cwd,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def collect_source(tag: str, cwd: Path = ROOT_DIR) -> dict[str, str]:
    """Fail-closed source preflight on the current checkout."""
    if not tag or not tag.startswith("v"):
        raise ReleaseError(f"release tag 必须以 v 开头：{tag!r}")
    tag_ref = f"refs/tags/{tag}"
    try:
        git("check-ref-format", tag_ref, cwd=cwd)
    except ReleaseError as exc:
        raise ReleaseError(f"tag 名称不合法：{tag!r}") from exc

    tag_type = git("cat-file", "-t", tag_ref, cwd=cwd)
    if tag_type != "tag":
        raise ReleaseError(f"{tag_ref} 必须是 annotated tag，当前类型为 {tag_type!r}（lightweight tag 拒绝）")

    tag_object = require_sha1("tag object", git("rev-parse", tag_ref, cwd=cwd))
    commit = require_sha1("tag commit", git("rev-parse", f"{tag_ref}^{{commit}}", cwd=cwd))
    remote_tag_object, remote_commit = read_remote_tag(tag, cwd=cwd)
    if remote_tag_object != tag_object:
        raise ReleaseError(
            f"远端 tag object 不一致：local={tag_object} remote={remote_tag_object}；tag 可能被移动"
        )
    if remote_commit != commit:
        raise ReleaseError(f"远端 peeled commit 不一致：local={commit} remote={remote_commit}")

    main_commit = require_sha1("origin/main", git("rev-parse", "origin/main", cwd=cwd))
    if not _is_ancestor(commit, main_commit, cwd):
        raise ReleaseError(f"tag commit {commit} 不在 origin/main {main_commit} 的历史中")

    head = require_sha1("HEAD", git("rev-parse", "HEAD", cwd=cwd))
    if head != commit:
        raise ReleaseError(f"HEAD={head} 不等于 tag commit={commit}；必须 checkout tag")

    status = git("status", "--porcelain", cwd=cwd)
    if status:
        raise ReleaseError(f"工作区不干净，拒绝生成 Release：\n{status}")

    if (cwd / ".gitmodules").exists() or git("ls-files", ".gitmodules", cwd=cwd):
        raise ReleaseError("检测到 .gitmodules；必须校验并导出固定 submodule commit，不能静默跳过")

    tree = require_sha1("tag tree", git("rev-parse", f"{commit}^{{tree}}", cwd=cwd))
    listing = git("ls-tree", "-r", "--full-tree", commit, cwd=cwd)
    snapshot = tree_snapshot_sha256(listing)

    return {
        "tag": tag,
        "tag_object_sha": tag_object,
        "commit": commit,
        "source_tree_sha": tree,
        "source_snapshot_sha256": snapshot,
        "main_commit_at_release": main_commit,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def _validate_preflight(preflight: dict[str, str], source: dict[str, str], tag: str) -> None:
    if preflight.get("tag") != tag:
        raise ReleaseError(f"preflight.tag={preflight.get('tag')!r} 不等于 --tag={tag!r}")
    for field in ("tag_object_sha", "commit", "source_tree_sha"):
        if preflight.get(field) != source[field]:
            raise ReleaseError(f"preflight.{field} 与当前 checkout 不一致；tag 或源码可能已被改写")
    if preflight.get("source_snapshot_sha256") != source["source_snapshot_sha256"]:
        raise ReleaseError("preflight.source_snapshot_sha256 与当前 tag tree 不一致")


def _build_manifest(
    tag: str,
    source: dict[str, str],
    backend_digest: str,
    frontend_digest: str,
    owner: str,
    backend_ref: str,
    frontend_ref: str,
    ci_run_id: str,
    ci_run_url: str,
    ci_workflow: str,
    ci_conclusion: str,
) -> dict:
    backend_digest = require_digest("backend digest", backend_digest)
    frontend_digest = require_digest("frontend digest", frontend_digest)
    backend_repo = f"ghcr.io/{owner.lower()}/geo-backend"
    frontend_repo = f"ghcr.io/{owner.lower()}/geo-frontend"
    backend_ref = require_image_ref(
        "backend image ref", backend_ref or f"{backend_repo}@{backend_digest}", backend_repo, backend_digest
    )
    frontend_ref = require_image_ref(
        "frontend image ref", frontend_ref or f"{frontend_repo}@{frontend_digest}", frontend_repo, frontend_digest
    )
    if ci_conclusion != "success":
        raise ReleaseError(f"CI conclusion 必须为 success，当前为 {ci_conclusion!r}")
    if ci_workflow != "backend-ci":
        raise ReleaseError(f"CI workflow 必须为 backend-ci，当前为 {ci_workflow!r}")
    if not ci_run_id.strip() or not ci_run_url.startswith("https://"):
        raise ReleaseError("CI run_id/run_url 不能为空，且 run_url 必须是 https URL")

    return {
        "schema_version": 2,
        "tag": tag,
        "tag_object_sha": source["tag_object_sha"],
        "commit": source["commit"],
        "source_tree_sha": source["source_tree_sha"],
        "source_snapshot_sha256": source["source_snapshot_sha256"],
        "main_commit_at_release": source["main_commit_at_release"],
        "build_environment": "github-actions",
        "created_at": source["created_at"],
        "ci": {
            "workflow": ci_workflow,
            "run_id": ci_run_id.strip(),
            "run_url": ci_run_url.strip(),
            "head_sha": source["commit"],
            "conclusion": ci_conclusion,
            "required_jobs": [
                "backend-test",
                "frontend-check",
                "frontend-e2e-mock",
            ],
        },
        "images": {
            "backend": {
                "ref": backend_ref,
                "repo_digest": backend_digest,
                "revision": source["commit"],
            },
            "frontend": {
                "ref": frontend_ref,
                "repo_digest": frontend_digest,
                "revision": source["commit"],
            },
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="生成 CI release manifest（schema 2）")
    parser.add_argument("--tag", required=True, help="annotated release tag，例如 v1.0.0")
    parser.add_argument(
        "--event-sha",
        required=True,
        help="触发 workflow 的 github.sha；必须与 tag peeled commit 一致",
    )
    parser.add_argument("--repo-root", type=Path, default=ROOT_DIR, help="仓库根目录；默认脚本所在仓库")
    parser.add_argument("--preflight-only", action="store_true", help="只做源码预检并写 preflight JSON")
    parser.add_argument("--preflight", type=Path, help="构建前生成的 preflight JSON")
    parser.add_argument("--backend-digest", help="backend 镜像 registry digest，sha256:<64 hex>")
    parser.add_argument("--frontend-digest", help="frontend 镜像 registry digest")
    parser.add_argument("--backend-ref", default="", help="backend digest-pinned image ref；默认按 owner 生成")
    parser.add_argument("--frontend-ref", default="", help="frontend digest-pinned image ref")
    parser.add_argument("--ci-run-id", default="", help="exact-SHA backend-ci push run id")
    parser.add_argument("--ci-run-url", default="", help="exact-SHA backend-ci push run URL")
    parser.add_argument("--ci-workflow", default="backend-ci", help="CI workflow 名")
    parser.add_argument("--ci-conclusion", default="success", help="CI 结论")
    parser.add_argument("--output", type=Path, help="输出路径；默认 preflight 到临时目录、manifest 到 deploy/releases/<tag>.json")
    args = parser.parse_args()

    try:
        source = collect_source(args.tag, cwd=args.repo_root)
        validate_event_sha(source["commit"], args.event_sha)
        if args.preflight_only:
            output = args.output or Path(tempfile.gettempdir()) / f"{args.tag}-release-preflight.json"
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(source, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(f"OK release preflight: tag={args.tag} commit={source['commit']} tag_object={source['tag_object_sha']}")
            print(f"  preflight={output}")
            return 0

        if not args.preflight:
            raise ReleaseError("生成 manifest 必须提供 --preflight（构建前预检产物）")
        preflight = json.loads(args.preflight.read_text(encoding="utf-8"))
        if not isinstance(preflight, dict):
            raise ReleaseError("preflight JSON 顶层必须是对象")
        _validate_preflight(preflight, source, args.tag)

        if not args.backend_digest or not args.frontend_digest:
            raise ReleaseError("--backend-digest 与 --frontend-digest 必填")
        owner, _repo = repo_slug(cwd=args.repo_root)
        manifest = _build_manifest(
            tag=args.tag,
            source=source,
            backend_digest=args.backend_digest,
            frontend_digest=args.frontend_digest,
            owner=owner,
            backend_ref=args.backend_ref,
            frontend_ref=args.frontend_ref,
            ci_run_id=args.ci_run_id,
            ci_run_url=args.ci_run_url,
            ci_workflow=args.ci_workflow,
            ci_conclusion=args.ci_conclusion,
        )
        output = args.output or DEFAULT_OUTPUT_DIR / f"{args.tag}.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"OK release manifest: tag={args.tag} commit={source['commit']}")
        print(f"  manifest={output}")
        print(f"  backend={manifest['images']['backend']['ref']}")
        print(f"  frontend={manifest['images']['frontend']['ref']}")
        return 0
    except (ReleaseError, json.JSONDecodeError, OSError) as exc:
        print(f"FAIL 生成 release manifest：{exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
