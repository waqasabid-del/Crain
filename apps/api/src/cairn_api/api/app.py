"""The FastAPI application.

A factory rather than a module-level `app = FastAPI()`. Tests need an
independent instance per case — one with its own rate limiter, so counts do not
leak between tests — and a module-level singleton makes that impossible without
reaching into private state.

**Startup verifies its own assumptions.** `preflight` confirms the application
role genuinely lacks `BYPASSRLS` before the service accepts traffic. That check
existed for two audit rounds and was never called, which meant the property
every isolation guarantee rests on was asserted in tests and unverified in
production. A misconfigured role is not a degraded service — it is one where
row-level security silently does nothing, so the correct response is to refuse
to start.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from cairn_api.api.errors import register_exception_handlers
from cairn_api.api.middleware import (
    AccessLogMiddleware,
    CsrfOriginMiddleware,
    RequestContextMiddleware,
    SecurityHeadersMiddleware,
)
from cairn_api.api.ratelimit import InMemoryRateLimiter, PostgresRateLimiter, RateLimiter
from cairn_api.api.routers import (
    admin,
    auth,
    facts,
    gchat,
    gchat_push,
    gmeet,
    gmeet_push,
    health,
    identities,
    internal,
    me,
    meetings,
    onboarding,
    slack,
    slack_webhooks,
    support,
    trust,
    workspaces,
)
from cairn_api.config import Settings, get_settings
from cairn_api.connectors.credentials import build_cipher
from cairn_api.db.preflight import run_preflight_checks
from cairn_api.db.session import dispose_engines, platform_session
from cairn_api.email import build_sender
from cairn_api.github import handlers as github_handlers
from cairn_api.github import jobs as github_jobs
from cairn_api.github import webhooks
from cairn_api.github.backfill import BACKFILL_JOB
from cairn_api.github.handlers import GITHUB_DELIVERY_JOB
from cairn_api.jobs.factory import build_queue
from cairn_api.jobs.runner import registry as job_registry
from cairn_api.logging import configure_logging
from cairn_api.pipeline import jobs as pipeline_jobs
from cairn_api.pipeline.jobs import UNDERSTAND_JOB
from cairn_api.telemetry.startup import check_telemetry

logger = structlog.get_logger(__name__)

#: Every route lives under a version prefix from the first commit.
#:
#: Adding one later means either breaking existing clients or maintaining
#: unversioned aliases forever. The cost now is six characters.
API_PREFIX = "/v1"

DESCRIPTION = """
CAIRN's HTTP API.

