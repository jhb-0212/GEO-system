import importlib.util
import shutil
import subprocess
from pathlib import Path

import pytest


def _git_executable() -> str:
    candidate = shutil.which("git")
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
    raise RuntimeError("git executable not found")


GIT = _git_executable()


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        [GIT, *args],
        cwd=repo,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError((result.stderr or result.stdout).strip())
    return result.stdout.strip()


def _load_script():
    path = Path(__file__).resolve().parents[1] / "scripts" / "check_migration_immutable.py"
    spec = importlib.util.spec_from_file_location("migration_guard", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _init_repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "guard-test@example.com")
    _git(repo, "config", "user.name", "Guard Test")
    migrations = repo / "migrations" / "versions"
    migrations.mkdir(parents=True)
    (migrations / "0001_base.py").write_text(
        '"""base"""\nrevision = "0001_base"\n',
        encoding="utf-8",
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "base")
    return repo, _git(repo, "rev-parse", "HEAD")


def _run(module, repo: Path, capsys, event: str, comparison: str, base: str, head: str = "HEAD"):
    module.ROOT_DIR = repo
    rc = module.main(
        [
            "--event",
            event,
            "--comparison",
            comparison,
            "--base",
            base,
            "--head",
            head,
        ]
    )
    return rc, capsys.readouterr().out


def _add_migration(repo: Path, name: str = "0002_new.py") -> None:
    path = repo / "migrations" / "versions" / name
    path.write_text('"""new"""\nrevision = "0002_new"\n', encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", f"add {name}")


def test_pr_new_migration_allowed(tmp_path, capsys):
    module = _load_script()
    repo, base = _init_repo(tmp_path)
    _git(repo, "checkout", "-b", "feature")
    _add_migration(repo)
    rc, out = _run(module, repo, capsys, "pull_request", "merge-base", base)
    assert rc == 0
    assert "event=pull_request" in out
    assert "仅新增 1 个文件" in out


@pytest.mark.parametrize(
    ("action", "expected_status"),
    [
        ("modify", "M"),
        ("delete", "D"),
        ("rename", "R"),
    ],
)
def test_pr_historical_migration_change_fails(tmp_path, capsys, action, expected_status):
    module = _load_script()
    repo, base = _init_repo(tmp_path)
    _git(repo, "checkout", "-b", "feature")
    path = repo / "migrations" / "versions" / "0001_base.py"
    if action == "modify":
        path.write_text('"""changed"""\nrevision = "0001_base"\n', encoding="utf-8")
        _git(repo, "add", ".")
    elif action == "delete":
        _git(repo, "rm", "migrations/versions/0001_base.py")
    else:
        _git(repo, "mv", "migrations/versions/0001_base.py", "migrations/versions/0001_renamed.py")
    _git(repo, "commit", "-m", f"{action} migration")
    rc, out = _run(module, repo, capsys, "pull_request", "merge-base", base)
    assert rc == 1
    assert f"  - {expected_status}" in out
    assert "0001_base.py" in out


def test_push_new_migration_allowed(tmp_path, capsys):
    module = _load_script()
    repo, base = _init_repo(tmp_path)
    _add_migration(repo)
    rc, out = _run(module, repo, capsys, "push", "direct", base)
    assert rc == 0
    assert "event=push" in out
    assert "仅新增 1 个文件" in out


@pytest.mark.parametrize(
    ("action", "expected_status"),
    [
        ("modify", "M"),
        ("delete", "D"),
        ("rename", "R"),
    ],
)
def test_push_historical_migration_change_fails(tmp_path, capsys, action, expected_status):
    module = _load_script()
    repo, base = _init_repo(tmp_path)
    path = repo / "migrations" / "versions" / "0001_base.py"
    if action == "modify":
        path.write_text('"""changed"""\nrevision = "0001_base"\n', encoding="utf-8")
        _git(repo, "add", ".")
    elif action == "delete":
        _git(repo, "rm", "migrations/versions/0001_base.py")
    else:
        _git(repo, "mv", "migrations/versions/0001_base.py", "migrations/versions/0001_renamed.py")
    _git(repo, "commit", "-m", f"{action} migration")
    rc, out = _run(module, repo, capsys, "push", "direct", base)
    assert rc == 1
    assert "event=push" in out
    assert f"  - {expected_status}" in out
    assert "0001_base.py" in out


def test_push_multi_commit_checks_full_before_after_range(tmp_path, capsys):
    module = _load_script()
    repo, base = _init_repo(tmp_path)
    _add_migration(repo)
    path = repo / "migrations" / "versions" / "0001_base.py"
    path.write_text('"""changed"""\nrevision = "0001_base"\n', encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "modify migration after add")
    rc, out = _run(module, repo, capsys, "push", "direct", base)
    assert rc == 1
    assert "  - M" in out
    assert "0001_base.py" in out


def test_push_non_fast_forward_compares_trees_without_merge_base(tmp_path, capsys):
    module = _load_script()
    repo, base = _init_repo(tmp_path)
    _git(repo, "checkout", "-b", "before")
    path = repo / "migrations" / "versions" / "0001_base.py"
    path.write_text('"""before"""\nrevision = "0001_base"\n', encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "before branch")
    before = _git(repo, "rev-parse", "HEAD")

    _git(repo, "checkout", "-b", "after", base)
    _add_migration(repo)
    after = _git(repo, "rev-parse", "HEAD")

    rc, out = _run(module, repo, capsys, "push", "direct", before, after)
    assert rc == 1
    assert "  - M" in out
    assert "0001_base.py" in out


def test_push_before_equals_after_allows_empty_diff(tmp_path, capsys):
    module = _load_script()
    repo, base = _init_repo(tmp_path)
    rc, out = _run(module, repo, capsys, "push", "direct", base, base)
    assert rc == 0
    assert "仅新增 0 个文件" in out


@pytest.mark.parametrize(
    ("event", "comparison"),
    [
        ("pull_request", "direct"),
        ("push", "merge-base"),
    ],
)
def test_event_and_comparison_must_match(tmp_path, capsys, event, comparison):
    module = _load_script()
    repo, base = _init_repo(tmp_path)
    rc, out = _run(module, repo, capsys, event, comparison, base)
    assert rc == 1
    assert "必须使用" in out


def test_zero_base_sha_fails_closed(tmp_path, capsys):
    module = _load_script()
    repo, _base = _init_repo(tmp_path)
    rc, out = _run(module, repo, capsys, "push", "direct", "0" * 40)
    assert rc == 1
    assert "全零 SHA" in out


def test_missing_base_sha_fails_closed(tmp_path, capsys):
    module = _load_script()
    repo, _base = _init_repo(tmp_path)
    rc, out = _run(module, repo, capsys, "push", "direct", "f" * 40)
    assert rc == 1
    assert "无法解析" in out


def test_head_must_match_checkout(tmp_path, capsys):
    module = _load_script()
    repo, base = _init_repo(tmp_path)
    _git(repo, "checkout", "-b", "feature")
    _add_migration(repo)
    rc, out = _run(module, repo, capsys, "push", "direct", base, base)
    assert rc == 1
    assert "checkout HEAD" in out
