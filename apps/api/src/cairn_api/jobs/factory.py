"""Broker selection. The wrong default fails loudly: an in-memory broker in
production loses every job on the next deploy with no error anywhere."""

from __future__ import annotations

from functools import lru_cache

import structlog

from cairn_api.config import Settings, get_settings
from cairn_api.jobs.memory import InMemoryJobQueue
from cairn_api.jobs.queue import JobQueue

logger = structlog.get_logger(__name__)


class QueueConfigurationError(RuntimeError):
    """The configured broker cannot be used in this environment."""


def build_queue(settings: Settings | None = None) -> JobQueue:
    """Construct the broker for this process."""
    settings = settings or get_settings()

    if settings.queue_backend == "memory":
        if settings.is_deployed:
            msg = (
                "queue_backend is 'memory' but CAIRN_ENVIRONMENT is "
                f"'{settings.environment}'. The in-memory broker holds jobs in "
                "RAM and loses every one of them on restart, silently. Set "
                "CAIRN_QUEUE_BACKEND=pubsub."
            )
            raise QueueConfigurationError(msg)

        logger.info("queue.using_in_memory_broker", environment=settings.environment)
        return InMemoryJobQueue()

    if not settings.gcp_project_id:
        msg = (
            "queue_backend is 'pubsub' but CAIRN_GCP_PROJECT_ID is not set. "
            "The Pub/Sub client would otherwise infer a project from ambient "
            "credentials, which is how a staging worker ends up consuming "
            "production's queue."
        )
        raise QueueConfigurationError(msg)

    # Imported here so google-cloud-pubsub is only loaded when used.
    from cairn_api.jobs.pubsub import PubSubJobQueue

    logger.info(
        "queue.using_pubsub",
        project=settings.gcp_project_id,
        topic=settings.queue_topic,
        subscription=settings.queue_subscription,
    )
    return PubSubJobQueue(
        project_id=settings.gcp_project_id,
        topic=settings.queue_topic,
        subscription=settings.queue_subscription,
        dead_letter_topic=settings.queue_dead_letter_topic,
    )


@lru_cache
def get_queue() -> JobQueue:
    """Cached: a Pub/Sub client owns gRPC channels/threads a per-request instance would leak."""
    return build_queue()
