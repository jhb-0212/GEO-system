"""C1：前端不得保留第二套业务日历。静态扫描比页面点击更能守住这条边界。"""
from pathlib import Path

FRONTEND = Path(__file__).resolve().parents[2] / "frontend"
WORKBENCH_FILES = [
    FRONTEND / "components" / "workbench-app.tsx",
    FRONTEND / "lib" / "workbench" / "client.ts",
    FRONTEND / "lib" / "workbench" / "mock.ts",
    FRONTEND / "lib" / "workbench" / "types.ts",
]

FORBIDDEN = [
    "86_400_000",
    "86_400_000 ",
    "getTimezoneOffset",
    "localDayStart",
    "localWeekStart",
    "todoInRange",
    "timezone_offset_minutes",
    "at: task.updatedAt",
    "at: item.submittedAt",
]


def test_no_frontend_business_calendar_implementation():
    violations: list[str] = []
    for path in WORKBENCH_FILES:
        text = path.read_text(encoding="utf-8")
        for token in FORBIDDEN:
            if token in text:
                violations.append(f"{path.name}: {token}")
    assert violations == [], f"前端仍存在本地日历/旧字段：{violations}"


def test_mock_todo_uses_server_entered_time_and_business_timezone():
    text = (FRONTEND / "components" / "workbench-app.tsx").read_text(encoding="utf-8")
    assert "enteredTodoAt" in text
    assert "business_timezone" in text
    # mock 窗口必须是固定样本，不能由浏览器当下时间推导
    assert "MOCK_WINDOWS" in text
