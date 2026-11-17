"""凭证引用解析：`credential_ref` 只允许指向受控的密钥类环境变量。

历史上 `credential_ref` 直接 `os.getenv(...)`，管理员可以把任意进程环境变量名填进去
（例如 `DATABASE_URL`、`SECRET_KEY`），再用“测试连接/采集”把值发到外部地址，形成
越权读取。这里用白名单后缀收敛可读范围，写入时由 schema 拒绝，读取时再兜底一次。
"""

import os
import re

# 允许的密钥类变量后缀：DEEPSEEK_API_KEY、YUANBAO_SECRET_ID、DEEPSEEK_WEBSEARCH_TOKEN …
CREDENTIAL_REF_PATTERN = re.compile(
    r"^[A-Z][A-Z0-9_]*(_API_KEY|_SECRET_KEY|_SECRET_ID|_ACCESS_KEY|_TOKEN)$"
)


def is_allowed_credential_ref(ref: str | None) -> bool:
    return bool(ref) and bool(CREDENTIAL_REF_PATTERN.match(ref.strip()))


def read_credential_env(ref: str | None) -> str:
    """按引用读环境变量；引用不在白名单时返回空串，绝不读其他变量。"""
    if not ref:
        return ""
    clean = ref.strip()
    if not is_allowed_credential_ref(clean):
        return ""
    return os.getenv(clean, "").strip()
