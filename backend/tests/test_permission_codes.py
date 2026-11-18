"""权限码目录一致性：API 只能引用能力矩阵中登记过的能力码。

裸字符串本身不会编译失败；拼错一个码，接口会对所有人 403，虽比前端菜单静默消失
容易发现，但仍应在测试阶段拦下。这里静态扫描 `app/api/**/*.py` 的
`require_permission("...")` 调用，与 `PERMISSION_CATALOG` 比对。
"""

import re
from pathlib import Path

from app.core.permissions import PERMISSION_CATALOG

_API_DIR = Path(__file__).resolve().parents[1] / "app" / "api"
_REQUIRE_PERMISSION_RE = re.compile(r'require_permission\("([^"]+)"\)')


def test_every_require_permission_code_is_in_catalog() -> None:
    catalog = {code for code, *_ in PERMISSION_CATALOG}
    found: dict[str, set[str]] = {}

    for path in sorted(_API_DIR.glob("*.py")):
        for code in _REQUIRE_PERMISSION_RE.findall(path.read_text(encoding="utf-8")):
            found.setdefault(code, set()).add(path.name)

    assert found, "未扫描到任何 require_permission 调用，正则或目录可能已失效"
    unknown = {code: sorted(files) for code, files in found.items() if code not in catalog}
    assert not unknown, f"API 使用了能力目录之外的权限码：{unknown}"
