"""同步导出守卫：导出前的唯一上限判据。

规则只有一条：同步导出的行数不得超过 `export_sync_row_limit`。
这里是该规则的唯一事实源——各接口只负责「先算出真实行数」，然后调用本函数，
不要各自再写一遍阈值比较与错误文案。

`services/audit.py::record_export` 里对 row_count 的校验保留不动：那是审计侧确认
「写进审计的行数本身合法」，与本函数「取数之前先卡住」职责不同。
"""

from __future__ import annotations

from app.core.config import settings
from app.core.errors import ExportTooLargeError


def ensure_sync_export_allowed(row_count: int, *, what: str) -> None:
    """行数超过同步上限时抛 400，要求缩小范围或改用异步导出。

    参数 `what` 只用于文案（例如「线索导出」「筛选导出需扫描的引用」），
    以便调用方在报错里说清是哪种导出、量级从哪来。
    """
    if row_count > settings.export_sync_row_limit:
        raise ExportTooLargeError(
            f"{what}共 {row_count} 条，超过同步上限 {settings.export_sync_row_limit}，"
            "请缩小范围或改用异步导出"
        )
