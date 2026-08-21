"""Connecting Google Chat, and choosing what CAIRN may read from it.

Five routes across two routers, and the split is forced rather than stylistic —
exactly as in ``api/routers/slack.py``. Four of them live under
``/workspaces/{workspace_id}`` and are gated on a session, a membership and a
permission. The fifth cannot: Google registers **one** redirect URI per OAuth
client, character for character, so it can carry no workspace id, and
``CurrentMembership`` would reject the request before the handler ran. What
identifies the workspace on the way back is the ``state`` parameter, which is
precisely why it is server-side, single-use and bound to the person who started
the install.

**Connecting grants nothing.** It creates a `SourceConnection` and stores a
refresh token, and CAIRN processes not one message until a space is selected.
Selecting is also what creates the Workspace Events subscription, so the
permission and the plumbing are one operation with one owner —
`gchat.spaces.save_selection`.

**The Pub/Sub receiver is not in this file and is not in the client.** It lives
in ``api/routers/gchat_push.py``, is unauthenticated by necessity, and is
verified by a Google-signed token rather than by a session. Nothing here exposes
it, and the OpenAPI document a customer's browser is built against must never
learn it exists.

**No route here returns a token, a Google error string, or a space display name
outside the Owner/Admin picker.** Failures arrive as a
`GoogleChatInstallFailure` — our vocabulary — and a `ConnectorErrorCategory`,
which is the closed set the rest of the product already reports on.

Every workspace-scoped route runs on the **platform** connection, which is one
place this file departs from the Slack one. Two reasons, both mechanical: an
access token is obtained by refreshing, and a failed refresh writes the reason
onto ``source_connections``, where the application role holds SELECT only; and
saving a selection writes ``google_chat_subscriptions``, where it also holds
SELECT only. Both grants are deliberate (see the migration), so the writes
belong platform-side, and every statement here carries its tenant predicate
explicitly rather than relying on a session scope it does not have.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from urllib.parse import urlencode

import structlog
from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cairn_api.api.dependencies import (
    CurrentUser,
    PlatformDb,
    SettingsDep,
    WorkspaceContext,
    requires,
)
from cairn_api.api.errors import ProblemDetailError
from cairn_api.api.schemas import (
    GoogleChatDisconnectResponse,
    GoogleChatInstallResponse,
    GoogleChatSpaceListResponse,
    GoogleChatSpaceResponse,
    GoogleChatSpaceSelectionRequest,
    GoogleChatSpaceSelectionResponse,
)
from cairn_api.auth.permissions import Permission, has_permission
from cairn_api.config import Settings
from cairn_api.connectors.credentials import read_secret
from cairn_api.db.connector_models import SourceConnection
from cairn_api.db.gchat_models import GoogleChatSubscription
from cairn_api.db.models import Membership
from cairn_api.gchat import oauth
from cairn_api.gchat import spaces as space_selection
from cairn_api.gchat import subscriptions as subscription_engine
from cairn_api.gchat.oauth import (
    GoogleChatApi,
    GoogleChatInstallError,
    GoogleChatInstallFailure,
    HttpGoogleChatApi,
)
from cairn_api.gchat.spaces import HttpSpaceDirectory, SpaceDirectory

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/workspaces", tags=["google-chat"])

#: The callback. No workspace in the path, because Google registers one redirect
#: URI per OAuth client and it must match the exchange request byte for byte.
callback_router = APIRouter(prefix="/integrations/google-chat", tags=["google-chat"])

#: Where the browser lands after the callback, relative to `public_app_url`.
#: The integration is configured from the workspace admin screen, so that is
#: where somebody mid-install expects to be put back.
RETURN_PATH = "/admin"

#: The bounded outcomes the callback may report, and the whole vocabulary of the
#: query string it redirects with. Nothing Google said reaches the URL bar —
#: which is the one place a customer's error message is also in their browser
#: history and in any referrer that follows.
OUTCOME_CONNECTED = "connected"
OUTCOME_DENIED = "denied"
OUTCOME_ERROR = "error"

#: The failures that mean "a human said no" rather than "something broke". Kept
#: as a set rather than tested inline so the two cases stay one decision: the
#: person declined on the consent screen, or their Workspace administrator has
#: blocked the scope. Both are answered by talking to somebody, not by retrying.
_DENIALS = frozenset(
    {
        GoogleChatInstallFailure.DECLINED,
        GoogleChatInstallFailure.ADMIN_POLICY_ENFORCED,
    }
)


def google_chat_api(settings: SettingsDep) -> GoogleChatApi:
    """The Google OAuth/Chat client for this request.

    A dependency rather than a module global, which is what makes "no unit test
    calls Google" true by construction: a test overrides this one function and
    every route in the file is served by the double. Nothing patches a module
    attribute, so nothing can forget to put it back.

    Raises:
        ProblemDetailError: 503 when Google Chat is not configured on this
            deployment. An operator's problem, and it must not read as "Google
            said no".
    """
    try:
        return HttpGoogleChatApi(
            client_id=settings.google_chat_client_id,
            client_secret=settings.google_chat_client_secret.get_secret_value(),
        )
    except GoogleChatInstallError as error:
        raise _problem(error, status.HTTP_503_SERVICE_UNAVAILABLE) from error


def space_directory() -> SpaceDirectory:
    """The space lister for this request.

    Separate from `google_chat_api` because it is a separate protocol with a
    separate double: this is the only call that returns display names, and
    keeping it on its own dependency means a test can serve a picker without
    also having to implement token exchange.
    """
    return HttpSpaceDirectory()


def subscription_client(settings: SettingsDep) -> subscription_engine.SubscriptionClient | None:
    """The Workspace Events client, or ``None`` on a deployment with no topic.

    ``None`` rather than a 503, because a missing topic must not stop somebody
    withdrawing a permission. A selection can still be saved and a space can
    still be deselected; what cannot happen is a lease being created, and
    `spaces.save_selection` records that in its log line rather than pretending
    the feed is live.
    """
    return subscription_engine.build_client(settings)


GoogleChatApiDep = Annotated[GoogleChatApi, Depends(google_chat_api)]
SpaceDirectoryDep = Annotated[SpaceDirectory, Depends(space_directory)]
SubscriptionClientDep = Annotated[
    subscription_engine.SubscriptionClient | None, Depends(subscription_client)
]


def _problem(error: GoogleChatInstallError, status_code: int) -> ProblemDetailError:
    """Render a Google Chat failure as a problem document.

    Carries our failure code and the bounded category, never Google's words. The
    category is included so a client can behave differently for "wait" and "ask
    an admin" without parsing prose, and so the value a customer sees is the same
    one staff diagnostics show — two screens describing one fault in one
    vocabulary.
    """
    return ProblemDetailError(
        status_code=status_code,
        title="Google Chat could not be connected",
        detail=error.detail,
        problem_type=f"google-chat-{error.failure.value.replace('_', '-')}",
        category=error.category.value,
    )


@router.post(
    "/{workspace_id}/integrations/google-chat/install",
    response_model=GoogleChatInstallResponse,
    summary="Begin connecting a Google Chat account",
    responses={
        403: {"description": "Requires permission to connect integrations."},
        503: {"description": "Google Chat is not configured on this deployment."},
    },
)
async def begin_install(
    context: Annotated[WorkspaceContext, Depends(requires(Permission.INTEGRATIONS_CONNECT))],
    db: PlatformDb,
    settings: SettingsDep,
) -> GoogleChatInstallResponse:
    """Issue a one-time state with its PKCE verifier, and return the authorise URL.

    Returns the URL rather than redirecting. The caller is a browser application
    doing this from an admin screen, and a 302 out of an XHR is either followed
    invisibly or blocked — neither of which lets the interface warn about the
    "add the app to the space" step before the customer is standing on Google's
    consent screen.

    Runs on the platform connection because ``google_chat_oauth_states`` is
    deliberately unreachable from the application role: the callback has to read
    the row with no tenant context to scope to, so every statement against that
    table is platform-side and the grant set says so.
    """
    if not oauth.is_configured(settings):
        # Checked before the state is written. Issuing a nonce and then failing
        # to build a URL would leave a live install state behind for an install
        # that could never start.
        raise _problem(
            GoogleChatInstallError(
                GoogleChatInstallFailure.NOT_CONFIGURED,
                "Google Chat is not configured on this deployment.",
            ),
            status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    nonce, verifier, expires_at = await oauth.issue_state(
        db, tenant_id=context.tenant_id, user_id=context.user.id
    )
    await db.commit()

    await logger.ainfo(
        "gchat.install_started",
        tenant_id=str(context.tenant_id),
        started_by=str(context.user.id),
        # Neither the nonce nor the verifier is present, on purpose. A log line
        # carrying them is a log line from which somebody can complete an install
        # a workspace admin started.
    )

    return GoogleChatInstallResponse(
        authorize_url=oauth.build_authorize_url(settings, state=nonce, code_verifier=verifier),
        expires_at=expires_at,
        notice=space_selection.APP_ADDED_NOTICE,
    )


@callback_router.get(
    "/callback",
    summary="Finish connecting a Google Chat account",
    response_class=RedirectResponse,
    responses={303: {"description": "Back to the workspace's admin screen."}},
)
async def finish_install(
    request: Request,
    caller: CurrentUser,
    db: PlatformDb,
    settings: SettingsDep,
    api: GoogleChatApiDep,
    code: Annotated[str | None, Query()] = None,
    state: Annotated[str | None, Query()] = None,
    error: Annotated[str | None, Query()] = None,
) -> RedirectResponse:
    """Where Google sends the customer back.

    **Any ``error`` parameter is a failed install.** The callback branches on the
    *presence* of the parameter, never on the literal ``access_denied``: an
    equality check that missed would fall through to "exchange the code" with no
    code, and the customer would see a parse failure instead of "you declined".
    The value is read only to choose between "denied" and "error", and is then
    discarded.

    The order of the checks is the security property. The state is claimed —
    atomically, single-use — *before* anything is exchanged, so a replayed
    callback fails on the second attempt whether or not the first one worked.
    Then the caller is proved to **still** be a member of the state's workspace
    **with permission to connect**: minutes passed, and in those minutes the
    person may have been removed or demoted, and an install that completes on a
    permission that no longer exists is one nobody currently authorised. Only
    then is the code sent to Google.

    Redirects rather than returning JSON, because the thing following this URL is
    a browser mid-navigation, and the destination is built from
    ``public_app_url`` rather than from the request — the same rule as
    verification links, for the same reason.
    """
    if error is not None:
        failure = oauth.failure_for_google_error(error)
        return _back(settings, failure=failure)

    if state is None or code is None:
        return _back(settings, failure=GoogleChatInstallFailure.STATE_REJECTED)

    try:
        claimed = await oauth.consume_state(db, state=state, user_id=caller.user.id)
        # Committed immediately. If the exchange below fails or the process dies,
        # the state must stay consumed — "retry until it works" is
        # indistinguishable from a replay, and single-use is the property that
        # separates them.
        await db.commit()
    except GoogleChatInstallError as failure_error:
        return _back(settings, failure=failure_error.failure)

    # Read off the row now, while it is still loaded. A `rollback()` below expires
    # every instance in the session regardless of `expire_on_commit`, so touching
    # these afterwards issues a lazy SELECT from a synchronous attribute hook —
    # which under asyncpg raises `MissingGreenlet` from inside an exception
    # handler, turning a handled failure into a 500.
    tenant_id = claimed.tenant_id
    code_verifier = claimed.code_verifier

    membership = await db.scalar(
        select(Membership).where(
            Membership.tenant_id == tenant_id,
            Membership.user_id == caller.user.id,
        )
    )
    if membership is None or not has_permission(membership.role, Permission.INTEGRATIONS_CONNECT):
        await logger.awarning(
            "gchat.install_rejected",
            tenant_id=str(tenant_id),
            reason=GoogleChatInstallFailure.STATE_REJECTED.value,
        )
        return _back(settings, failure=GoogleChatInstallFailure.STATE_REJECTED)

    try:
        grant = await api.exchange_code(
            code=code,
            redirect_uri=settings.google_chat_redirect_uri,
            code_verifier=code_verifier,
        )
        # Probed before anything is written. A personal Gmail account completes
        # the whole OAuth flow perfectly and is then refused by every Chat call,
        # so without this the customer gets a connection that reports success, an
        # empty space picker, and no explanation anywhere.
        await oauth.ensure_workspace_account(api, access_token=grant.access_token)
        await oauth.record_installation(
            db, settings=settings, tenant_id=tenant_id, user_id=caller.user.id, grant=grant
        )
    except GoogleChatInstallError as failure_error:
        # Rolled back explicitly. `record_installation` writes a connection and a
        # credential; leaving a half-written connection behind would be a
        # workspace that reads as connected with no usable token.
        await db.rollback()
        await logger.awarning(
            "gchat.install_failed",
            tenant_id=str(tenant_id),
            reason=failure_error.failure.value,
            category=failure_error.category.value,
        )
        return _back(settings, failure=failure_error.failure)

    await db.commit()
    _ = request  # The destination is built from settings, never from this.
    return _back(settings, failure=None)


def _back(settings: Settings, *, failure: GoogleChatInstallFailure | None) -> RedirectResponse:
    """Send the browser back to the admin screen with a bounded outcome.

    Three values, and only three. The Slack callback carries a reason and a
    category as well; this one deliberately does not, because a Google failure
    code in a URL is a Google failure code in browser history, in a referrer and
    in any analytics the customer's own site runs — and the actionable half of it
    is already on the connection, behind the session, where the admin screen
    reads it.
    """
    destination = f"{settings.public_app_url.rstrip('/')}{RETURN_PATH}"
    if failure is None:
        outcome = OUTCOME_CONNECTED
    elif failure in _DENIALS:
        outcome = OUTCOME_DENIED
    else:
        outcome = OUTCOME_ERROR
    query = urlencode({"googleChat": outcome})
    # 303, not 302: the browser must issue a GET for the destination regardless
    # of how it arrived, and 302's method handling is famously
    # implementation-defined.
    return RedirectResponse(f"{destination}?{query}", status_code=status.HTTP_303_SEE_OTHER)


@router.get(
    "/{workspace_id}/integrations/google-chat/spaces",
    response_model=GoogleChatSpaceListResponse,
    summary="List the Google Chat spaces CAIRN could read",
    responses={
        403: {"description": "Requires permission to connect integrations."},
        404: {"description": "No Google Chat account is connected."},
        502: {"description": "Google could not be reached."},
    },
)
async def list_spaces(
    context: Annotated[WorkspaceContext, Depends(requires(Permission.INTEGRATIONS_CONNECT))],
    db: PlatformDb,
    api: GoogleChatApiDep,
    directory: SpaceDirectoryDep,
) -> GoogleChatSpaceListResponse:
    """The picker's contents: every eligible named space, and the state of its feed.

    Gated on `INTEGRATIONS_CONNECT` — Owner and Admin — rather than on plain
    membership. This is the one endpoint in the API that returns Google Chat
    space **display names**, and the people who may see the list are the people
    who may change what CAIRN reads. A Member gains nothing from a list they
    cannot act on, and a space name is frequently the most sensitive string a
    customer holds.

    Direct messages, one-to-one app conversations and unnamed spaces never reach
    this response: `spaces.eligible_spaces` removes them, in addition to the
    server-side filter Google is asked for. Two filters rather than one, because
    a picker that offered a direct message would not be noticed until somebody
    selected it.
    """
    connection = await _connected_or_404(db, context)

    try:
        token = await oauth.access_token_for(api, connection)
        available = await space_selection.eligible_spaces(directory, access_token=token)
    except GoogleChatInstallError as error:
        # `access_token_for` records the reason on the connection before raising,
        # so the commit keeps it. Without this the admin screen would show a
        # healthy connection that has been failing to refresh for a week.
        await db.commit()
        raise _problem(error, status.HTTP_502_BAD_GATEWAY) from error

    selected = await space_selection.selected_space_names(db, connection_id=connection.id)
    leases = await space_selection.subscriptions_by_space(db, connection_id=connection.id)
    await db.commit()

    return GoogleChatSpaceListResponse(
        spaces=[
            _space_response(space, selected=space.name in selected, lease=leases.get(space.name))
            for space in available
        ],
        notice=space_selection.APP_ADDED_NOTICE,
    )


def _space_response(
    space: space_selection.AvailableSpace,
    *,
    selected: bool,
    lease: GoogleChatSubscription | None,
) -> GoogleChatSpaceResponse:
    """One row of the picker.

    An unselected space has no lease, so all three subscription fields are
    ``None``. That is deliberately distinguishable from a selected space whose
    lease is ``pending`` — "we have not asked yet" and "we asked and Google has
    not answered" are different things to be looking at while a feed is empty.
    """
    return GoogleChatSpaceResponse(
        name=space.name,
        display_name=space.display_name,
        eligible=space.eligible,
        selected=selected,
        subscription_state=None if lease is None else lease.state.value,
        expire_time=None if lease is None else lease.expire_time,
        error_category=(
            None
            if lease is None or lease.suspension_category is None
            else lease.suspension_category.value
        ),
    )


@router.put(
    "/{workspace_id}/integrations/google-chat/spaces",
    response_model=GoogleChatSpaceSelectionResponse,
    summary="Choose which Google Chat spaces CAIRN may process",
    responses={
        403: {"description": "Requires permission to connect integrations."},
        404: {"description": "No Google Chat account is connected."},
        409: {"description": "A space is already connected to another workspace."},
        422: {"description": "A value was not a Google Chat space resource name."},
    },
)
async def save_spaces(
    body: GoogleChatSpaceSelectionRequest,
    context: Annotated[WorkspaceContext, Depends(requires(Permission.INTEGRATIONS_CONNECT))],
    db: PlatformDb,
    client: SubscriptionClientDep,
) -> GoogleChatSpaceSelectionResponse:
    """Replace the selection with exactly these spaces, and move the subscriptions.

    ``PUT`` rather than ``POST``, and a replace rather than a merge, because the
    body is the full state of a set of checkboxes. A merge would make unchecking
    a box do nothing — and the box being unchecked is somebody withdrawing
    permission for CAIRN to read a conversation, which is the single operation on
    this endpoint that must not silently fail.

    An empty list is valid and means "process nothing", which is also the state a
    freshly connected account is in.

    **This is where the subscription lifecycle is driven from.** Selecting a space
    creates a Workspace Events lease; deselecting deletes the selection row —
    which blocks ingestion the moment it lands — and then tears the lease down.
    The commit happens after both, so a caller that receives 200 has had every
    removal persisted.
    """
    connection = await _connected_or_404(db, context)

    try:
        saved = await space_selection.save_selection(
            db,
            client,
            connection=connection,
            user_id=context.user.id,
            space_names=body.space_names,
        )
    except space_selection.GoogleChatSpaceClaimedError as error:
        # 409, not 422: the request is well formed and the caller has done
        # nothing wrong — the space is simply taken. Distinct from the 422 below
        # so an interface can offer "disconnect it there first" rather than
        # "check what you typed".
        raise ProblemDetailError(
            status_code=status.HTTP_409_CONFLICT,
            title="That space is connected elsewhere",
            detail=str(error),
            problem_type="google-chat-space-claimed",
        ) from error
    except space_selection.GoogleChatSelectionError as error:
        raise ProblemDetailError(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            title="That selection cannot be saved",
            detail=str(error),
            problem_type="google-chat-space-selection-invalid",
        ) from error

    await db.commit()
    return GoogleChatSpaceSelectionResponse(
        space_names=list(saved), notice=space_selection.APP_ADDED_NOTICE
    )


@router.post(
    "/{workspace_id}/integrations/google-chat/disconnect",
    response_model=GoogleChatDisconnectResponse,
    summary="Disconnect Google Chat and destroy the stored credential",
    responses={
        403: {"description": "Requires permission to disconnect integrations."},
        404: {"description": "No Google Chat account is connected."},
    },
)
async def disconnect_google_chat(
    context: Annotated[WorkspaceContext, Depends(requires(Permission.INTEGRATIONS_DISCONNECT))],
    db: PlatformDb,
    client: SubscriptionClientDep,
) -> GoogleChatDisconnectResponse:
    """Stop collecting, tear the leases down, and drop the refresh token.

    All three, in one call, with no option to do only the first. A disconnect
    that leaves the credential behind keeps CAIRN holding a standing grant to
    read a customer's conversations after they asked it to stop — and from
    outside there is no way to tell the two apart, which is exactly why the
    response says which happened.

    The subscriptions are removed **before** the credential is destroyed, because
    deleting a lease at Google needs a token. Every space is blocked locally
    whether or not that succeeds: `remove_all_subscriptions` marks each row before
    it calls Google and does not stop on an error, and the connection state this
    handler then sets is itself what `spaces.is_space_permitted` refuses on. A
    lease that survives at Google therefore delivers into a workspace that will
    not read it, and lapses on its own inside four hours.

    **The response tells the truth about retention.** Disconnecting stops new
    collection; it does not delete what was already recorded. Saying otherwise
    would be the shorter sentence and a false one.
    """
    connection = await _connected_or_404(db, context)

    if client is not None:
        await subscription_engine.remove_all_subscriptions(db, client, connection)

    await oauth.disconnect(connection)
    await db.commit()

    await logger.ainfo(
        "gchat.disconnected",
        tenant_id=str(context.tenant_id),
        disconnected_by=str(context.user.id),
    )

    return GoogleChatDisconnectResponse(
        state=connection.state.value,
        disconnected_at=connection.disconnected_at or datetime.now(UTC),
        credential_cleared=read_secret(connection) is None,
        retention_notice=(
            "Google Chat will stop being collected from immediately, the event "
            "subscriptions have been torn down, and the stored refresh token has "
            "been destroyed. What CAIRN already recorded from Google Chat is not "
            "deleted by disconnecting — the space selection is kept too, so "
            "reconnecting restores it."
        ),
    )


async def _connected_or_404(db: AsyncSession, context: WorkspaceContext) -> SourceConnection:
    """This workspace's live Google Chat connection, or a 404.

    404 rather than 409 for a connection that exists but is disconnected. From
    the caller's side those are the same fact — there is no Google Chat here —
    and the distinction only matters to somebody probing whether a workspace once
    had one.
    """
    connection = await oauth.find_connection(db, tenant_id=context.tenant_id)
    if connection is None or not connection.is_active:
        raise _not_connected()
    return connection


def _not_connected() -> ProblemDetailError:
    return ProblemDetailError(
        status_code=status.HTTP_404_NOT_FOUND,
        title="Google Chat is not connected",
        detail="No Google Chat account is connected to this workspace.",
        problem_type="google-chat-not-connected",
    )


__all__ = ["callback_router", "google_chat_api", "router", "space_directory", "subscription_client"]
