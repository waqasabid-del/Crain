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
                "CAIRN_QUEUE_BACKEND=postgres."
            )
            raise QueueConfigurationError(msg)

        logger.info("queue.using_in_memory_broker", environment=settings.environment)
        return InMemoryJobQueue()

    if settings.queue_backend == "postgres":
        # No lazy import: PostgreSQL is already a hard dependency of every
        # process that would construct a queue at all.
        from cairn_api.jobs.postgres import PostgresJobQueue

        logger.info("queue.using_postgres_scheduler", environment=settings.environment)
        return PostgresJobQueue()

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

    if settings.is_deployed and not settings.queue_fairness_optional:
        # Durable, but not fair, and not observable. Pub/Sub delivers in arrival
        # order with no notion of one customer's backfill crowding out another's
        # live push, and it reports no retry or dead-letter metrics — so the
        # DLQ alert in docs/OPERATIONS.md has nothing to fire on.
        #
        # A warning was not enough. An operator following an older runbook would
        # deploy it, the log line would scroll past, and the first person to
        # notice would be the customer whose live events were stuck behind
        # somebody else's import. Refusing is recoverable in a way that is not.
        msg = (
            "queue_backend is 'pubsub' but CAIRN_ENVIRONMENT is "
            f"'{settings.environment}'. Pub/Sub cannot enforce per-tenant "
            "fairness — one workspace's backfill can occupy every worker and "
            "delay another workspace's live events — and it emits no retry or "
            "dead-letter metrics, so the DLQ alert has nothing to fire on. Set "
            "CAIRN_QUEUE_BACKEND=postgres, or set "
            "CAIRN_QUEUE_FAIRNESS_OPTIONAL=true to accept both losses."
        )
        raise QueueConfigurationError(msg)

    if settings.is_deployed:
        logger.warning(
            "queue.fairness_not_enforced",
            backend="pubsub",
            detail=(
                "Running deployed on Pub/Sub by explicit configuration. "
                "Per-tenant fairness, priority scheduling and queue outcome "
                "metrics are all unavailable on this backend."
            ),
        )

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
