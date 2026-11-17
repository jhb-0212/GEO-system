"""凭证引用解析：`credential_ref` 只允许指向受控的密钥类环境变量。

历史上 `credential_ref` 直接 `os.getenv(...)`，管理员可以把任意进程环境变量名填进去
（例如 `DATABASE_URL`、`SECRET_KEY`），再用“测试连接/采集”把值发到外部地址，形成
越权读取。这里用白名单后缀收敛可读范围，写入时由 schema 拒绝，读取时再兜底一次。
"""

import os
import re
from functools import lru_cache
from pathlib import Path

try:
    from dotenv import dotenv_values
except ImportError:  # 运行环境没装 python-dotenv 时降级为只读进程环境，不让启动直接崩
    dotenv_values = None  # type: ignore[assignment]

# 允许的密钥类变量后缀：DEEPSEEK_API_KEY、YUANBAO_SECRET_ID、DEEPSEEK_WEBSEARCH_TOKEN …
CREDENTIAL_REF_PATTERN = re.compile(
    r"^[A-Z][A-Z0-9_]*(_API_KEY|_SECRET_KEY|_SECRET_ID|_ACCESS_KEY|_TOKEN)$"
)

# 与 pydantic-settings 相同的候选文件顺序；靠后的文件覆盖靠前的。
_BACKEND_DIR = Path(__file__).resolve().parents[2]  # backend/
ENV_PATHS: tuple[Path, ...] = (_BACKEND_DIR.parent / ".env", _BACKEND_DIR / ".env")


def is_allowed_credential_ref(ref: str | None) -> bool:
    return bool(ref) and bool(CREDENTIAL_REF_PATTERN.match(ref.strip()))


@lru_cache(maxsize=8)
def _dotenv_credentials(env_paths: tuple[Path, ...] = ENV_PATHS) -> dict[str, str]:
    """把 `.env` 里**白名单内**的密钥读成一个字典。

    为什么需要这一层：`.env` 由 pydantic-settings 读进 `settings`，但它不会把值导出到
    `os.environ`。所以只要某个 key 只写在 `.env`（例如 `YUANBAO_SECRET_ID`），
    `os.getenv` 就是空的——表现为“明明配了却报未配置”。

    只挑白名单后缀的键，其余（数据库口令、SECRET_KEY 之类）一律不取，
    避免把 .env 变成任意环境变量的读取入口。
    """
    merged: dict[str, str] = {}
    if dotenv_values is None:
        return merged
    for path in env_paths:
        if not path.is_file():
            continue
        for key, value in dotenv_values(path).items():
            if value and is_allowed_credential_ref(key):
                merged[key.strip()] = value.strip()
    return merged


def read_credential_env(
    ref: str | None, *, env_paths: tuple[Path, ...] | None = None
) -> str:
    """按引用读密钥：先看进程环境，再回落到 `.env`（仅白名单键）。

    引用不在白名单时返回空串，绝不读其他变量。`env_paths` 仅供测试注入，
    生产调用不传、走模块级 `ENV_PATHS`。
    """
    if not ref:
        return ""
    clean = ref.strip()
    if not is_allowed_credential_ref(clean):
        return ""
    value = os.getenv(clean, "").strip()
    if value:
        return value
    return _dotenv_credentials(env_paths or ENV_PATHS).get(clean, "")
