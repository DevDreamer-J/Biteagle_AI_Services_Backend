"""健康检查：存活探针与就绪探针。"""

from fastapi import APIRouter, Response, status

from app.clients.redis import check_redis
from app.core.config import get_settings
from app.db.session import check_database
from app.schemas.health import Liveness, Readiness

router = APIRouter(tags=["health"])


@router.get("/health/live", response_model=Liveness, summary="存活探针")
async def liveness() -> Liveness:
    settings = get_settings()
    return Liveness(status="ok", app=settings.app_name, version=settings.app_version)


@router.get(
    "/health/ready",
    response_model=Readiness,
    summary="就绪探针",
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": Readiness}},
)
async def readiness(response: Response) -> Readiness:
    checks = {
        "database": await check_database(),
        "redis": await check_redis(),
    }
    ready = all(checks.values())
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return Readiness(
        status="ok" if ready else "degraded",
        checks={name: "ok" if passed else "unavailable" for name, passed in checks.items()},
    )
