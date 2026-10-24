"""v1 路由汇总。"""

from fastapi import APIRouter

from app.api.v1 import health, sessions, tasks, users

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(users.router)
api_router.include_router(sessions.router)
api_router.include_router(tasks.router)

__all__ = ["api_router"]
