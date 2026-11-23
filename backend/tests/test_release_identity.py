from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "deploy" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from release_common import (  # noqa: E402
    ReleaseError,
    find_git,
    parse_remote_tag,
    validate_manifest_static,
)

spec = importlib.util.spec_from_file_location("create_release_manifest", SCRIPTS / "create_release_manifest.py")
assert spec and spec.loader
create_release_manifest = importlib.util.module_from_spec(spec)
spec.loader.exec_module(create_release_manifest)

verify_spec = importlib.util.spec_from_file_location("verify_release", SCRIPTS / "verify_release.py")
assert verify_spec and verify_spec.loader
verify_release = importlib.util.module_from_spec(verify_spec)
verify_spec.loader.exec_module(verify_release)

BACKEND_DIGEST = "sha256:" + "a" * 64
FRONTEND_DIGEST = "sha256:" + "b" * 64


def run_git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        [find_git(), "-C", str(repo), *args],
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError((result.stderr or result.stdout).strip())
    return result.stdout.strip()


def make_repo(tmp_path: Path) -> tuple[Path, Path]:
    remote = tmp_path / "remote.git"
    subprocess.run([find_git(), "init", "--bare", "--initial-branch=main", str(remote)], check=True, capture_output=True)
    work = tmp_path / "work"
    subprocess.run([find_git(), "init", "--initial-branch=main", str(work)], check=True, capture_output=True)
    run_git(work, "config", "user.name", "Release Test")
    run_git(work, "config", "user.email", "release@example.com")
    (work / "README.md").write_text("release test\n", encoding="utf-8")
    run_git(work, "add", "README.md")
    run_git(work, "commit", "-m", "init")
    run_git(work, "tag", "-a", "v0.1.0", "-m", "release v0.1.0")
    run_git(work, "remote", "add", "origin", str(remote))
    run_git(work, "push", "-u", "origin", "main")
    run_git(work, "push", "origin", "refs/tags/v0.1.0")
    run_git(work, "fetch", "origin", "main:refs/remotes/origin/main")
    run_git(work, "checkout", "--detach", "refs/tags/v0.1.0")
    return work, remote


def test_collect_source_accepts_annotated_tag_on_clean_checkout(tmp_path: Path) -> None:
    work, _remote = make_repo(tmp_path)
    source = create_release_manifest.collect_source("v0.1.0", cwd=work)
    assert source["tag"] == "v0.1.0"
    assert source["tag_object_sha"] == run_git(work, "rev-parse", "refs/tags/v0.1.0")
    assert source["commit"] == run_git(work, "rev-parse", "HEAD")
    assert source["source_tree_sha"] == run_git(work, "rev-parse", "HEAD^{tree}")
    assert len(source["source_snapshot_sha256"]) == 64


def test_collect_source_rejects_lightweight_tag(tmp_path: Path) -> None:
    work, _remote = make_repo(tmp_path)
    run_git(work, "checkout", "main")
    run_git(work, "tag", "v0.2.0")
    run_git(work, "push", "origin", "refs/tags/v0.2.0")
    run_git(work, "fetch", "origin", "refs/tags/v0.2.0:refs/tags/v0.2.0", "--force")
    run_git(work, "checkout", "--detach", "refs/tags/v0.2.0")
    with pytest.raises(ReleaseError, match="annotated tag"):
        create_release_manifest.collect_source("v0.2.0", cwd=work)


def test_collect_source_rejects_head_not_tag(tmp_path: Path) -> None:
    work, _remote = make_repo(tmp_path)
    run_git(work, "checkout", "main")
    (work / "README.md").write_text("ahead\n", encoding="utf-8")
    run_git(work, "add", "README.md")
    run_git(work, "commit", "-m", "ahead")
    with pytest.raises(ReleaseError, match="HEAD"):
        create_release_manifest.collect_source("v0.1.0", cwd=work)


def test_collect_source_rejects_dirty_worktree(tmp_path: Path) -> None:
    work, _remote = make_repo(tmp_path)
    (work / "README.md").write_text("dirty\n", encoding="utf-8")
    with pytest.raises(ReleaseError, match="工作区不干净"):
        create_release_manifest.collect_source("v0.1.0", cwd=work)


def test_collect_source_rejects_moved_tag(tmp_path: Path) -> None:
    work, _remote = make_repo(tmp_path)
    old_tag_object = run_git(work, "rev-parse", "refs/tags/v0.1.0")
    run_git(work, "checkout", "main")
    (work / "README.md").write_text("next\n", encoding="utf-8")
    run_git(work, "add", "README.md")
    run_git(work, "commit", "-m", "next")
    run_git(work, "tag", "-f", "-a", "v0.1.0", "-m", "moved")
    run_git(work, "push", "--force", "origin", "refs/tags/v0.1.0")
    run_git(work, "update-ref", "refs/tags/v0.1.0", old_tag_object)
    run_git(work, "checkout", "--detach", "refs/tags/v0.1.0")
    with pytest.raises(ReleaseError, match="远端 tag object 不一致"):
        create_release_manifest.collect_source("v0.1.0", cwd=work)


def _source() -> dict[str, str]:
    return {
        "tag": "v0.1.0",
        "tag_object_sha": "1" * 40,
        "commit": "2" * 40,
        "source_tree_sha": "3" * 40,
        "source_snapshot_sha256": "4" * 64,
        "main_commit_at_release": "5" * 40,
        "created_at": "2026-11-23T00:00:00+00:00",
    }


