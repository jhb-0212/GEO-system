"""统一错误信封：所有业务错误都返回 {"error": {"code", "message"}}，不混用 FastAPI 的 detail 包装。"""


class AppError(Exception):
    status_code = 400
    code = "app_error"

    def __init__(self, message: str = "", *, code: str | None = None) -> None:
        super().__init__(message or self.code)
        if code:
            self.code = code


class ProjectAccessError(AppError):
    """项目不存在、未授权、或资源不属于该项目。对外统一 403，避免探测。"""

    status_code = 403
    code = "project_forbidden"


class InsufficientRoleError(AppError):
    status_code = 403
    code = "insufficient_role"


class SystemAdminOnlyError(AppError):
    status_code = 403
    code = "system_admin_only"


class UnauthorizedError(AppError):
    status_code = 401
    code = "unauthorized"


class PathEscapeError(AppError):
    status_code = 403
    code = "path_escape"


class ResourceMissingError(AppError):
    status_code = 404
    code = "resource_missing"


class ExportTooLargeError(AppError):
    """同步导出超过行数上限，必须改为异步任务。"""

    status_code = 400
    code = "export_too_large"


class TaskRejectedError(AppError):
    """后台任务参数不合法（缺项目标识、项目停用等），任务拒绝执行并记录原因。"""

    status_code = 409
    code = "task_rejected"
