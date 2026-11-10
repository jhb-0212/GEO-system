"""路由聚合：后续各业务模块（项目、题库、监测、证据、内容、发布、分析）在此挂载。"""

from fastapi import APIRouter

from app.api import health

api_router = APIRouter()
api_router.include_router(health.router)
