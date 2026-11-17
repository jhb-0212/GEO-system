"""Beat 容器健康检查：确认 celery beat 进程仍在运行。

celery beat 不会像 worker 那样写 Redis 心跳，容器 `Up` 也不代表调度进程活者：
它可能已异常退出而容器只剩余 PID 1。这里直接扫 /proc 判断命令行里是否还有
`celery ... beat` 进程，替代对 schedule 文件 mtime 的猜测。
"""

from __future__ import annotations

import os
import sys


def _is_beat(cmdline: bytes) -> bool:
    text = cmdline.replace(b"\x00", b" ").decode("utf-8", "ignore")
    return "celery" in text and "beat" in text


def main() -> int:
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            with open(f"/proc/{entry}/cmdline", "rb") as handle:
                if _is_beat(handle.read()):
                    return 0
        except OSError:
            continue
    print("celery beat process not found", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
