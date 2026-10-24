"""应用入口：创建 FastAPI 实例，装配中间件、异常处理与路由。"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from app.api.v1 import api_router
from app.clients.redis import close_redis
from app.core.config import Settings, get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware
from app.db.session import dispose_engine


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings)
    logger = structlog.get_logger(__name__)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        logger.info(
            "app_starting",
            environment=settings.environment,
            version=settings.app_version,
        )
        try:
            yield
        finally:
            await dispose_engine()
            await close_redis()
            logger.info("app_stopped")

    app = FastAPI(
        title="AI 服务后端",
        version=settings.app_version,
        description="会话与消息服务：FastAPI + PostgreSQL + Redis + RabbitMQ(Celery)",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    app.add_middleware(RequestContextMiddleware)
    register_exception_handlers(app)
    app.include_router(api_router)

    return app


app = create_app()
