"""Connecting Slack, and choosing what CAIRN may read from it.

Five routes across two routers, and the split is forced rather than stylistic.
Four of them live under ``/workspaces/{workspace_id}`` and are gated exactly like
``connect_github`` — a session, a membership, a permission. The fifth cannot: the
OAuth callback URL is registered with Slack once, character for character, so it
can carry no workspace id, and ``CurrentMembership`` would reject the request
before the handler ran. What identifies the workspace on the way back is the
``state`` parameter, which is precisely why it is server-side, single-use and
bound to the person who started the install.

**Connecting grants nothing.** It creates a `SourceConnection` and stores a bot
token, and CAIRN processes not one message until a channel is selected. That is
the same rule ``connect_github`` states about historical collection, applied to a
source where the alternative is worse: Slack would happily return years of
history from every channel, and a connector that reaches for it has read a great
deal nobody chose to share.

**No route here returns a token, a channel name outside the picker, or a Slack
error string.** Failures arrive as a `SlackInstallFailure` — our vocabulary — and
a `ConnectorErrorCategory`, which is the closed set the rest of the product
already reports on.
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
    TenantDb,
    WorkspaceContext,
    requires,
)
from cairn_api.api.errors import ProblemDetailError
from cairn_api.api.schemas import (
    SlackChannelListResponse,
    SlackChannelResponse,
    SlackChannelSelectionRequest,
    SlackChannelSelectionResponse,
    SlackDisconnectResponse,
    SlackInstallResponse,
)
from cairn_api.auth.permissions import Permission, has_permission
from cairn_api.config import Settings
from cairn_api.connectors.credentials import read_secret
from cairn_api.db.connector_models import SourceConnection
from cairn_api.db.models import Membership
from cairn_api.slack import channels as channel_selection
from cairn_api.slack import oauth
from cairn_api.slack.oauth import (
    HttpSlackApi,
    SlackApi,
    SlackInstallError,
    SlackInstallFailure,
)

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/workspaces", tags=["slack"])

#: The callback. No workspace in the path, because the URL is registered with
#: Slack once and must match the exchange request byte for byte.
callback_router = APIRouter(prefix="/integrations/slack", tags=["slack"])


def slack_api(settings: SettingsDep) -> SlackApi:
    """The Slack client for this request.

    A dependency rather than a module global, which is what makes "no unit test
    calls Slack" true by construction: a test overrides this one function and
    every route in the file is served by the double. Nothing patches a module
    attribute, so nothing can forget to put it back.

    Constructed per request. A pooled client would be faster and would also mean
    an ``httpx.AsyncClient`` owned by app state, closed on shutdown, and leaked
    by every test that builds an app — for a connector whose calls are measured
    in a handful per workspace per day.

    Raises:
        ProblemDetailError: 503 when Slack is not configured on this deployment.
            An operator's problem, and it must not read as "Slack said no".
    """
    try:
        return HttpSlackApi(
            client_id=settings.slack_client_id,
            client_secret=settings.slack_client_secret.get_secret_value(),
        )
    except SlackInstallError as error:
        raise _problem(error, status.HTTP_503_SERVICE_UNAVAILABLE) from error


SlackApiDep = Annotated[SlackApi, Depends(slack_api)]


def _problem(error: SlackInstallError, status_code: int) -> ProblemDetailError:
    """Render a Slack failure as a problem document.

    Carries our failure code and the bounded category, never Slack's words. The
    category is included so a client can behave differently for "wait" and "ask
    an admin" without parsing prose, and so the value a customer sees is the same
    one staff diagnostics show — two screens describing one fault in one
    vocabulary.
    """
    return ProblemDetailError(
        status_code=status_code,
        title="Slack could not be connected",
        detail=error.detail,
        problem_type=f"slack-{error.failure.value.replace('_', '-')}",
        category=error.category.value,
    )


@router.post(
    "/{workspace_id}/integrations/slack/install",
    response_model=SlackInstallResponse,
    summary="Begin connecting a Slack workspace",
    responses={
        403: {"description": "Requires permission to connect integrations."},
        503: {"description": "Slack is not configured on this deployment."},
    },
)
async def begin_install(
    context: Annotated[WorkspaceContext, Depends(requires(Permission.INTEGRATIONS_CONNECT))],
    db: PlatformDb,
    settings: SettingsDep,
) -> SlackInstallResponse:
    """Issue a one-time state and return the authorise URL.

    Returns the URL rather than redirecting. The caller is a browser application
    doing this from a settings screen, and a 302 out of an XHR is either followed
    invisibly or blocked — neither of which lets the interface warn about the
    ``/invite`` step before the customer is standing on Slack's consent screen.

    Runs on the platform connection because ``slack_oauth_states`` is
    deliberately unreachable from the application role: the callback has to read
    the row with no tenant context to scope to, so every statement against that
    table is platform-side and the grant set says so.
    """
    if not settings.slack_client_id:
        # Checked before the state is written. Issuing a nonce and then failing
        # to build a URL would leave a live install state behind for an install
        # that could never start.
        raise _problem(
            SlackInstallError(
                SlackInstallFailure.NOT_CONFIGURED,
                "Slack is not configured on this deployment.",
            ),
            status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    nonce, expires_at = await oauth.issue_state(
        db, tenant_id=context.tenant_id, user_id=context.user.id
    )
    await db.commit()

    await logger.ainfo(
        "slack.install_started",
        tenant_id=str(context.tenant_id),
        started_by=str(context.user.id),
        # The nonce is absent on purpose. A log line carrying it is a log line
        # from which somebody can complete an install a workspace admin started.
    )

    return SlackInstallResponse(
        authorize_url=oauth.build_authorize_url(settings, state=nonce),
        expires_at=expires_at,
        requested_scopes=list(oauth.REQUIRED_BOT_SCOPES),
        notice=channel_selection.BOT_INVITE_NOTICE,
    )


@callback_router.get(
    "/callback",
    summary="Finish connecting a Slack workspace",
    response_class=RedirectResponse,
    responses={303: {"description": "Back to the workspace's integration settings."}},
)
async def finish_install(
    request: Request,
    caller: CurrentUser,
    db: PlatformDb,
    settings: SettingsDep,
    api: SlackApiDep,
    code: Annotated[str | None, Query()] = None,
    state: Annotated[str | None, Query()] = None,
    error: Annotated[str | None, Query()] = None,
) -> RedirectResponse:
    """Where Slack sends the customer back.

    **Any ``error`` parameter is a failed install.** Slack's documentation does
    not state verbatim which value comes back when somebody presses Cancel, so
    this does not compare against the literal ``access_denied`` — an equality
    check that missed would fall through to "exchange the code" with no code, and
    the customer would see a parse failure instead of "you declined". Presence is
    the condition; the value is read for categorisation and then discarded.

    The order of the checks is the security property. The state is claimed —
    atomically, single-use — *before* anything is exchanged, so a replayed
    callback fails on the second attempt whether or not the first one worked.
    Then the caller is proved to still be a member of the state's workspace with
    permission to connect, so a leaked state cannot be redeemed by anyone else.
    Only then is the code sent to Slack.

    Redirects rather than returning JSON, because the thing following this URL is
    a browser mid-navigation, and the destination is built from
    ``public_app_url`` rather than from the request — the same rule as
    verification links, for the same reason.
    """
    if error is not None:
        # Read only to choose a category; never stored, logged or returned.
        failure = oauth.failure_for_slack_error(error)
        return _back(settings, failure=failure)

    if state is None or code is None:
        return _back(settings, failure=SlackInstallFailure.STATE_REJECTED)

    try:
        claimed = await oauth.consume_state(db, state=state, user_id=caller.user.id)
        # Committed immediately. If the exchange below fails or the process dies,
        # the state must stay consumed — "retry until it works" is
        # indistinguishable from a replay, and single-use is the property that
        # separates them.
        await db.commit()
    except SlackInstallError as failure_error:
        return _back(settings, failure=failure_error.failure)

    # Read off the row now, while it is still loaded. A `rollback()` below expires
    # every instance in the session regardless of `expire_on_commit`, so touching
    # `claimed.tenant_id` afterwards issues a lazy SELECT from a synchronous
    # attribute hook — which under asyncpg raises `MissingGreenlet` from inside an
    # exception handler, turning a handled Slack failure into a 500.
    tenant_id = claimed.tenant_id

    membership = await db.scalar(
        select(Membership).where(
            Membership.tenant_id == tenant_id,
            Membership.user_id == caller.user.id,
        )
    )
    if membership is None or not has_permission(membership.role, Permission.INTEGRATIONS_CONNECT):
        # Re-checked at the callback rather than trusted from the start. Minutes
        # passed, and in those minutes the person may have been removed from the
        # workspace or demoted — an install that completes on a permission that
        # no longer exists is one nobody currently authorised.
        await logger.awarning(
            "slack.install_rejected",
            tenant_id=str(tenant_id),
            reason=SlackInstallFailure.STATE_REJECTED.value,
        )
        return _back(settings, failure=SlackInstallFailure.STATE_REJECTED)

    try:
        grant = await api.exchange_code(code=code, redirect_uri=settings.slack_redirect_uri)
        await oauth.record_installation(
            db, tenant_id=tenant_id, user_id=caller.user.id, grant=grant
        )
    except SlackInstallError as failure_error:
        # Rolled back explicitly. `record_installation` writes a connection and
        # a credential before scope verification could conceivably be moved
        # later by a well-meaning edit; leaving a half-written connection behind
        # would be a workspace that reads as connected with no usable token.
        await db.rollback()
        await logger.awarning(
            "slack.install_failed",
            tenant_id=str(tenant_id),
            reason=failure_error.failure.value,
            category=failure_error.category.value,
        )
        return _back(settings, failure=failure_error.failure)

    await db.commit()
    _ = request  # The destination is built from settings, never from this.
    return _back(settings, failure=None)


def _back(settings: Settings, *, failure: SlackInstallFailure | None) -> RedirectResponse:
    """Send the browser back to the integrations screen with a bounded outcome.

    Every value in the query string is one of ours: a `SlackInstallFailure` and a
    `ConnectorErrorCategory`. Nothing Slack said reaches the URL bar, which is
    the one place a customer's error message is also in their browser history and
    in any referrer that follows.
    """
    destination = f"{settings.public_app_url.rstrip('/')}/settings/integrations"
    if failure is None:
        query = urlencode({"slack": "connected"})
    else:
        query = urlencode(
            {
                "slack": "failed",
                "reason": failure.value,
                "category": oauth.category_for(failure).value,
            }
        )
    # 303, not 302: the browser must issue a GET for the destination regardless
    # of how it arrived, and 302's method handling is famously implementation-
    # defined.
    return RedirectResponse(f"{destination}?{query}", status_code=status.HTTP_303_SEE_OTHER)


@router.get(
    "/{workspace_id}/integrations/slack/channels",
    response_model=SlackChannelListResponse,
    summary="List public channels CAIRN could read",
    responses={
        403: {"description": "Requires permission to connect integrations."},
        404: {"description": "No Slack workspace is connected."},
        502: {"description": "Slack could not be reached."},
    },
)
async def list_channels(
    context: Annotated[WorkspaceContext, Depends(requires(Permission.INTEGRATIONS_CONNECT))],
    db: TenantDb,
    api: SlackApiDep,
) -> SlackChannelListResponse:
    """The picker's contents: every non-archived public channel, and its state.

    Gated on `INTEGRATIONS_CONNECT` — Owner and Admin — rather than on plain
    membership. This is the one endpoint in the API that returns Slack channel
    names, and the people who may see the list are the people who may change what
    CAIRN reads. A Member gains nothing from a list they cannot act on.

    ``bot_is_member`` is carried through untouched because it is the field that
    makes the screen honest: selecting a channel the app has not been invited to
    produces a permission that delivers nothing, forever, with no error anywhere.
    """
    connection = await _connected_or_404(db, context)
    token = read_secret(connection)
    if token is None:
        # A connected connection with no credential. Reachable if a disconnect
        # were interrupted between clearing the token and setting the state, and
        # the honest answer is "not connected" rather than an empty picker that
        # implies the workspace has no channels.
        raise _not_connected()

    try:
        available = await channel_selection.available_channels(
            api, connection_id=connection.id, token=token
        )
    except SlackInstallError as error:
        raise _problem(error, status.HTTP_502_BAD_GATEWAY) from error

    selected = await channel_selection.selected_channel_ids(db, connection_id=connection.id)

    return SlackChannelListResponse(
        channels=[
            SlackChannelResponse(
                id=item.id,
                name=item.name,
                bot_is_member=item.bot_is_member,
                selected=item.id in selected,
            )
            for item in available
        ],
        notice=channel_selection.BOT_INVITE_NOTICE,
    )


@router.put(
    "/{workspace_id}/integrations/slack/channels",
    response_model=SlackChannelSelectionResponse,
    summary="Choose which public channels CAIRN may process",
    responses={
        403: {"description": "Requires permission to connect integrations."},
        404: {"description": "No Slack workspace is connected."},
        422: {"description": "A value was not a Slack channel ID."},
    },
)
async def save_channels(
    body: SlackChannelSelectionRequest,
    context: Annotated[WorkspaceContext, Depends(requires(Permission.INTEGRATIONS_CONNECT))],
    db: TenantDb,
) -> SlackChannelSelectionResponse:
    """Replace the selection with exactly these channels.

    ``PUT`` rather than ``POST``, and a replace rather than a merge, because the
    body is the full state of a set of checkboxes. A merge would make unchecking
    a box do nothing — and the box being unchecked is somebody withdrawing
    permission for CAIRN to read a conversation, which is the single operation on
    this endpoint that must not silently fail.

    An empty list is valid and means "process nothing", which is also the state a
    freshly connected workspace is in.

    Runs on the tenant-scoped session: the application role holds SELECT, INSERT
    and DELETE here precisely because these writes happen from inside a
    workspace, where the policy's WITH CHECK stops a row being written for
    anybody else.
    """
    connection = await _connected_or_404(db, context)

    try:
        saved = await channel_selection.save_selection(
            db, connection=connection, user_id=context.user.id, channel_ids=body.channel_ids
        )
    except channel_selection.SlackSelectionError as error:
        raise ProblemDetailError(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            title="That selection cannot be saved",
            detail=str(error),
            problem_type="slack-channel-selection-invalid",
        ) from error

    await db.commit()
    return SlackChannelSelectionResponse(
        channel_ids=list(saved), notice=channel_selection.BOT_INVITE_NOTICE
    )


@router.post(
    "/{workspace_id}/integrations/slack/disconnect",
    response_model=SlackDisconnectResponse,
    summary="Disconnect Slack and destroy the stored credential",
    responses={
        403: {"description": "Requires permission to disconnect integrations."},
        404: {"description": "No Slack workspace is connected."},
    },
)
async def disconnect_slack(
    context: Annotated[WorkspaceContext, Depends(requires(Permission.INTEGRATIONS_DISCONNECT))],
    db: PlatformDb,
) -> SlackDisconnectResponse:
    """Stop collecting, and drop the bot token.

    Both, in one call, with no option to do only the first. A disconnect that
    leaves the credential behind keeps CAIRN holding a live grant to read a
    customer's conversations after they asked it to stop — and from outside there
    is no way to tell the two apart, which is exactly why the response says which
    happened.

    Runs on the platform connection because the application role holds SELECT
    only on ``source_connections``.

    **The response tells the truth about retention.** Disconnecting stops new
    collection; it does not delete what was already recorded. Saying otherwise
    would be the shorter sentence and a false one, and a product whose deletion
    claims are approximate is one whose deletion claims are worthless.
    """
    connection = await _connected_or_404(db, context)

    await oauth.disconnect(connection)
    channel_selection.forget_channels(connection.id)
    await db.commit()

    await logger.ainfo(
        "slack.disconnected",
        tenant_id=str(context.tenant_id),
        disconnected_by=str(context.user.id),
    )

    return SlackDisconnectResponse(
        state=connection.state.value,
        disconnected_at=connection.disconnected_at or datetime.now(UTC),
        credential_cleared=read_secret(connection) is None,
        retention_notice=(
            "Slack will stop being collected from immediately, and the stored "
            "access token has been destroyed. What CAIRN already recorded from "
            "Slack is not deleted by disconnecting — the channel selection is "
            "kept too, so reconnecting restores it."
        ),
    )


async def _connected_or_404(db: AsyncSession, context: WorkspaceContext) -> SourceConnection:
    """This workspace's live Slack connection, or a 404.

    404 rather than 409 for a connection that exists but is disconnected. From
    the caller's side those are the same fact — there is no Slack here — and the
    distinction only matters to somebody probing whether a workspace once had
    one.
    """
    connection = await oauth.find_connection(db, tenant_id=context.tenant_id)
    if connection is None or not connection.is_active:
        raise _not_connected()
    return connection


def _not_connected() -> ProblemDetailError:
    return ProblemDetailError(
        status_code=status.HTTP_404_NOT_FOUND,
        title="Slack is not connected",
        detail="No Slack workspace is connected to this workspace.",
        problem_type="slack-not-connected",
    )


__all__ = ["callback_router", "router", "slack_api"]
