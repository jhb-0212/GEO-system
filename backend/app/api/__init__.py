"""路由聚合：所有业务接口按能力码门禁，见各模块的 require_permission。"""

from fastapi import APIRouter

from app.api import (
    audit,
    auth,
    channels,
    citations,
    content,
    engines,
    evidence,
    health,
    keywords,
    leads,
    members,
    monitoring,
    pages,
    plans,
    projects,
    publishing,
    questions,
    quotes,
    stats,
    system_audit,
    tasks,
)

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(audit.router)
api_router.include_router(citations.router)
api_router.include_router(health.router)
api_router.include_router(projects.router)
api_router.include_router(engines.router)
api_router.include_router(members.router)
api_router.include_router(evidence.router)
api_router.include_router(monitoring.router)
api_router.include_router(stats.router)
api_router.include_router(leads.router)
api_router.include_router(content.router)
api_router.include_router(publishing.router)
api_router.include_router(channels.router)
api_router.include_router(questions.router)
api_router.include_router(keywords.router)
api_router.include_router(plans.router)
api_router.include_router(quotes.router)
api_router.include_router(pages.router)
api_router.include_router(system_audit.router)
api_router.include_router(tasks.router)
