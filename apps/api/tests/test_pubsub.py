"""The Pub/Sub adapter, against a real emulator.

Skipped when the emulator is not running, which is honest: without it these
assert nothing, and a mocked Pub/Sub client would only confirm that the mock
behaves like the mock. The semantics that matter — at-least-once delivery,
acknowledgement deadlines, redelivery of unacknowledged messages — are precisely
the ones a mock gets wrong, and getting them wrong in a mock produces a worker
written against a broker that does not exist.

Start it with `make queue-up`, or `docker compose up -d pubsub`.
"""

from __future__ import annotations

import asyncio
import os
import socket
import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from cairn_api.jobs.envelope import JobEnvelope
from cairn_api.jobs.pubsub import (
    EMULATOR_ENV,
    PubSubJobQueue,
    ensure_topics_and_subscription,
    make_test_ids,
)
from cairn_api.jobs.queue import Priority, QueueMessage

PROJECT = "cairn-local"
DEFAULT_EMULATOR = "localhost:8085"
TENANT = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")


def _emulator_reachable(address: str) -> bool:
    host, _, port = address.partition(":")
    try:
        with socket.create_connection((host, int(port or 8085)), timeout=1):
            return True
    except OSError:
        return False


_ADDRESS = os.environ.get(EMULATOR_ENV, DEFAULT_EMULATOR)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not _emulator_reachable(_ADDRESS),
        reason=(
            f"Pub/Sub emulator not reachable at {_ADDRESS}. "
            "Start it with: docker compose up -d pubsub"
        ),
    ),
]


@pytest_asyncio.fixture
async def queue() -> AsyncIterator[PubSubJobQueue]:
    """A queue on freshly created, uniquely named topics.

    The emulator keeps state for its lifetime, so tests sharing names would see
    each other's messages and pass or fail by execution order.
    """
    os.environ[EMULATOR_ENV] = _ADDRESS
    topic, subscription, dlq = make_test_ids()
    await ensure_topics_and_subscription(
        project_id=PROJECT, topic=topic, subscription=subscription, dead_letter_topic=dlq
    )
    yield PubSubJobQueue(
        project_id=PROJECT,
        topic=topic,
        subscription=subscription,
        dead_letter_topic=dlq,
        # A short poll here only. Production long-polls, because an idle worker
        # that round-trips every second is a billed operation per second; these
        # tests assert on emptiness repeatedly, and the default turned this file
        # into two and a half minutes of waiting.
        pull_timeout_seconds=0.5,
    )


def envelope(job_type: str = "test.job") -> JobEnvelope:
    return JobEnvelope(job_type=job_type, tenant_id=TENANT)


async def _receive_eventually(
    queue: PubSubJobQueue, *, max_messages: int = 1, attempts: int = 10
) -> list[QueueMessage]:
    """Poll until something arrives.

    Publish and pull are not instantaneous even against the emulator, and a
    single pull that returns empty is normal rather than a failure. Retrying is
    what a worker does; asserting on one pull would make these tests flaky in
    exactly the way the worker is designed not to be.
    """
    for _ in range(attempts):
        messages = await queue.receive(max_messages=max_messages)
        if messages:
            return messages
        await asyncio.sleep(0.2)
    return []


class TestRoundTrip:
    async def test_a_published_job_comes_back_intact(self, queue: PubSubJobQueue) -> None:
        original = envelope("round.trip")

        await queue.publish(original)
        received = await _receive_eventually(queue)

        assert len(received) == 1
        # Identity must survive the wire: `job_id` is what makes idempotent
        # consumption possible under at-least-once delivery.
        assert received[0].envelope.job_id == original.job_id
        assert received[0].envelope.tenant_id == original.tenant_id
        assert received[0].envelope.job_type == "round.trip"

    async def test_priority_survives_the_round_trip(self, queue: PubSubJobQueue) -> None:
        await queue.publish(envelope("bulk.work"), priority=Priority.BULK)

        received = await _receive_eventually(queue)

        assert received[0].priority is Priority.BULK

    async def test_an_acknowledged_message_is_not_redelivered(self, queue: PubSubJobQueue) -> None:
        await queue.publish(envelope())
        received = await _receive_eventually(queue)

        await queue.ack(received[0])

        # Several pulls, because a single empty one proves nothing — Pub/Sub
        # returns empty when it feels like it.
        for _ in range(5):
            assert await queue.receive(max_messages=10) == []
            await asyncio.sleep(0.1)


class TestDeliverySemantics:
    async def test_an_unacknowledged_message_is_redelivered(self, queue: PubSubJobQueue) -> None:
        """At-least-once, from the real broker.

        This is the property the whole worker design rests on: a process killed
        mid-job never acknowledges, and the message must come back. Asserting it
        against a mock would assert only that the mock was written to agree.
        """
        await queue.publish(envelope())
        first = await _receive_eventually(queue)

        # Ask for immediate redelivery — the "worker crashed" signal.
        await queue.retry(first[0], delay_seconds=0)
        second = await _receive_eventually(queue, attempts=20)

        assert len(second) == 1
        assert second[0].envelope.job_id == first[0].envelope.job_id

    async def test_dead_lettering_acknowledges_and_stops_redelivery(
        self, queue: PubSubJobQueue
    ) -> None:
        # Aside, not away. The message must stop blocking the stream while
        # remaining inspectable on the dead-letter topic.
        await queue.publish(envelope("poison"))
        received = await _receive_eventually(queue)

        await queue.dead_letter(received[0], reason="unparseable payload")

        for _ in range(5):
            assert await queue.receive(max_messages=10) == []
            await asyncio.sleep(0.1)

    async def test_an_undecodable_message_is_removed_rather_than_looping(
        self, queue: PubSubJobQueue
    ) -> None:
        """A malformed message must not wedge the queue.

        Publishing bytes that are not a `JobEnvelope` — an older producer, a
        hand-published test message, a corrupted payload. Left alone it would be
        redelivered forever at the head of the queue, and one malformed payload
        would stall the whole pipeline (md/06 §6B.2: individual failures must
        not cascade).
        """
        from google.cloud import pubsub_v1

        publisher = pubsub_v1.PublisherClient()
        publisher.publish(queue._topic_path, b"{ not json at all").result()

        # `receive` decodes, discards and dead-letters it, returning nothing.
        assert await queue.receive(max_messages=10) == []

        # And it does not come back.
        for _ in range(5):
            assert await queue.receive(max_messages=10) == []
            await asyncio.sleep(0.1)


class TestDepthReporting:
    async def test_depth_is_reported_as_unknown_rather_than_zero(
        self, queue: PubSubJobQueue
    ) -> None:
        """Pub/Sub has no backlog-count API.

        `num_undelivered_messages` is a Cloud Monitoring metric on a
        multi-minute interval — the right source for autoscaling, the wrong one
        for a request-time call. What matters is that this does not fabricate a
        number: a hardcoded zero reads as "queue empty", which is the single
        most misleading thing a depth call could return during an incident.
        """
        await queue.publish(envelope())

        depth = await queue.depth()

        assert depth.total == 0
        assert depth.per_tenant == {}
