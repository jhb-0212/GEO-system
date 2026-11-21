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


class InsufficientPermissionError(AppError):
    """缺少具体能力码：返回 403 并写审计，不暴露角色细节。"""

    status_code = 403
    code = "insufficient_permission"


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


class ReviewStateError(AppError):
    status_code = 409
    code = "review_state_conflict"


class BusinessValidationError(AppError):
    """业务字段之间不满足约束：422，具体 code 由调用方给。"""

    status_code = 422
    code = "business_validation_error"


class ConflictError(AppError):
    """唯一约束或状态机冲突：409，具体 code 由调用方给。"""

    status_code = 409
    code = "conflict"


class TooManyRequestsError(AppError):
    """触发限流：429，主要用于登录失败与高频接口。"""

    status_code = 429
    code = "too_many_requests"


class ServiceUnavailableError(AppError):
    """依赖配置缺失或外部授权服务不可用：503，不暴露内部配置。"""

    status_code = 503
    code = "service_unavailable"
