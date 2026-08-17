"""Which public channels CAIRN may read, and the one question ingestion asks.

**Selection is the permission.** A Slack workspace can be connected, healthy and
fully scoped, and CAIRN still processes nothing from it until somebody chooses
channels. There is no "all channels" option and no default selection, because a
default that includes the channel created tomorrow is a permission nobody gave —
and because the channel most likely to be created tomorrow is the one about a
reorganisation.

:func:`is_channel_permitted` is the whole contract for the ingestion side. It
answers "may this workspace process this channel" with a single boolean, and it
checks the *connection* as well as the selection: a disconnected workspace with a
full selection permits nothing. Ingestion must call it before an event is stored,
not after — the point of a permission check performed on the way out is that the
data was already read.

Nothing here persists a channel name. Names arrive from Slack for the picker and
are gone by the end of the request; see ``db/slack_models.SlackChannelSelection``.
"""

from __future__ import annotations

import re
import time
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import final

import structlog
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from cairn_api.connectors.credentials import SecretValue
from cairn_api.db.connector_models import ConnectionState, ConnectorProvider, SourceConnection
from cairn_api.db.slack_models import CHANNEL_ID_PATTERN, SlackChannelSelection
from cairn_api.slack.oauth import SlackApi, SlackChannel

logger = structlog.get_logger(__name__)

#: Compiled once. Mirrors the CHECK constraint on the column, so a bad id is
#: refused with a 422 naming the field rather than as an IntegrityError.
_CHANNEL_ID = re.compile(CHANNEL_ID_PATTERN)

#: What every surface showing the picker must say.
#:
#: Served from the API rather than written into the interface, for the reason
#: `ConsentResponse.refusals` is: a promise stated in one client is a promise the
#: next client forgets. This one is not a nicety — a customer who selects a
#: channel and is never told about `/invite` gets an integration that reports
#: success and delivers silence, and concludes CAIRN does not work.
BOT_INVITE_NOTICE = (
    "CAIRN only receives messages from channels the CAIRN app has been added to. "
    "For each channel you select, run /invite @CAIRN in Slack. CAIRN cannot add "
    "itself — it does not ask Slack for permission to join channels."
)

#: How long a fetched channel list is reused.
#:
#: `conversations.list` is rate-limited by Slack, and a picker is exactly the
#: screen a person reloads while deciding. Sixty seconds is short enough that a
#: channel created mid-session appears on the next look, and long enough that the
#: reload does not spend the workspace's budget.
CACHE_TTL_SECONDS = 60.0

#: Ceiling on how many channels one workspace may select in one request.
#:
#: Not a technical limit — it is a bound on a request body, so an accidental or
#: hostile caller cannot make one PUT insert an unbounded number of rows.
MAX_SELECTED_CHANNELS = 1000


class SlackSelectionError(ValueError):
    """A selection that cannot be saved, with a sentence safe to return.

    A ``ValueError`` subclass because it genuinely is bad input, and the message
    names the problem without echoing the offending value — a caller that sent a
    channel *name* would otherwise get that name reflected into a response body
    and, from there, into whatever logs the response.
    """


@final
@dataclass(frozen=True, slots=True)
class _CacheEntry:
    expires_at: float
    channels: tuple[SlackChannel, ...]


#: Per-connection, in-process, never persisted.
#:
#: Keyed on the connection id — which is per-tenant — rather than on the team id,
#: so there is no key a second workspace could collide with. Process-local
#: because the alternative, a shared cache, would put channel names in a store
#: with its own lifetime and its own readers for the sake of saving one API call.
_CACHE: dict[uuid.UUID, _CacheEntry] = {}


def forget_channels(connection_id: uuid.UUID) -> None:
    """Drop one connection's cached names.

    Called on disconnect. A workspace that has asked CAIRN to stop reading its
    Slack must not leave its channel names sitting in this process's memory for
    the next minute, and "it expires soon" is not the answer to give somebody who
    just withdrew permission.
    """
    _CACHE.pop(connection_id, None)


def clear_channel_cache() -> None:
    """Drop every cached list. For tests, which must not inherit each other's."""
    _CACHE.clear()


async def available_channels(
    api: SlackApi,
    *,
    connection_id: uuid.UUID,
    token: SecretValue,
    now: float | None = None,
) -> tuple[SlackChannel, ...]:
    """The workspace's public channels, from Slack or from the short cache."""
    moment = now if now is not None else time.monotonic()

    cached = _CACHE.get(connection_id)
    if cached is not None and cached.expires_at > moment:
        return cached.channels

    channels = await api.list_public_channels(token=token)
    _CACHE[connection_id] = _CacheEntry(expires_at=moment + CACHE_TTL_SECONDS, channels=channels)
    return channels