def test_build_manifest_uses_registry_digest_as_identity() -> None:
    manifest = create_release_manifest._build_manifest(
        tag="v0.1.0",
        source=_source(),
        backend_digest=BACKEND_DIGEST,
        frontend_digest=FRONTEND_DIGEST,
        owner="Example",
        backend_ref=f"ghcr.io/example/geo-backend@{BACKEND_DIGEST}",
        frontend_ref=f"ghcr.io/example/geo-frontend@{FRONTEND_DIGEST}",
        ci_run_id="123456",
        ci_run_url="https://github.com/example/repo/actions/runs/123456",
        ci_workflow="backend-ci",
        ci_conclusion="success",
    )
    assert manifest["schema_version"] == 2
    assert manifest["build_environment"] == "github-actions"
    assert manifest["images"]["backend"]["repo_digest"] == BACKEND_DIGEST
    assert manifest["images"]["frontend"]["repo_digest"] == FRONTEND_DIGEST
    assert "image_id" not in manifest["images"]["backend"]
    assert validate_manifest_static(manifest) == []


def test_build_manifest_rejects_ref_digest_mismatch() -> None:
    with pytest.raises(ReleaseError, match="digest 与 repo_digest 不一致"):
        create_release_manifest._build_manifest(
            tag="v0.1.0",
            source=_source(),
            backend_digest=BACKEND_DIGEST,
            frontend_digest=FRONTEND_DIGEST,
            owner="example",
            backend_ref=f"ghcr.io/example/geo-backend@{FRONTEND_DIGEST}",
            frontend_ref=f"ghcr.io/example/geo-frontend@{FRONTEND_DIGEST}",
            ci_run_id="123456",
            ci_run_url="https://github.com/example/repo/actions/runs/123456",
            ci_workflow="backend-ci",
            ci_conclusion="success",
        )


def test_build_manifest_rejects_non_success_ci() -> None:
    with pytest.raises(ReleaseError, match="conclusion"):
        create_release_manifest._build_manifest(
            tag="v0.1.0",
            source=_source(),
            backend_digest=BACKEND_DIGEST,
            frontend_digest=FRONTEND_DIGEST,
            owner="example",
            backend_ref="",
            frontend_ref="",
            ci_run_id="123456",
            ci_run_url="https://github.com/example/repo/actions/runs/123456",
            ci_workflow="backend-ci",
            ci_conclusion="failure",
        )


def test_validate_manifest_static_rejects_missing_identity() -> None:
    failures = validate_manifest_static({"schema_version": 2})
    assert any("tag_object_sha" in item for item in failures)
    assert any("commit" in item for item in failures)
    assert any("images" in item for item in failures)


def test_parse_remote_tag_rejects_lightweight_output() -> None:
    with pytest.raises(ReleaseError, match="peeled commit"):
        parse_remote_tag("deadbeef" * 5 + "\trefs/tags/v0.1.0\n", "v0.1.0")


def _manifest() -> dict:
    return create_release_manifest._build_manifest(
        tag="v0.1.0",
        source=_source(),
        backend_digest=BACKEND_DIGEST,
        frontend_digest=FRONTEND_DIGEST,
        owner="example",
        backend_ref="",
        frontend_ref="",
        ci_run_id="123456",
        ci_run_url="https://github.com/example/repo/actions/runs/123456",
        ci_workflow="backend-ci",
        ci_conclusion="success",
    )


def test_verify_source_matches_tag_tree_and_snapshot(tmp_path: Path) -> None:
    work, _remote = make_repo(tmp_path)
    source = create_release_manifest.collect_source("v0.1.0", cwd=work)
    assert verify_release.verify_source(source, cwd=work) == []

    source["source_snapshot_sha256"] = "0" * 64
    failures = verify_release.verify_source(source, cwd=work)
    assert any("source_snapshot_sha256" in item for item in failures)


def test_verify_manifest_checks_remote_tag_and_owner(monkeypatch: pytest.MonkeyPatch) -> None:
    manifest = _manifest()
    monkeypatch.setattr(verify_release, "verify_source", lambda item: [])
    monkeypatch.setattr(verify_release, "read_remote_tag", lambda tag: (manifest["tag_object_sha"], manifest["commit"]))
    monkeypatch.setattr(verify_release, "repo_slug", lambda: ("example", "repo"))
    assert verify_release.verify_manifest(manifest) == []

    manifest["images"]["backend"]["ref"] = "ghcr.io/other/geo-backend@" + BACKEND_DIGEST
    failures = verify_release.verify_manifest(manifest)
    assert any("不属于当前仓库" in item for item in failures)


def test_verify_compose_rejects_build_and_mismatched_image(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _manifest()
    compose_file = tmp_path / "compose.yml"
    env_file = tmp_path / ".env.prod"
    compose_file.write_text("services: {}\n", encoding="utf-8")
    env_file.write_text("BACKEND_IMAGE=x\n", encoding="utf-8")
    backend_ref = manifest["images"]["backend"]["ref"]
    frontend_ref = manifest["images"]["frontend"]["ref"]
    services = {
        name: {"image": backend_ref, "pull_policy": "always"} for name in ("migrate", "api", "worker", "beat")
    }
    services["frontend"] = {"image": frontend_ref, "pull_policy": "always"}
    monkeypatch.setattr(verify_release, "run", lambda command: json.dumps({"services": services}))
    assert verify_release.verify_compose(manifest, compose_file, env_file) == []

    services["api"] = {"image": frontend_ref, "pull_policy": "always", "build": {"context": "."}}
    failures = verify_release.verify_compose(manifest, compose_file, env_file)
    assert any("build" in item for item in failures)
    assert any("api.image" in item for item in failures)
