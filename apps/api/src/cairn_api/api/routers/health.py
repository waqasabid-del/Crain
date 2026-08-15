"""Liveness and readiness.

Two endpoints, because Kubernetes and Cloud Run ask two different questions and
answering them the same way causes an outage.

*Liveness* asks whether the process is wedged and should be killed. It must not
touch the database: if the database is briefly unavailable, a liveness probe
that checks it reports every instance as dead, the platform restarts them all,
and a recoverable database blip becomes a total outage with a thundering herd of
reconnects on the far side.

*Readiness* asks whether this instance can serve traffic right now, and so does
check the database — an instance that cannot reach it should be taken out of
rotation, not restarted.

Neither is under the version prefix. Health checks are infrastructure, not
product surface, and their URLs are configured in a deployment manifest that
should not have to change when the API version does.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Response, status
from sqlalchemy import text

from cairn_api.api.dependencies import SettingsDep
from cairn_api.api.schemas import HealthResponse
from cairn_api.db.session import get_engine

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["health"])


@router.get(
    "/healthz",
    response_model=HealthResponse,
    summary="Liveness probe",
)
async def liveness(settings: SettingsDep) -> HealthResponse:
    """Report that the process is running. Never touches the database."""
    return HealthResponse(status="ok", environment=settings.environment)


@router.get(
    "/readyz",
    response_model=HealthResponse,
    summary="Readiness probe",
    responses={503: {"description": "A dependency is unavailable."}},
)
async def readiness(settings: SettingsDep, response: Response) -> HealthResponse:
    """Report whether this instance can serve traffic.

    Returns 503 rather than raising, so the body is a plain health document in
    both cases — a probe parsing two different shapes is a probe that eventually
    misreads one.
    """
    try:
        engine = get_engine()
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except Exception as exc:
        # Logged, not returned. A readiness endpoint is typically unauthenticated
        # and reachable from anywhere the load balancer is, so a connection error
        # in the body would publish the database host and driver.
        await logger.awarning("readiness_check_failed", error=str(exc))
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthResponse(status="unavailable", environment=settings.environment)

    return HealthResponse(status="ok", environment=settings.environment)
