"""What happened to a project, recorded without recording anybody.

**The durable audit is the rows themselves.** A membership row carries who
added it, when, who removed it and when; a project carries who declared its
state and when a claim was made. All of it is returned by the API to every
member — that is the "audit record the workspace can see", answerable from the
data rather than from a log somebody has to trust. This module is the
*operational* half: the events an operator watches to see the feature working,
following `meetings/audit.py` — categories and counts only.

**What may never appear here**: a project name (workspaces name projects after
their most sensitive work), a purpose text, a person id or display name, a
claimed source string (a private repo's name is a disclosure). The signature
is the guarantee — there is no parameter to put one in.
"""

from __future__ import annotations

import enum

import structlog

logger = structlog.get_logger(__name__)


class ProjectEvent(enum.StrEnum):
    """The transitions worth watching. Closed, because a free-form event name
    is how an identifier eventually gets appended to one."""

    CREATED = "project.created"
    STATE_DECLARED = "project.state_declared"
    PURPOSE_CHANGED = "project.purpose_changed"
    ARCHIVED = "project.archived"
    RESTORED = "project.restored"
    SOURCE_CLAIMED = "project.source_claimed"
    SOURCE_RELEASED = "project.source_released"
    MEMBER_ADDED = "project.member_added"
    MEMBER_REMOVED = "project.member_removed"


async def record(
    event: ProjectEvent,
    *,
    state: str | None = None,
    sources: int | None = None,
) -> None:
    """Emit one safe operational event.

    `state` is a bounded enum word, never who declared it. `sources` is a
    count of claimed strings, never the strings. There is no field for a
    project, a person, or a string, so a caller in a hurry has nowhere to put
    one.
    """
    fields: dict[str, object] = {}
    if state is not None:
        fields["state"] = state
    if sources is not None:
        fields["sources"] = sources

    await logger.ainfo(event.value, **fields)
