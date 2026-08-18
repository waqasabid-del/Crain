"""Connecting Google Meet — and nothing about choosing what to collect.

Three routes across two routers. Two live under ``/workspaces/{workspace_id}``
and are gated on a session, a membership and a permission. The third cannot:
Google registers **one** redirect URI per OAuth client, character for character,
so it can carry no workspace id and ``CurrentMembership`` would reject the
request before the handler ran. What identifies the workspace on the way back is
the ``state`` parameter, which is precisely why it is server-side, single-use and
bound to the person who started the install.

**There is no space picker here, and that absence is the design.** The Google
Chat router has one because an admin decides which conversations CAIRN may read.
Meet has no equivalent surface and must not grow one: what CAIRN may watch is
decided one meeting at a time by the people who will be in it, through Step 35's
capture requests, and every subscription is created from a `CollectionPermit`
that only unanimous consent produces. An admin-facing "choose which meetings"
screen would be one person granting a permission that is not theirs to give.

So connecting does exactly two things: it stores a refresh token, and it makes it
*possible* for a later, consent-gated operation to create a subscription. Until
some meeting's every participant has agreed, a connected Google Meet account
causes precisely zero collection, and the install response says so.

**The Pub/Sub receiver is not in this file and is not in the client.** It lives in
``api/routers/gmeet_push.py``, is unauthenticated by necessity, and is verified by
a Google-signed token rather than by a session.

**No route here returns a token, a Google error string, a meeting reference or a
joining code.** Failures arrive as a `GoogleMeetInstallFailure` — our vocabulary
— and a `ConnectorErrorCategory`, the closed set the rest of the product already
reports on.

Every workspace-scoped route runs on the **platform** connection, for the same
mechanical reason the Chat router does: an access token is obtained by
refreshing, a failed refresh writes onto ``source_connections`` where the
application role holds SELECT only, and tearing down subscriptions writes
``google_meet_subscriptions`` where it also holds SELECT only. Both grants are
deliberate, so the writes belong platform-side, and every statement here carries
its tenant predicate explicitly rather than relying on a session scope it does
not have.
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
from cairn_api.api.schemas import GoogleMeetDisconnectResponse, GoogleMeetInstallResponse
from cairn_api.auth.permissions import Permission, has_permission
from cairn_api.config import Settings
from cairn_api.connectors.credentials import read_secret
from cairn_api.db.connector_models import SourceConnection
from cairn_api.db.models import Membership
from cairn_api.gmeet import oauth
from cairn_api.gmeet import subscriptions as subscription_engine
from cairn_api.gmeet.oauth import (
    GoogleMeetApi,
    GoogleMeetInstallError,
    GoogleMeetInstallFailure,
    HttpGoogleMeetApi,
)

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/workspaces", tags=["google-meet"])

#: The callback. No workspace in the path, because Google registers one redirect
#: URI per OAuth client and it must match the exchange request byte for byte.
callback_router = APIRouter(prefix="/integrations/google-meet", tags=["google-meet"])

#: Where the browser lands after the callback, relative to `public_app_url`.
RETURN_PATH = "/admin"

#: The bounded outcomes the callback may report, and the whole vocabulary of the
#: query string it redirects with. Nothing Google said reaches the URL bar — which
#: is the one place a customer's error message is also in their browser history
#: and in any referrer that follows.
OUTCOME_CONNECTED = "connected"
OUTCOME_DENIED = "denied"
OUTCOME_ERROR = "error"

#: What connecting actually grants, in one sentence, returned before the customer
#: reaches Google's consent screen.
#:
#: Written here rather than in the frontend because it is a statement about what
#: the backend does, and a claim about collection that lives only in a React
#: component is a claim nothing keeps true.
CONNECT_NOTICE = (
    "Connecting Google Meet does not let CAIRN collect anything on its own. "
    "CAIRN watches a meeting only after every person invited to it has agreed, "
    "one meeting at a time, and even then it only records that the meeting "
    "platform produced a transcript — it does not join meetings, retrieve "
    "transcripts, or track who attended."
)

#: The failures that mean "a human said no" rather than "something broke". Kept as
#: a set rather than tested inline so the two cases stay one decision.
_DENIALS = frozenset(
    {
        GoogleMeetInstallFailure.DECLINED,
        GoogleMeetInstallFailure.ADMIN_POLICY_ENFORCED,
    }
)


def google_meet_api(settings: SettingsDep) -> GoogleMeetApi:
    """The Google OAuth client for this request.

    A dependency rather than a module global, which is what makes "no unit test
    calls Google" true by construction: a test overrides this one function and
    every route in the file is served by the double.

    Raises:
        ProblemDetailError: 503 when Google Meet is not configured on this
            deployment. An operator's problem, and it must not read as "Google
            said no".
    """
    try:
        return HttpGoogleMeetApi(
            client_id=settings.google_meet_client_id,
            client_secret=settings.google_meet_client_secret,
        )
    except GoogleMeetInstallError as error:
        raise _problem(error, status.HTTP_503_SERVICE_UNAVAILABLE) from error


def subscription_client(settings: SettingsDep) -> subscription_engine.SubscriptionClient | None:
    """The Workspace Events client, or ``None`` on a deployment with no topic.

    ``None`` rather than a 503, because a missing topic must not stop somebody
    disconnecting. The local rows are marked first in either case, which is what
    actually stops collection.
    """
    return subscription_engine.build_client(settings)


GoogleMeetApiDep = Annotated[GoogleMeetApi, Depends(google_meet_api)]
SubscriptionClientDep = Annotated[
    subscription_engine.SubscriptionClient | None, Depends(subscription_client)
]


def _problem(error: GoogleMeetInstallError, status_code: int) -> ProblemDetailError:
    """Render a Google Meet failure as a problem document.

    Carries our failure code and the bounded category, never Google's words. The
    category is included so a client can behave differently for "wait" and "ask an
    admin" without parsing prose, and so the value a customer sees is the same one
    staff diagnostics show.
    """
    return ProblemDetailError(
        status_code=status_code,
        title="Google Meet could not be connected",
        detail=error.detail,
        problem_type=f"google-meet-{error.failure.value.replace('_', '-')}",
        category=error.category.value,
    )


@router.post(
    "/{workspace_id}/integrations/google-meet/install",
    response_model=GoogleMeetInstallResponse,
    summary="Begin connecting a Google Meet account",
    responses={
        403: {"description": "Requires permission to connect integrations."},
        503: {"description": "Google Meet is not configured on this deployment."},
    },
)
async def begin_install(
    context: Annotated[WorkspaceContext, Depends(requires(Permission.INTEGRATIONS_CONNECT))],
    db: PlatformDb,
    settings: SettingsDep,
) -> GoogleMeetInstallResponse:
    """Issue a one-time state with its PKCE verifier, and return the authorise URL.

    Returns the URL rather than redirecting. The caller is a browser application
    doing this from an admin screen, and a 302 out of an XHR is either followed
    invisibly or blocked — neither of which lets the interface state
    :data:`CONNECT_NOTICE` before the customer is standing on Google's consent
    screen.

    Runs on the platform connection because ``google_meet_oauth_states`` is
    deliberately unreachable from the application role: the callback has to read
    the row with no tenant context to scope to, so every statement against that
    table is platform-side and the grant set says so.
    """
    if not settings.google_meet_client_id:
        # Checked before the state is written. Issuing a nonce and then failing to
        # build a URL would leave a live install state behind for an install that
        # could never start.
        raise _problem(
            GoogleMeetInstallError(
                GoogleMeetInstallFailure.NOT_CONFIGURED,
                "Google Meet is not configured on this deployment.",
            ),
            status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    nonce, verifier, expires_at = await oauth.issue_state(
        db, tenant_id=context.tenant_id, user_id=context.user.id
    )
    await db.commit()

    await logger.ainfo(
        "gmeet.install_started",
        tenant_id=str(context.tenant_id),
        started_by=str(context.user.id),
        # Neither the nonce nor the verifier is present, on purpose. A log line
        # carrying them is a log line from which somebody can complete an install
        # a workspace admin started.
    )

    return GoogleMeetInstallResponse(
        authorize_url=oauth.build_authorize_url(settings, state=nonce, code_verifier=verifier),
        expires_at=expires_at,
        notice=CONNECT_NOTICE,
    )


@callback_router.get(
    "/callback",
    summary="Finish connecting a Google Meet account",
    response_class=RedirectResponse,
    responses={303: {"description": "Back to the workspace's admin screen."}},
)
async def finish_install(
    request: Request,
    caller: CurrentUser,
    db: PlatformDb,
    settings: SettingsDep,
    api: GoogleMeetApiDep,
    code: Annotated[str | None, Query()] = None,
    state: Annotated[str | None, Query()] = None,
    error: Annotated[str | None, Query()] = None,
) -> RedirectResponse:
    """Where Google sends the customer back.

    **Any ``error`` parameter is a failed install.** The callback branches on the
    *presence* of the parameter, never on the literal ``access_denied``: an
    equality check that missed would fall through to "exchange the code" with no
    code, and the customer would see a parse failure instead of "you declined".

    The order of the checks is the security property. The state is claimed —
    atomically, single-use — *before* anything is exchanged, so a replayed
    callback fails on the second attempt whether or not the first one worked.

    **The workspace comes off the stored row and never from the request.** There
    is no ``workspace_id`` parameter on this route to trust, and adding one would
    let anybody who obtained a state bind an authorisation to a workspace of their
    choosing.

    Then the caller is proved to **still** be a member of that workspace **with
    permission to connect**: minutes passed, and in those minutes the person may
    have been removed or demoted, and an install that completes on a permission
    that no longer exists is one nobody currently authorised. Only then is the
    code sent to Google.
    """
    if error is not None:
        failure = oauth.failure_for_google_error(error)
        return _back(settings, failure=failure)

    if state is None or code is None:
        return _back(settings, failure=GoogleMeetInstallFailure.STATE_REJECTED)

    try:
        claimed = await oauth.consume_state(db, state=state, user_id=caller.user.id)
        # Committed immediately. If the exchange below fails or the process dies,
        # the state must stay consumed — "retry the callback until it works" is
        # indistinguishable from a replay, and single-use is what separates them.
        await db.commit()
    except GoogleMeetInstallError as failure_error:
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
            "gmeet.install_rejected",
            tenant_id=str(tenant_id),
            reason=GoogleMeetInstallFailure.STATE_REJECTED.value,
        )
        return _back(settings, failure=GoogleMeetInstallFailure.STATE_REJECTED)

    try:
        grant = await api.exchange_code(
            code=code,
            redirect_uri=settings.google_meet_redirect_uri,
            code_verifier=code_verifier,
        )
        await oauth.record_installation(
            db, settings=settings, tenant_id=tenant_id, user_id=caller.user.id, grant=grant
        )
    except GoogleMeetInstallError as failure_error:
        # Rolled back explicitly. `record_installation` writes a connection and a
        # credential; leaving a half-written connection behind would be a
        # workspace that reads as connected with no usable token.
        await db.rollback()
        await logger.awarning(
            "gmeet.install_failed",
            tenant_id=str(tenant_id),
            reason=failure_error.failure.value,
            category=failure_error.category.value,
        )
        return _back(settings, failure=failure_error.failure)

    await db.commit()
    _ = request  # The destination is built from settings, never from this.
    return _back(settings, failure=None)


def _back(settings: Settings, *, failure: GoogleMeetInstallFailure | None) -> RedirectResponse:
    """Send the browser back to the admin screen with a bounded outcome.

    Three values, and only three. A failure code in a URL is a failure code in
    browser history, in a referrer and in any analytics the customer's own site
    runs — and the actionable half of it is already on the connection, behind the
    session, where the admin screen reads it.
    """
    destination = f"{settings.public_app_url.rstrip('/')}{RETURN_PATH}"
    if failure is None:
        outcome = OUTCOME_CONNECTED
    elif failure in _DENIALS:
        outcome = OUTCOME_DENIED
    else:
        outcome = OUTCOME_ERROR
    query = urlencode({"googleMeet": outcome})
    # 303, not 302: the browser must issue a GET for the destination regardless of
    # how it arrived, and 302's method handling is famously
    # implementation-defined.
    return RedirectResponse(f"{destination}?{query}", status_code=status.HTTP_303_SEE_OTHER)


@router.post(
    "/{workspace_id}/integrations/google-meet/disconnect",
    response_model=GoogleMeetDisconnectResponse,
    summary="Disconnect Google Meet and destroy the stored credential",
    responses={
        403: {"description": "Requires permission to disconnect integrations."},
        404: {"description": "No Google Meet account is connected."},
    },
)
async def disconnect_google_meet(
    context: Annotated[WorkspaceContext, Depends(requires(Permission.INTEGRATIONS_DISCONNECT))],
    db: PlatformDb,
    client: SubscriptionClientDep,
) -> GoogleMeetDisconnectResponse:
    """Stop watching, tear the leases down, and drop the refresh token.

    All three, in one call, with no option to do only the first. A disconnect that
    leaves the credential behind keeps CAIRN holding a standing grant after the
    customer asked it to stop, and from outside there is no way to tell the two
    apart — which is exactly why the response says which happened.

    The subscriptions are removed **before** the credential is destroyed, because
    deleting a lease at Google needs a token. Every meeting is blocked locally
    whether or not that succeeds: `remove_all_subscriptions` marks each row before
    it calls Google and does not stop on an error, and the receiver refuses a
    delivery whose connection is not active. A lease that survives at Google
    therefore delivers into a workspace that will not record it, and lapses on its
    own because nothing renews it.

    **The response tells the truth about retention.** Disconnecting stops new
    collection; it does not delete what was already recorded.
    """
    connection = await _connected_or_404(db, context)

    outcomes: tuple[subscription_engine.RemovalOutcome, ...] = ()
    if client is not None:
        outcomes = await subscription_engine.remove_all_subscriptions(db, client, connection)

    await oauth.disconnect(connection)
    await db.commit()

    await logger.ainfo(
        "gmeet.disconnected",
        tenant_id=str(context.tenant_id),
        disconnected_by=str(context.user.id),
        count=len(outcomes),
    )

    return GoogleMeetDisconnectResponse(
        state=connection.state.value,
        disconnected_at=connection.disconnected_at or datetime.now(UTC),
        subscriptions_removed=len(outcomes),
        credential_cleared=read_secret(connection) is None,
        retention_notice=(
            "Google Meet will stop being watched immediately, the event "
            "subscriptions have been torn down, and the stored refresh token has "
            "been destroyed. What CAIRN already recorded is not deleted by "
            "disconnecting, and the consent decisions people made about "
            "individual meetings are kept — reconnecting does not re-start "
            "anything on its own."
        ),
    )


async def _connected_or_404(db: AsyncSession, context: WorkspaceContext) -> SourceConnection:
    """This workspace's live Google Meet connection, or a 404.

    404 rather than 409 for a connection that exists but is disconnected. From the
    caller's side those are the same fact — there is no Google Meet here — and the
    distinction only matters to somebody probing whether a workspace once had one.
    """
    connection = await oauth.find_connection(db, tenant_id=context.tenant_id)
    if connection is None or not connection.is_active:
        raise _not_connected()
    return connection


def _not_connected() -> ProblemDetailError:
    return ProblemDetailError(
        status_code=status.HTTP_404_NOT_FOUND,
        title="Google Meet is not connected",
        detail="No Google Meet account is connected to this workspace.",
        problem_type="google-meet-not-connected",
    )


__all__ = ["callback_router", "google_meet_api", "router", "subscription_client"]
