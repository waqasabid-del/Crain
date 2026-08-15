"""The Pub/Sub adapter — production's broker, verified against the emulator
in `docker-compose.yml`. Three mismatches with `JobQueue`: no delayed
delivery (retry uses `modify_ack_deadline`, capped at 600s); dead-lettering
is explicit via `dead_letter` rather than the subscription's own policy
(kept as backstop for a dying worker); `depth()` has no real backlog-count
API, so it reports "unknown" rather than a lie. Ordering is not requested —
handlers must be order-independent (`envelope.py`).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import uuid
from typing import Any

import structlog

from cairn_api.jobs.envelope import JobEnvelope
from cairn_api.jobs.queue import Priority, QueueDepth, QueueMessage

logger = structlog.get_logger(__name__)

#: Pub/Sub's maximum ack deadline; no retry policy used here may exceed it.
MAX_ACK_DEADLINE_SECONDS = 600

#: Env var the Google client libraries read to reach the emulator.
EMULATOR_ENV = "PUBSUB_EMULATOR_HOST"


class PubSubJobQueue:
    """The client libraries are synchronous, so every call is dispatched
    with `asyncio.to_thread` to avoid stalling the event loop.
    """

    def __init__(
        self,
        *,
        project_id: str,
        topic: str,
        subscription: str,
        dead_letter_topic: str,
        pull_timeout_seconds: float = 5.0,
        publisher: Any | None = None,
        subscriber: Any | None = None,
    ) -> None:
        from google.cloud import pubsub_v1

        self._project = project_id
        self._publisher = publisher or pubsub_v1.PublisherClient()
        self._subscriber = subscriber or pubsub_v1.SubscriberClient()
        self._topic_path = self._publisher.topic_path(project_id, topic)
        self._dlq_path = self._publisher.topic_path(project_id, dead_letter_topic)
        self._subscription_path = self._subscriber.subscription_path(project_id, subscription)
        # Long poll: bounds idle-loop cost and shutdown latency together.
        self._pull_timeout = pull_timeout_seconds

    async def publish(
        self,
        envelope: JobEnvelope,
        *,
        priority: Priority = Priority.STANDARD,
        delay_seconds: float = 0.0,
    ) -> None:
        """``delay_seconds`` is accepted and ignored — Pub/Sub has no delayed publish."""
        if delay_seconds > 0:
            await logger.awarning(
                "pubsub.publish_delay_ignored",
                job_type=envelope.job_type,
                requested_delay=delay_seconds,
                detail="Pub/Sub has no delayed publish; use Cloud Tasks for scheduling.",
            )

        data = envelope.model_dump_json().encode("utf-8")
        attributes = {
            "job_type": envelope.job_type,
            "tenant_id": str(envelope.tenant_id),
            "priority": str(int(priority)),
            "attempt": str(envelope.attempt),
        }
        if envelope.traceparent:
            attributes["traceparent"] = envelope.traceparent

        await asyncio.to_thread(
            lambda: self._publisher.publish(self._topic_path, data, **attributes).result()
        )

    async def receive(self, *, max_messages: int = 1) -> list[QueueMessage]:
        def _pull() -> Any:
            return self._subscriber.pull(
                request={
                    "subscription": self._subscription_path,
                    "max_messages": max_messages,
                },
                timeout=self._pull_timeout,
            )

        response = await asyncio.to_thread(_pull)

        messages: list[QueueMessage] = []
        for received in response.received_messages:
            envelope = self._decode(received)
            if envelope is None:
                # No version of this code can parse it — ack and dead-letter now.
                await self._acknowledge(received.ack_id)
                await self._publish_raw_to_dlq(received.message.data)
                continue

            messages.append(
                QueueMessage(
                    envelope=envelope,
                    receipt=received.ack_id,
                    priority=_priority_from(received.message.attributes),
                    delivery_attempt=received.delivery_attempt or 1,
                )
            )

        return messages

    def _decode(self, received: Any) -> JobEnvelope | None:
        try:
            return JobEnvelope.model_validate_json(received.message.data)
        except (ValueError, json.JSONDecodeError):
            logger.exception(
                "pubsub.undecodable_message",
                message_id=received.message.message_id,
            )
            return None

    async def ack(self, message: QueueMessage) -> None:
        await self._acknowledge(message.receipt)

    async def _acknowledge(self, ack_id: str) -> None:
        def _call() -> None:
            self._subscriber.acknowledge(
                request={"subscription": self._subscription_path, "ack_ids": [ack_id]}
            )

        await asyncio.to_thread(_call)

    async def retry(self, message: QueueMessage, *, delay_seconds: float) -> None:
        """`modify_ack_deadline`, not a republish — a republish would reset
        Pub/Sub's delivery-attempt counter and defeat its dead-letter backstop.
        """
        deadline = min(int(delay_seconds), MAX_ACK_DEADLINE_SECONDS)
        await asyncio.to_thread(
            lambda: self._subscriber.modify_ack_deadline(
                request={
                    "subscription": self._subscription_path,
                    "ack_ids": [message.receipt],
                    "ack_deadline_seconds": deadline,
                }
            )
        )

    async def dead_letter(self, message: QueueMessage, *, reason: str) -> None:
        """Publish then acknowledge, in that order — the reverse loses the message on a crash between."""
        payload = message.envelope.model_dump_json().encode("utf-8")
        await asyncio.to_thread(
            lambda: self._publisher.publish(
                self._dlq_path,
                payload,
                job_type=message.envelope.job_type,
                tenant_id=str(message.envelope.tenant_id),
                attempts=str(message.envelope.attempt),
                reason=reason[:1024],
            ).result()
        )
        await self.ack(message)

        await logger.aerror(
            "job.dead_lettered",
            job_id=str(message.envelope.job_id),
            job_type=message.envelope.job_type,
            tenant_id=str(message.envelope.tenant_id),
            attempts=message.envelope.attempt,
            reason=reason,
        )

    async def _publish_raw_to_dlq(self, data: bytes) -> None:
        await asyncio.to_thread(
            lambda: self._publisher.publish(self._dlq_path, data, reason="undecodable").result()
        )

    async def depth(self) -> QueueDepth:
        """No backlog-count API exists, so this reports "unknown" rather than a false zero."""
        await logger.adebug(
            "pubsub.depth_unavailable",
            detail=(
                "Backlog size comes from Cloud Monitoring "
                "(subscription/num_undelivered_messages), not the Pub/Sub API."
            ),
        )
        return QueueDepth(pending=0, in_flight=0, dead_lettered=0, per_tenant={})


def _priority_from(attributes: Any) -> Priority:
    """Defaults rather than fails — an older revision's message has no
    priority attribute, and a rolling deploy runs both versions at once.
    """
    raw = attributes.get("priority") if attributes else None
    if raw is None:
        return Priority.STANDARD
    try:
        return Priority(int(raw))
    except (ValueError, TypeError):
        return Priority.STANDARD


async def ensure_topics_and_subscription(
    *,
    project_id: str,
    topic: str,
    subscription: str,
    dead_letter_topic: str,
    max_delivery_attempts: int = 10,
) -> None:
    """For local dev and tests against the emulator; in production these are Terraform's job."""
    from google.api_core.exceptions import AlreadyExists
    from google.cloud import pubsub_v1

    publisher = pubsub_v1.PublisherClient()
    subscriber = pubsub_v1.SubscriberClient()

    topic_path = publisher.topic_path(project_id, topic)
    dlq_path = publisher.topic_path(project_id, dead_letter_topic)
    subscription_path = subscriber.subscription_path(project_id, subscription)

    for path in (topic_path, dlq_path):
        with contextlib.suppress(AlreadyExists):
            await asyncio.to_thread(publisher.create_topic, request={"name": path})

    request: dict[str, Any] = {
        "name": subscription_path,
        "topic": topic_path,
        "ack_deadline_seconds": 60,
        "dead_letter_policy": {
            "dead_letter_topic": dlq_path,
            "max_delivery_attempts": max_delivery_attempts,
        },
    }
    try:
        await asyncio.to_thread(subscriber.create_subscription, request=request)
    except AlreadyExists:
        pass
    except Exception as exc:
        # Emulator doesn't implement dead-letter policies; fall back for local dev.
        await logger.awarning(
            "pubsub.dead_letter_policy_unsupported",
            error=str(exc),
            detail="Retrying without a dead-letter policy — expected on the emulator.",
        )
        request.pop("dead_letter_policy")
        with contextlib.suppress(AlreadyExists):
            await asyncio.to_thread(subscriber.create_subscription, request=request)


def make_test_ids() -> tuple[str, str, str]:
    """The emulator persists state for its lifetime, so shared names would leak between tests."""
    suffix = uuid.uuid4().hex[:12]
    return f"jobs-{suffix}", f"jobs-sub-{suffix}", f"jobs-dlq-{suffix}"
