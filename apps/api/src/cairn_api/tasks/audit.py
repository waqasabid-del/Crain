"""Operational events for the task layer, recording nobody.

The durable audit is the ``task_events`` table — categorical rows the API
renders back to every member. This module is the *operational* half, the
projects/audit.py idiom: the events an operator watches to see the feature
working. Categories only.

**What may never appear here**: a task title or description (teams title
tasks after their most sensitive work), a person id or display name, a due
date. The signature is the guarantee — there is no parameter to put one in.
The two bounded enum words a state change carries are workflow column names,
which every workspace shares.
"""

from __future__ import annotations

import enum

import structlog

logger = structlog.get_logger(__name__)


class TaskOpEvent(enum.StrEnum):
    """The transitions worth watching. Closed, because a free-form event name
    is how an identifier eventually gets appended to one."""

    CREATED = "task.created"
    EDITED = "task.edited"
    STATE_CHANGED = "task.state_changed"
    ARCHIVED = "task.archived"
    RESTORED = "task.restored"


async def record(
    event: TaskOpEvent,
    *,
    from_state: str | None = None,
    to_state: str | None = None,
) -> None:
    """Emit one safe operational event.

    The two states are bounded enum words — workflow column names, never who
    moved the task. There is no field for a task, a person, or a title, so a
    caller in a hurry has nowhere to put one.
    """
    fields: dict[str, object] = {}
    if from_state is not None:
        fields["from_state"] = from_state
    if to_state is not None:
        fields["to_state"] = to_state

    await logger.ainfo(event.value, **fields)
