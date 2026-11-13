r"""开发环境令牌签发（仅本地开发使用，生产禁用）。

本脚本仅用于本地调试 Bearer 令牌，正式登录验收必须调用 `auth/login`：

    cd backend
    .\.venv\Scripts\python.exe scripts\dev_token.py --username geo_admin

令牌带 `sub`、`tv`（用户令牌版本）与过期时间，权限仍由数据库每次判定。
`APP_ENV` 不是 dev/local/test 时直接拒绝，避免误用于生产。
"""

import argparse
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import select  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.security import create_access_token  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.models import User  # noqa: E402

DEV_ENVS = {"dev", "local", "test"}


def main() -> None:
    if settings.app_env.strip().lower() not in DEV_ENVS:
        raise SystemExit(f"APP_ENV={settings.app_env!r}，禁止在非开发环境签发调试令牌")

    parser = argparse.ArgumentParser(description="签发开发用访问令牌")
    parser.add_argument("--username", required=True, help="用户名，例如 geo_admin")
    parser.add_argument("--minutes", type=int, default=None, help="有效期，默认取配置")
    args = parser.parse_args()

    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == args.username))

    if user is None:
        raise SystemExit(f"用户不存在：{args.username}")
    if not user.is_active:
        raise SystemExit(f"用户已停用：{args.username}")

    print(create_access_token(user.id, token_version=user.token_version, expires_minutes=args.minutes))


if __name__ == "__main__":
    main()
