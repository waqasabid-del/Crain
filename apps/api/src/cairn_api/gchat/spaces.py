"""Which Google Chat spaces CAIRN may read, and the one question ingestion asks.

**Selection is the permission.** A Google Chat account can be connected, healthy
and fully scoped, and CAIRN processes nothing from it until somebody chooses
spaces. There is no "all spaces" option and no default selection, because a
default that includes the space created tomorrow is a permission nobody gave —
and the space most likely to be created tomorrow is the one about a
reorganisation.

:func:`is_space_permitted` is the whole contract for the ingestion side. It
answers "may this workspace process this space" with a single boolean, and it
checks the *connection* as well as the selection: a disconnected workspace with a
full selection permits nothing.

Two things make this file different from ``slack/channels.py``:

**Saving a selection creates and destroys Google Workspace Events
subscriptions.** A Chat space delivers nothing without one, so a selection that
only wrote a row would be a checkbox that reports success and produces silence
forever. :func:`save_selection` therefore calls ``gchat.subscriptions`` for every
space added and every space removed — that is the vertical slice, and there is no
second place that does it.

**Removing a selection blocks immediately, whatever Google says.** The selection
row is deleted and flushed *before* a byte goes to Google, and
`subscriptions.remove_subscription` marks its own row the same way. A remote
delete that fails leaves the lease to lapse inside its four-hour TTL, and
`subscriptions.resolve_space` refuses everything it publishes meanwhile. The
reverse order produces the one failure this product cannot have: a withdrawn
permission that keeps taking data because a third party was unreachable.

Nothing here persists a space display name. Names arrive from Google for the
Owner/Admin picker and are gone by the end of the request; see
``db/gchat_models.GoogleChatSpaceSelection.space_name``.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol, final

import httpx
import structlog
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from cairn_api.connectors.credentials import SecretValue
from cairn_api.db.connector_models import ConnectionState, ConnectorProvider, SourceConnection
from cairn_api.db.gchat_models import (
    SPACE_NAME_PATTERN,
    GoogleChatSpaceSelection,
    GoogleChatSubscription,
)
from cairn_api.gchat import subscriptions as subscription_engine
from cairn_api.gchat.oauth import (
    REQUEST_TIMEOUT_SECONDS,
    SPACES_LIST_URL,
    GoogleChatInstallError,
    GoogleChatInstallFailure,
)
from cairn_api.gchat.oauth import (
    _chat_body as translate_chat_response,
)

logger = structlog.get_logger(__name__)

# `_chat_body` is imported rather than reimplemented, and the underscore is not
# an oversight. It is the single place Google's Chat statuses become CAIRN's
# bounded failures, and — critically — the place that refuses to read Google's
# ``error.message``, which names the space and frequently the person. A second
# copy here would be a second thing to keep honest, and the copy that eventually
# passes the message through is the one nobody reviewed.

#: Compiled once. Mirrors the CHECK constraint on both Google Chat tables, so a
#: display name is refused with a 422 naming the field rather than as an
#: IntegrityError several frames later.
_SPACE_NAME = re.compile(SPACE_NAME_PATTERN)

#: Google's ``spaceType`` for a named space — the only kind CAIRN will read.
NAMED_SPACE_TYPE = "SPACE"

#: The server-side filter, applied *as well as* the local eligibility check
#: below. Asking Google to filter saves a page of direct messages crossing the
#: wire; checking again locally is what makes "we only ever offer named spaces"
#: true rather than "we asked nicely".
NAMED_SPACE_FILTER = f'spaceType = "{NAMED_SPACE_TYPE}"'

_SPACE_PAGE_SIZE = 100

#: Bounded rather than ``while True``. A provider that keeps returning a page
#: token — through a bug or a hostile response — would otherwise spin forever
#: inside a request handler.
_MAX_SPACE_PAGES = 10

#: Ceiling on how many spaces one workspace may select in one request.
#:
#: Not a technical limit — it is a bound on a request body, so an accidental or
#: hostile caller cannot make one PUT insert an unbounded number of rows *and*
#: issue an unbounded number of calls to Google.
MAX_SELECTED_SPACES = 1000

#: What every surface showing the picker must say.
#:
#: Served from the API rather than written into the interface, for the reason
#: `ConsentResponse.refusals` is: a promise stated in one client is a promise the
#: next client forgets. This one is not a nicety — a customer who selects a space
#: the CAIRN app is not in gets an integration that reports success and delivers
#: silence, and concludes CAIRN does not work.
APP_ADDED_NOTICE = (
    "CAIRN only receives messages from spaces the CAIRN app has been added to, "
    "and only messages sent after you select the space. For each space you "
    "select, add the CAIRN app to it in Google Chat. CAIRN cannot add itself — "
    "it does not ask Google for permission to join spaces."
)


class GoogleChatSelectionError(ValueError):
    """A selection that cannot be saved, with a sentence safe to return.

    A ``ValueError`` subclass because it genuinely is bad input, and the message
    names the problem without echoing the offending value — a caller that sent a
    space *display name* would otherwise get that name reflected into a response
    body and, from there, into whatever logs the response.
    """


class GoogleChatSpaceClaimedError(GoogleChatSelectionError):
    """A space another CAIRN workspace is already reading.

    ``uq_google_chat_space_selections_space_name`` is **global**, deliberately:
    one Chat space feeds at most one CAIRN workspace, which is what makes a space
    resource name resolve to exactly one tenant on the Pub/Sub side. Without this
    check the constraint would surface as an ``IntegrityError`` several frames
    later and reach an Owner as a 500 — for an action that is neither a bug nor
    their fault.

    The message names no space. Telling one organisation *which* of its spaces
    another CAIRN customer is reading is a disclosure across the tenant boundary,
    which is the one boundary this product cannot leak across even by accident.
    """


@final
@dataclass(frozen=True, slots=True)
class AvailableSpace:
    """One space the authorising person can see, as Google described it just now.

    A transport object, never persisted. It carries a display name where
    `oauth.GoogleChatSpace` deliberately does not, and the difference is scope:
    that type is used by `oauth.ensure_workspace_account`, which runs at connect
    time and has no picker to draw. This one exists for exactly one endpoint —
    Owner/Admin, the caller's own workspace, read by somebody already looking at
    the same list in Google Chat — and the name never leaves that response. No
    column stores it, no log line carries it, and every other endpoint here
    answers in resource names alone.
    """

    #: ``spaces/{space}``. The only durable identifier a Chat event carries, and
    #: the key every permission here is stored under.
    name: str

    #: Google's ``displayName``. Empty for spaces that have none, which is also
    #: one of the things that makes a space ineligible.
    display_name: str

    #: Google's ``spaceType``.
    space_type: str

    #: Google's ``singleUserBotDm`` — a one-to-one conversation with an app.
    #: Carried separately because such a space can still report a ``spaceType``
    #: the filter accepts.
    single_user_bot_dm: bool

    @property
    def eligible(self) -> bool:
        """Whether CAIRN will offer this space at all.

        Three conditions, and each excludes something a customer would be
        alarmed to find in a picker:

        - **A named space.** ``spaceType`` other than ``SPACE`` is a direct
          message or a group direct message — private correspondence between
          named people, which nobody chose to make readable by a tool.
        - **Not an app DM.** ``singleUserBotDm`` is one person's private
          conversation with an app.
        - **Actually named.** An unnamed space has no display name, cannot be
          described to the person choosing, and is in practice an ad-hoc group
          conversation.
        """
        return (
            self.space_type == NAMED_SPACE_TYPE
            and not self.single_user_bot_dm
            and bool(self.display_name)
        )


class SpaceDirectory(Protocol):
    """The one network call the picker makes.

    A protocol with a single method, so a unit test supplies an object rather
    than patching a module global or intercepting a transport — the same split
    `gchat/oauth.py` and `gchat/subscriptions.py` use, and for the same reason:
    "no unit test calls Google" becomes a property of the structure rather than
    of everyone remembering.

    Implementations raise `GoogleChatInstallError` and nothing else.
    """

    async def list_spaces(self, *, access_token: SecretValue) -> tuple[AvailableSpace, ...]:
        """Every space the authorising person can see, eligible or not."""
        ...


@final
class HttpSpaceDirectory:
    """The real one. Lists spaces, following page tokens to the end."""

    __slots__ = ()

    async def list_spaces(self, *, access_token: SecretValue) -> tuple[AvailableSpace, ...]:
        spaces: list[AvailableSpace] = []
        page_token = ""
        for _ in range(_MAX_SPACE_PAGES):
            params = {"pageSize": str(_SPACE_PAGE_SIZE), "filter": NAMED_SPACE_FILTER}
            if page_token:
                params["pageToken"] = page_token
            payload = await self._get(params, access_token=access_token)
            spaces.extend(_spaces_from(payload))
            raw_token = payload.get("nextPageToken")
            page_token = raw_token if isinstance(raw_token, str) else ""
            if not page_token:
                break
        return tuple(spaces)

    async def _get(
        self, params: Mapping[str, str], *, access_token: SecretValue
    ) -> Mapping[str, object]:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            try:
                response = await client.get(
                    SPACES_LIST_URL,
                    params=dict(params),
                    headers={"Authorization": f"Bearer {access_token.reveal()}"},
                )
            except httpx.HTTPError as exc:
                raise GoogleChatInstallError(GoogleChatInstallFailure.PROVIDER_UNAVAILABLE) from exc
        return translate_chat_response(response)


def _spaces_from(payload: Mapping[str, object]) -> list[AvailableSpace]:
    """Read one page of ``spaces.list``, skipping anything malformed.

    A space with no ``name`` is skipped outright — there is nothing to key a
    permission on. Everything else is carried through *including* the ineligible
    ones, because eligibility is decided by :meth:`AvailableSpace.eligible` in
    one place rather than by whichever parser saw the row first.
    """
    raw = payload.get("spaces")
    if not isinstance(raw, list):
        return []

    spaces: list[AvailableSpace] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if not isinstance(name, str) or not name:
            continue
        display = item.get("displayName")
        space_type = item.get("spaceType")
        spaces.append(
            AvailableSpace(
                name=name,
                display_name=display if isinstance(display, str) else "",
                space_type=space_type if isinstance(space_type, str) else "",
                single_user_bot_dm=item.get("singleUserBotDm") is True,
            )
        )
    return spaces


async def eligible_spaces(
    directory: SpaceDirectory, *, access_token: SecretValue
) -> tuple[AvailableSpace, ...]:
    """The picker's contents: only the spaces CAIRN is willing to read.

    The filter is applied here rather than at the endpoint, so there is no
    version of this list that reaches a response with a direct message in it.
    """
    listed = await directory.list_spaces(access_token=access_token)
    return tuple(space for space in listed if space.eligible)


def normalise_space_names(space_names: Iterable[str]) -> tuple[str, ...]:
    """Validate and de-duplicate a requested selection.

    Raises:
        GoogleChatSelectionError: Something that is not a space resource name, or
            more names than one request may carry. The message deliberately does
            not quote the offending value: a caller that sent
            ``Acme / Northwind diligence`` would otherwise have that name
            reflected into a response body and into whatever logged it.
    """
    seen: dict[str, None] = {}
    for raw in space_names:
        candidate = raw.strip()
        if not _SPACE_NAME.fullmatch(candidate):
            # Describes the shape rather than showing the input. The
            # overwhelmingly likely cause is an interface that passed the
            # display label through, or one that stripped the ``spaces/``
            # prefix "for tidiness" — a bare id would never match the resource
            # name a Chat event carries, so it is a permission that looks
            # granted and delivers nothing.
            msg = (
                "Spaces are selected by Google Chat resource name (for example "
                "spaces/AAAA1111), not by display name, and the spaces/ prefix "
                "is part of the name."
            )
            raise GoogleChatSelectionError(msg)
        # An ordered dict rather than a set: the response echoes the selection
        # back, and a set would reorder it into something that looks like a
        # different answer than the one that was sent.
        seen[candidate] = None

    if len(seen) > MAX_SELECTED_SPACES:
        msg = f"A selection may name at most {MAX_SELECTED_SPACES} spaces."
        raise GoogleChatSelectionError(msg)

    return tuple(seen)


async def selected_space_names(db: AsyncSession, *, connection_id: uuid.UUID) -> frozenset[str]:
    """Which spaces this connection currently permits."""
    rows = await db.scalars(
        select(GoogleChatSpaceSelection.space_name).where(
            GoogleChatSpaceSelection.connection_id == connection_id
        )
    )
    return frozenset(rows)


async def subscriptions_by_space(
    db: AsyncSession, *, connection_id: uuid.UUID
) -> dict[str, GoogleChatSubscription]:
    """This connection's leases, keyed by space, for the picker.

    Read as whole rows rather than reduced like `subscriptions.subscription_records`
    because this caller is the customer's own Owner/Admin looking at their own
    workspace, and the two facts they need — is it delivering, and when does it
    lapse — are per space. Nothing Google wrote is in any of these columns.
    """
    rows = await db.scalars(
        select(GoogleChatSubscription).where(GoogleChatSubscription.connection_id == connection_id)
    )
    return {row.space_name: row for row in rows.all()}


async def save_selection(
    db: AsyncSession,
    client: subscription_engine.SubscriptionClient | None,
    *,
    connection: SourceConnection,
    user_id: uuid.UUID,
    space_names: Sequence[str],
) -> tuple[str, ...]:
    """Replace this connection's selection with exactly these spaces, and subscribe.

    Replace, not merge. A picker sends the full state of its checkboxes, and a
    merge would make unchecking a box do nothing — which is the failure mode that
    matters here, because the box being unchecked is somebody withdrawing
    permission to read a conversation.

    **Removals happen first, and land before Google is called.** The rows are
    deleted and flushed, which alone stops ingestion —
    `subscriptions.resolve_space` treats an absent selection as "no", so a space
    is blocked the moment the statement lands whether or not the remote delete
    that follows succeeds.

    **A failed subscription does not fail the save.** The space stays selected
    and its subscription row carries the category, which is what the picker
    renders; a save that rolled back would discard four working spaces because
    the fifth was throttled, and would leave the customer no way to see which.

    Raises:
        GoogleChatSelectionError: A value that is not a space resource name, or
            too many.
        GoogleChatSpaceClaimedError: A space another workspace already reads.
            Raised before anything is sent to Google, so a refused save leaves no
            lease behind — and the caller's transaction is rolled back whole,
            including the removals above.
    """
    wanted = normalise_space_names(space_names)
    current = await selected_space_names(db, connection_id=connection.id)

    removed = sorted(current - set(wanted))
    if removed:
        await db.execute(
            delete(GoogleChatSpaceSelection).where(
                GoogleChatSpaceSelection.connection_id == connection.id,
                GoogleChatSpaceSelection.space_name.in_(removed),
            )
        )
        # Flushed before a byte goes to Google. See the docstring — this is the
        # statement that withdraws the permission, and everything after it is
        # tidying up a lease that can no longer deliver anything readable.
        await db.flush()

    added = [space_name for space_name in wanted if space_name not in current]
    if added:
        # Checked before the insert rather than caught after it. This statement
        # deliberately reads across tenants — it runs on the platform connection
        # and carries no tenant predicate — because the question is precisely
        # "does *anybody else* already read this space", and a tenant-scoped
        # version of it would always answer no and always be wrong.
        claimed = await db.scalar(
            select(GoogleChatSpaceSelection.id)
            .where(
                GoogleChatSpaceSelection.space_name.in_(added),
                GoogleChatSpaceSelection.connection_id != connection.id,
            )
            .limit(1)
        )
        if claimed is not None:
            msg = (
                "One of those spaces is already connected to a different CAIRN "
                "workspace. A Google Chat space can feed only one workspace at a "
                "time; disconnect it there first."
            )
            raise GoogleChatSpaceClaimedError(msg)

    for space_name in added:
        db.add(
            GoogleChatSpaceSelection(
                tenant_id=connection.tenant_id,
                connection_id=connection.id,
                space_name=space_name,
                selected_by_user_id=user_id,
            )
        )
    if added:
        await db.flush()

    failed = 0
    if client is not None:
        for space_name in removed:
            await subscription_engine.remove_subscription(
                db, client, connection, space_name=space_name
            )
        for space_name in added:
            try:
                await subscription_engine.ensure_subscription(
                    db, client, connection, space_name=space_name
                )
            except subscription_engine.SubscriptionError:
                # Already recorded on the row, with a bounded category. Counted
                # here and swallowed: see the docstring on why one throttled
                # space must not discard four working ones.
                failed += 1

    await logger.ainfo(
        "gchat.space_selection_saved",
        tenant_id=str(connection.tenant_id),
        selected_by=str(user_id),
        # Counts, never resource names and never display names. A space name
        # identifies a conversation inside a customer's organisation, and a log
        # line is read by people who were never granted a support session.
        selected=len(wanted),
        added=len(added),
        removed=len(removed),
        subscribe_failed=failed,
        # True when the deployment has no Pub/Sub topic. The selection is still
        # recorded — it is the customer's decision, not the deployment's — but
        # nothing will arrive, and this is the field that says so.
        unsubscribed=client is None,
    )
    return wanted


async def is_space_permitted(db: AsyncSession, *, tenant_id: uuid.UUID, space_name: str) -> bool:
    """**The ingestion contract.** May this workspace process this space?

    Call this before an event is stored, not after. A check performed on the way
    out is a check performed on data that has already been read, and "we deleted
    it afterwards" is not the promise this product makes.

    Both halves are checked in one statement, and both are load-bearing:

    - **The selection exists.** No row, no processing. This is what makes a
      connected account with an empty selection an account CAIRN reads nothing
      from, and it is why deselecting deletes the row rather than flagging it.
    - **The connection is live.** ``CONNECTED``, never disconnected, never
      revoked. A revoked connection is what `oauth.mark_refresh_failure` leaves
      behind when a standing grant is withdrawn at Google, and ingestion has to
      stop on that as surely as on a customer pressing Disconnect.

    The subscription table is deliberately **not** consulted. A row there is not
    a permission; a lease that outlived a deselection must read nothing, which is
    guaranteed by the selection row being gone rather than by a state column
    agreeing.
    """
    if not _SPACE_NAME.fullmatch(space_name):
        # A malformed name cannot match a stored selection anyway. Refused here
        # so the answer is a plain `False` rather than a query, and so a caller
        # passing a display name is denied rather than silently mismatched.
        return False

    found = await db.scalar(
        select(GoogleChatSpaceSelection.id)
        .join(SourceConnection, SourceConnection.id == GoogleChatSpaceSelection.connection_id)
        .where(
            GoogleChatSpaceSelection.tenant_id == tenant_id,
            GoogleChatSpaceSelection.space_name == space_name,
            SourceConnection.provider == ConnectorProvider.GOOGLE_CHAT,
            SourceConnection.state == ConnectionState.CONNECTED,
            SourceConnection.disconnected_at.is_(None),
            SourceConnection.revoked_at.is_(None),
        )
        .limit(1)
    )
    return found is not None


__all__ = [
    "APP_ADDED_NOTICE",
    "MAX_SELECTED_SPACES",
    "NAMED_SPACE_FILTER",
    "NAMED_SPACE_TYPE",
    "AvailableSpace",
    "GoogleChatSelectionError",
    "GoogleChatSpaceClaimedError",
    "HttpSpaceDirectory",
    "SpaceDirectory",
    "eligible_spaces",
    "is_space_permitted",
    "normalise_space_names",
    "save_selection",
    "selected_space_names",
    "subscriptions_by_space",
]