Errors are RFC 9457 problem documents (`application/problem+json`) with a stable
`type` URI to branch on. Authentication is a `HttpOnly` session cookie issued by
`POST /v1/auth/login`; browser clients must send credentials and never need to
read the cookie.
""".strip()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Verify the environment on the way up, release connections on the way down."""
    settings: Settings = app.state.settings

    if settings.is_deployed:
        # Every deployed environment verifies that the application role
        # genuinely lacks BYPASSRLS before serving traffic. Skipped for local
        # and automated-test runs, where `test_preflight.py` asserts the same
        # property directly against deliberately misconfigured roles — a
        # stronger check than a startup call that only exercises the happy path.
        await run_preflight_checks()

    # Before serving, not after: an environment that cannot export what it
    # records is one where the first incident has no trace.
    check_telemetry(settings)

    # Same reasoning, higher stakes. Without this the missing key surfaces at
    # the first connector write — which is the moment a customer is handing
    # CAIRN an access token, and the worst possible time to discover there is
    # nowhere safe to put it. Building the cipher here turns that into a
    # refusal to start.
    build_cipher(settings)

    await logger.ainfo(
        "api_started",
        environment=settings.environment,
        cors_origins=list(settings.cors_allowed_origins),
    )

    yield

    await dispose_engines()
    await logger.ainfo("api_stopped")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build an application instance."""
    settings = settings or get_settings()
    configure_logging(settings)

    app = FastAPI(
        title="CAIRN API",
        description=DESCRIPTION,
        version="0.1.0",
        lifespan=lifespan,
        # Interactive docs in deployed environments would publish the full
        # surface, including every field name and error shape, to anyone who
        # finds the URL. The schema is generated into the repository for the
        # TypeScript client, so nothing is lost by not serving it.
        docs_url="/docs" if settings.environment == "local" else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.environment == "local" else None,
    )

    app.state.settings = settings
    app.state.rate_limiter = _build_rate_limiter(settings)
    # The API publishes; workers consume. Built here rather than looked up
    # per-request because a Pub/Sub client owns gRPC channels and background
    # threads, and constructing one per request would leak both.
    app.state.queue = build_queue(settings)
    app.state.email_sender = build_sender(settings)

    # Registered so the API and the worker agree on what a job type means. The
    # API never runs handlers, but a job type it can publish and no worker can
    # resolve is a message that dead-letters as "unknown", so the two lists must
    # not drift — and a test asserts every published type has a handler.
    #
    # Guarded per type rather than wrapped around one call: the registry is
    # process-wide and rejects a duplicate registration, so a second
    # `create_app` in the same test session must not re-register what the first
    # already did.
    if GITHUB_DELIVERY_JOB not in job_registry.registered_types():
        github_handlers.register(queue=app.state.queue)
    if BACKFILL_JOB not in job_registry.registered_types():
        github_jobs.register(app.state.queue)
    if UNDERSTAND_JOB not in job_registry.registered_types():
        pipeline_jobs.register()

    register_exception_handlers(app)
    _install_middleware(app, settings)

    app.include_router(health.router)
    app.include_router(auth.router, prefix=API_PREFIX)
    app.include_router(workspaces.router, prefix=API_PREFIX)
    app.include_router(workspaces.invitations_router, prefix=API_PREFIX)
    # Mounted under the same `/workspaces/{workspace_id}` prefix as the router
    # above, and kept in its own module: what the pipeline produced is a
    # different subject from who may configure the workspace, and one file
    # answering both invites a read endpoint acquiring a permission check
    # written for a mutation.
    app.include_router(facts.router, prefix=API_PREFIX)
    app.include_router(onboarding.router, prefix=API_PREFIX)
    app.include_router(me.router, prefix=API_PREFIX)
    # Its own module rather than more of `me.py`, and mounted under the same
    # `/workspaces/{workspace_id}` prefix. Cross-source identity is where the
    # self-only rule is load-bearing — every route there resolves its person
    # from the session and none takes a subject — and keeping it in one file
    # means that property is checkable by reading one file rather than by
    # trusting that a later addition to a longer one kept the pattern.
    app.include_router(identities.router, prefix=API_PREFIX)
    # Its own module, under the same `/workspaces/{workspace_id}` prefix, for the
    # reason `identities` is: the self-only rule is load-bearing here. Two of its
    # routes take no subject at all and are the only places a consent decision is
    # written, so keeping them in one file means "no administrator can consent
    # for anybody" is a property a reviewer checks by reading one file rather
    # than by trusting that a later addition to a longer one kept the pattern.
    app.include_router(meetings.router, prefix=API_PREFIX)
    app.include_router(admin.router, prefix=API_PREFIX)
    app.include_router(trust.router, prefix=API_PREFIX)
    app.include_router(support.router, prefix=API_PREFIX)
    app.include_router(internal.router, prefix=API_PREFIX)
    # Two routers, because the Slack OAuth callback URL is registered with Slack
    # once and therefore cannot carry a `{workspace_id}` path segment. The
    # workspace-scoped half is gated exactly like the GitHub connect endpoint;
    # the callback identifies its workspace from the single-use state instead.
    app.include_router(slack.router, prefix=API_PREFIX)
    app.include_router(slack.callback_router, prefix=API_PREFIX)
    # Two routers again, and for a stricter version of the same reason: Google
    # registers exactly one redirect URI per OAuth client, so the callback cannot
    # carry a `{workspace_id}`. The single-use state identifies the workspace.
    app.include_router(gchat.router, prefix=API_PREFIX)
    app.include_router(gchat.callback_router, prefix=API_PREFIX)
    # And again for Google Meet, which has its **own** OAuth client rather than
    # sharing Chat's — both connectors verify the granted scope set by equality,
    # so one shared client makes each reject the other's grant. There is
    # deliberately no picker router here: what CAIRN may watch is decided per
    # meeting by the people in it, not by an admin on a settings screen.
    app.include_router(gmeet.router, prefix=API_PREFIX)
    app.include_router(gmeet.callback_router, prefix=API_PREFIX)
    app.include_router(webhooks.router, prefix=API_PREFIX)
    # Mounts the Slack event endpoint and registers the job it publishes, in one
    # call: a router without its handler publishes a job type no worker can
    # resolve, which dead-letters as "unknown".
    slack_webhooks.install(app, prefix=API_PREFIX)
    # Same one-call pattern, for the same reason: the Google Chat Pub/Sub push
    # receiver and the job it publishes are mounted and registered together.
    gchat_push.install(app, prefix=API_PREFIX)
    # The Meet receiver mounts no job type, deliberately: Step 36A records that a
    # transcript exists and publishes no work that could go and fetch it.
    gmeet_push.install(app, prefix=API_PREFIX)

    return app


def _build_rate_limiter(settings: Settings) -> RateLimiter:
    """Choose a limiter backend.

    Shared storage everywhere it matters. The in-process limiter is per-instance,
    so on Cloud Run the effective limit is the configured one multiplied by the
    instance count, and it resets on every deploy — a real weakening, and one an
    attacker benefits from without needing to know about it.

    The in-memory limiter is kept for local development and tests, where a
    database round trip per login would slow the suite for no signal, and where
    there is only one instance anyway. It is not a fallback: a deployed
    environment gets the shared store, full stop.
    """
    if settings.is_deployed:
        return PostgresRateLimiter(platform_session)
    return InMemoryRateLimiter()


def _install_middleware(app: FastAPI, settings: Settings) -> None:
    """Install middleware in the order it must run.

    Starlette applies middleware in reverse order of registration, so the *last*
    one added is the outermost. The registrations below are therefore written
    inner-to-outer, and the ordering is load-bearing:

    - **Request context outermost.** Everything else — the access log, every
      exception handler, every problem document — reads the request ID. Added
      last so it wraps them all; anything above it logs an unidentified request.
    - **CORS above the CSRF check.** A rejected preflight must still carry CORS
      headers, or the browser reports an opaque network error instead of the 403
      that explains it.
    - **Security headers innermost of the three**, so they apply to responses
      produced by the handlers below them, including error responses.
    """
    allowed = frozenset(settings.cors_allowed_origins)

    app.add_middleware(SecurityHeadersMiddleware, hsts=settings.is_deployed)
    app.add_middleware(CsrfOriginMiddleware, allowed_origins=allowed)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_allowed_origins),
        # Required for the session cookie to be sent at all. It is also exactly
        # why `allow_origins` can never be a wildcard — the browser refuses that
        # combination, and the natural "fix" is to stop sending credentials.
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "X-Request-ID"],
        expose_headers=["X-Request-ID", "Retry-After"],
        max_age=600,
    )
    app.add_middleware(AccessLogMiddleware)
    app.add_middleware(RequestContextMiddleware)
