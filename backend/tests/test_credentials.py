"""凭证读取：进程环境优先，`.env` 兜底，且两个来源都受白名单约束。

锁三个点：
1. `.env` 里的密钥能被读到——否则“明明写在 .env 里却报未配置”，这是最容易复发的坑
   （pydantic-settings 只把 .env 读进 settings，不导出到 os.environ）；
2. 非白名单的键永远读不到——`.env` 里有 DATABASE_URL / SECRET_KEY，不能变成任意读取入口；
3. 进程环境优先于 `.env`——部署时临时注入的值不能被文件覆盖。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import credentials
from app.core.credentials import is_allowed_credential_ref, read_credential_env


def _write_env(path: Path, lines: list[str]) -> Path:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_reads_key_from_env_file(tmp_path, monkeypatch) -> None: 
    env_file = _write_env(tmp_path / ".env", ["ARK_API_KEY=file-secret-1", "DATABASE_URL=postgres://x"])
    # 本机用户级环境变量里可能存在真实 ARK_API_KEY，进程环境优先会盖掉文件值，先隔离
    monkeypatch.delenv("ARK_API_KEY", raising=False)
    credentials._dotenv_credentials.cache_clear()
    try:
        assert read_credential_env("ARK_API_KEY", env_paths=(env_file,)) == "file-secret-1"
    finally:
        credentials._dotenv_credentials.cache_clear()


def test_non_whitelisted_names_never_readable(tmp_path) -> None:
    env_file = _write_env(tmp_path / ".env", ["DATABASE_URL=postgres://leaked", "SECRET_KEY=leaked"])
    credentials._dotenv_credentials.cache_clear()
    try:
        assert read_credential_env("DATABASE_URL", env_paths=(env_file,)) == ""
        assert read_credential_env("SECRET_KEY", env_paths=(env_file,)) == ""
    finally:
        credentials._dotenv_credentials.cache_clear()


def test_process_env_wins_over_env_file(tmp_path, monkeypatch) -> None:
    env_file = _write_env(tmp_path / ".env", ["QIANFAN_API_KEY=from-file"])
    monkeypatch.setenv("QIANFAN_API_KEY", "from-process")
    credentials._dotenv_credentials.cache_clear()
    try:
        assert read_credential_env("QIANFAN_API_KEY", env_paths=(env_file,)) == "from-process"
    finally:
        credentials._dotenv_credentials.cache_clear()


def test_later_env_file_overrides_earlier(tmp_path, monkeypatch) -> None:
    root_env = _write_env(tmp_path / "root.env", ["ARK_API_KEY=root-value"])
    backend_env = _write_env(tmp_path / "backend.env", ["ARK_API_KEY=backend-value"])
    monkeypatch.delenv("ARK_API_KEY", raising=False)
    credentials._dotenv_credentials.cache_clear()
    try:
        assert read_credential_env("ARK_API_KEY", env_paths=(root_env, backend_env)) == "backend-value"
    finally:
        credentials._dotenv_credentials.cache_clear()


def test_missing_file_is_not_fatal(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("ARK_API_KEY", raising=False)
    credentials._dotenv_credentials.cache_clear()
    try:
        assert read_credential_env("ARK_API_KEY", env_paths=(tmp_path / "nope.env",)) == ""
    finally:
        credentials._dotenv_credentials.cache_clear()


def test_whitelist_pattern() -> None:
    assert is_allowed_credential_ref("ARK_API_KEY")
    assert is_allowed_credential_ref("YUANBAO_SECRET_ID")
    assert not is_allowed_credential_ref("DATABASE_URL")
    assert not is_allowed_credential_ref("")
    assert not is_allowed_credential_ref(None)