def normalise_channel_ids(channel_ids: Iterable[str]) -> tuple[str, ...]:
    """Validate and de-duplicate a requested selection.

    Raises:
        SlackSelectionError: Something that is not a Slack channel id, or more
            ids than one request may carry. The message deliberately does not
            quote the offending value: a caller that sent ``#acme-layoffs``
            would otherwise have that name reflected into a response body and
            into whatever logged it.
    """
    seen: dict[str, None] = {}
    for raw in channel_ids:
        candidate = raw.strip()
        if not _CHANNEL_ID.match(candidate):
            # Deliberately describes the shape rather than showing the input.
            # The overwhelmingly likely cause is an interface that passed the
            # display label through, so the message says which of the two to
            # send.
            msg = (
                "Channels are selected by Slack channel ID (for example "
                "C0123ABCD), not by name. Channel names change; IDs do not."
            )
            raise SlackSelectionError(msg)
        # An ordered dict rather than a set: the response echoes the selection
        # back, and a set would reorder it into something that looks like a
        # different answer than the one that was sent.
        seen[candidate] = None

    if len(seen) > MAX_SELECTED_CHANNELS:
        msg = f"A selection may name at most {MAX_SELECTED_CHANNELS} channels."
        raise SlackSelectionError(msg)

    return tuple(seen)


async def selected_channel_ids(db: AsyncSession, *, connection_id: uuid.UUID) -> frozenset[str]:
    """Which channels this connection currently permits."""
    rows = await db.scalars(
        select(SlackChannelSelection.channel_id).where(
            SlackChannelSelection.connection_id == connection_id
        )
    )
    return frozenset(rows)


async def save_selection(
    db: AsyncSession,
    *,
    connection: SourceConnection,
    user_id: uuid.UUID,
    channel_ids: Sequence[str],
) -> tuple[str, ...]:
    """Replace this connection's selection with exactly these channels.

    Replace, not merge. A picker sends the full state of its checkboxes, and a
    merge would make unchecking a box do nothing — which is the failure mode that
    matters here, because the box being unchecked is somebody withdrawing
    permission to read a channel.

    Deselecting deletes the row rather than flagging it. The presence of the row
    *is* the permission (the ``source_opt_outs`` shape), so there is no second
    state to keep in agreement, and the application role holds no UPDATE on this
    table at all.

    Raises:
        SlackSelectionError: A value that is not a channel id, or too many.
    """
    wanted = normalise_channel_ids(channel_ids)
    current = await selected_channel_ids(db, connection_id=connection.id)

    removed = current - set(wanted)
    if removed:
        await db.execute(
            delete(SlackChannelSelection).where(
                SlackChannelSelection.connection_id == connection.id,
                SlackChannelSelection.channel_id.in_(removed),
            )
        )

    added = [channel_id for channel_id in wanted if channel_id not in current]
    for channel_id in added:
        db.add(
            SlackChannelSelection(
                tenant_id=connection.tenant_id,
                connection_id=connection.id,
                channel_id=channel_id,
                selected_by_user_id=user_id,
            )
        )

    await db.flush()

    await logger.ainfo(
        "slack.channel_selection_saved",
        tenant_id=str(connection.tenant_id),
        selected_by=str(user_id),
        # Counts, never ids and never names. A channel id identifies a
        # conversation inside a customer's workspace, and a log line is read by
        # people who were never granted a support session (md/15 §5.2).
        selected=len(wanted),
        added=len(added),
        removed=len(removed),
    )
    return wanted


async def is_channel_permitted(db: AsyncSession, *, tenant_id: uuid.UUID, channel_id: str) -> bool:
    """**The ingestion contract.** May this workspace process this channel?

    Call this before an event is stored, not after. A check performed on the way
    out is a check performed on data that has already been read, and "we deleted
    it afterwards" is not the promise this product makes.

    Both halves are checked in one statement, and both are load-bearing:

    - **The selection exists.** No row, no processing. This is what makes a
      connected workspace with an empty selection a workspace CAIRN reads
      nothing from.
    - **The connection is live.** A workspace that disconnected keeps its
      selection rows — so reconnecting restores the configuration rather than
      making somebody rebuild it — which means a selection alone would keep
      permitting reads after the customer turned the integration off.

    Runs on a tenant-scoped session in production, so row-level security is a
    second boundary underneath the explicit ``tenant_id`` predicate. The
    predicate is still written out: a query whose correctness depends only on the
    caller having remembered to scope its session is one mistake away from
    reading everybody's selections.
    """
    if not _CHANNEL_ID.match(channel_id):
        # A malformed id cannot match a stored selection anyway. Refused here so
        # the answer is a plain `False` rather than a query, and so a caller
        # passing a channel *name* is denied rather than silently mismatched.
        return False

    found = await db.scalar(
        select(SlackChannelSelection.id)
        .join(SourceConnection, SourceConnection.id == SlackChannelSelection.connection_id)
        .where(
            SlackChannelSelection.tenant_id == tenant_id,
            SlackChannelSelection.channel_id == channel_id,
            SourceConnection.provider == ConnectorProvider.SLACK,
            SourceConnection.state == ConnectionState.CONNECTED,
            SourceConnection.disconnected_at.is_(None),
            SourceConnection.revoked_at.is_(None),
        )
        .limit(1)
    )
    return found is not None
