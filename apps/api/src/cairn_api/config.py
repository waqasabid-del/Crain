"""Application settings.

Loaded from the environment, validated at startup. Failing loudly on a missing
or malformed setting is deliberate: a service that boots with a half-configured
database URL fails later, in a harder place to diagnose.

No secret ever has a production-usable default. The local database password is
the sole exception, and it only reaches a container that never holds real data
(md/17-engineering-standards.md §9.1).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal, Self

from pydantic import Field, PostgresDsn, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

#: Public in this repository. Any deployed environment that sees this value in
#: a connection string has not had its secrets injected.
LOCAL_DEV_PASSWORD = "cairn_local_dev"  # noqa: S105

Environment = Literal["local", "test", "staging", "production"]

#: Which broker backs the job queue.
#:
#: 'postgres' is the scheduling backend: durable, and the only one that can
#: enforce priority and per-tenant fairness across every worker, because it is
#: the only one where all the workers can see the same queue.
QueueBackend = Literal["memory", "pubsub", "postgres"]

#: How outbound email is delivered.
#:
#: "console" writes the message to the log so a developer can follow an
#: invitation link out of their terminal. A deployed environment refuses it:
#: invitations would reach nobody, and nothing about the request would say so.
EmailBackend = Literal["console", "smtp"]

#: Which model adapter the understanding pipeline uses.
#:
#: "scripted" is the deterministic provider the evaluation harness grades
#: against. It exists here so a local environment can produce real output
#: through the real pipeline instead of an empty product; a deployed
#: environment refuses to start on it.
ModelBackend = Literal["auto", "vertex", "scripted", "offline"]

#: Environments that never hold customer data and therefore may use the
#: development defaults below.
#:
#: ``test`` is on this list deliberately. It names the *automated test run* —
#: pytest against a throwaway container on localhost, in CI or on a laptop — not
#: a deployed test environment. Pre-production deployments are ``staging``,
#: which is guarded exactly like production.
#:
#: Worth stating because the name is genuinely ambiguous, and someone who reads
#: ``test`` as "our test server" and points it at real data would be outside
#: every check in this file.
NON_DEPLOYED_ENVIRONMENTS: frozenset[str] = frozenset({"local", "test"})

#: Name of the session cookie.
#:
#: A module constant rather than a setting. FastAPI needs the name at import
#: time to describe the parameter in the OpenAPI schema, so a per-environment
#: value would be read once at startup and ignored thereafter — a setting that
#: appears to work and does not. There is no scenario requiring it to differ.
SESSION_COOKIE_NAME = "cairn_session"


class Settings(BaseSettings):
    """Runtime configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="CAIRN_",
        extra="ignore",
    )

    environment: Environment = "local"

    database_url: PostgresDsn = Field(
        default=PostgresDsn("postgresql+asyncpg://cairn_app:cairn_local_dev@localhost:5432/cairn"),
        description=(
            "Application connection. Uses a NOSUPERUSER, NOBYPASSRLS role so that "
            "row-level security actually applies — RLS is silently inert for "
            "superusers regardless of FORCE."
        ),
    )

    platform_database_url: PostgresDsn = Field(
        default=PostgresDsn("postgresql+asyncpg://cairn:cairn_local_dev@localhost:5432/cairn"),
        description=(
            "Privileged connection for operations that legitimately precede any "
            "tenant context: signup, workspace creation, migrations. Deliberately "
            "separate so that reaching for it is a visible, greppable decision "
            "rather than something that happens by default."
        ),
    )

    #: Echo SQL to the log. Useful locally, unacceptable in production, where it
    #: would write customer data into log storage.
    database_echo: bool = False

    # -- HTTP -------------------------------------------------------------

    cors_allowed_origins: tuple[str, ...] = Field(
        default=("http://localhost:3000",),
        description=(
            "Origins permitted to call the API with credentials. An explicit "
            "list, never '*': the browser refuses a wildcard alongside "
            "credentialed requests, and a service that responded with one "
            "would be inviting any page on the internet to act as a signed-in "
            "user."
        ),
    )

    trusted_proxy_hops: int = Field(
        default=1,
        ge=0,
        le=8,
        description=(
            "How many proxies append to X-Forwarded-For in front of this "
            "service. The client address is read that many entries from the "
            "right. Wrong in either direction breaks per-address rate limiting: "
            "too low reads a proxy's address and collapses every caller into "
            "one bucket, too high reads a client-supplied value and hands an "
            "attacker a fresh bucket per request. Cloud Run alone is 1; behind "
            "an external HTTPS load balancer it is 2."
        ),
    )

    session_cookie_domain: str | None = Field(
        default=None,
        description=(
            "Domain for the session cookie. None means host-only, which is "
            "correct locally. In production the API and the app are separate "
            "hosts under one site, so this is set to the registrable domain "
            "(e.g. '.cairn.dev') for the cookie to reach both."
        ),
    )

    public_app_url: str = Field(
        default="http://localhost:3000",
        description=(
            "Base URL of the web app, used to build the links in outbound "
            "email. Never derived from the request: a verification link built "
            "from an attacker-supplied Host header sends the token to the "
            "attacker."
        ),
    )

    # -- Email -------------------------------------------------------------

    email_backend: EmailBackend = Field(
        default="console",
        description=(
            "How mail is delivered. 'console' writes the message to the log and "
            "sends nothing — local development only, so an invitation link can "
            "be copied out of a terminal. A deployed environment refuses to "
            "start on it."
        ),
    )

    email_from: str = Field(
        default="CAIRN <no-reply@localhost>",
        description="Envelope and header sender for every outbound message.",
    )

    smtp_host: str | None = Field(
        default=None,
        description="Relay host. Required when email_backend is 'smtp'.",
    )

    smtp_port: int = Field(default=587, gt=0, le=65535, description="Relay port.")

    smtp_username: str | None = Field(
        default=None,
        description="Relay username. Omitted for a relay authenticated by network.",
    )

    smtp_password: str | None = Field(default=None, description="Relay password.")

    # -- Queue ------------------------------------------------------------

    queue_backend: QueueBackend = Field(
        default="memory",
        description=(
            "Which broker to use. 'memory' is for local development and tests "
            "only — it holds jobs in RAM and loses them on restart, silently. "
            "A deployed environment refuses to start on it."
        ),
    )

    queue_fairness_optional: bool = Field(
        default=False,
        description=(
            "Accept a deployed queue backend that cannot enforce per-tenant "
            "fairness. Only Pub/Sub is affected: it delivers in arrival order, "
            "so one workspace's backfill can occupy every worker and delay "
            "another workspace's live events, and it reports no retry or "
            "dead-letter metrics. A deployed environment refuses to start on it "
            "unless this says the trade was chosen deliberately."
        ),
    )

    gcp_project_id: str | None = Field(
        default=None,
        description=(
            "GCP project owning the Pub/Sub topics. Required when queue_backend "
            "is 'pubsub' and never inferred from ambient credentials, which is "
            "how a staging worker ends up consuming production's queue."
        ),
    )

    model_backend: ModelBackend = Field(
        default="auto",
        description=(
            "Which model adapter the pipeline uses. 'auto' selects Vertex when "
            "gcp_project_id is set and no model otherwise. 'scripted' runs the "
            "deterministic provider the evaluation harness grades against, so a "
            "local environment produces real output through the real pipeline; "
            "a deployed environment refuses to start on it."
        ),
    )

    queue_topic: str = "cairn-jobs"
    queue_subscription: str = "cairn-jobs-worker"
    queue_dead_letter_topic: str = "cairn-jobs-dead-letter"

    # -- GitHub App --------------------------------------------------------

    github_app_id: str | None = Field(
        default=None,
        description="Numeric App ID from the GitHub App settings page.",
    )

    github_webhook_secret: str = Field(
        default="",
        description=(
            "Shared secret registered with the GitHub App. The entire basis for "
            "trusting an inbound webhook: the endpoint is unauthenticated, so a "
            "blank secret makes it an open write path. Verification refuses to "
            "run without one rather than passing everything."
        ),
    )

    github_private_key: str | None = Field(
        default=None,
        description=(
            "PEM private key for the GitHub App, used to mint installation "
            "tokens. Not needed to receive webhooks — only to call back to "
            "GitHub — so it is optional until Step 12."
        ),
    )

    # -- Model spend -------------------------------------------------------
    #
    # `pipeline/spend.py` enforces these. They live here rather than as module
    # constants next to the enforcement because a ceiling that cannot be lowered
    # without a deploy is a ceiling nobody can react with: the moment to change
    # one is during an incident, not during a release.

    model_max_tokens_per_tenant: int | None = Field(
        default=2_000_000,
        ge=0,
        description=(
            "Total model tokens (input + output) one tenant may spend in one "
            "process before further calls are refused. Roughly a full backfill "
            "of a busy repository: large enough that no legitimate job hits it, "
            "small enough that a runaway loop stops within a recognisable bill "
            "rather than an unrecognisable one. None disables this ceiling — "
            "supported only because the call ceiling still applies, so there is "
            "no configuration in which both are off."
        ),
    )

    model_max_calls_per_tenant: int | None = Field(
        default=5_000,
        ge=0,
        description=(
            "Total model calls one tenant may make in one process. The backstop "
            "for the token ceiling, which depends on the provider reporting its "
            "own usage honestly: an adapter that returns zero tokens — broken, "
            "scripted, or unable to parse the response's usage block — makes a "
            "token-only ceiling infinite. This one cannot be lied about, "
            "because we do the counting."
        ),
    )

    # -- Pipeline tuning ---------------------------------------------------
    #
    # Each of these mirrors a module constant that is documented where it is
    # used — `pipeline/synthesize.MAX_FACTS`, `pipeline/retrieval.DEFAULT_*`.
    # The reasoning for each number lives with the code it bounds and is not
    # repeated here; these fields exist so the number can be *changed* per
    # environment without a deploy, not so it can be explained twice.
    #
    # Mirrored rather than imported. Importing `pipeline.retrieval` here would
    # drag SQLAlchemy and every ORM model into the import graph of a module that
    # Alembic, the CLI and every test load first — and `db/session.py` already
    # imports this module, so the cycle is not hypothetical. The cost of
    # mirroring is that the two can drift, which is why
    # `test_config.py` asserts they are equal rather than trusting a comment.

    synthesis_max_facts: int = Field(
        default=40,
        gt=0,
        description=(
            "Facts offered to one synthesis call. Mirrors "
            "pipeline.synthesize.MAX_FACTS, which documents why 40."
        ),
    )

    retrieval_entry_points: int = Field(
        default=8,
        gt=0,
        description=(
            "Facts similarity search contributes before traversal begins. "
            "Mirrors pipeline.retrieval.DEFAULT_ENTRY_POINTS."
        ),
    )

    retrieval_max_hops: int = Field(
        default=2,
        ge=0,
        description=(
            "How far traversal walks from an entry point. Mirrors "
            "pipeline.retrieval.DEFAULT_MAX_HOPS."
        ),
    )

    retrieval_budget_chars: int = Field(
        default=60_000,
        gt=0,
        description=(
            "The retrieved set's size ceiling, in characters. Mirrors "
            "pipeline.retrieval.DEFAULT_BUDGET_CHARS."
        ),
    )

    @field_validator("cors_allowed_origins", mode="before")
    @classmethod
    def split_origins(cls, value: object) -> object:
        """Accept a comma-separated list.

        Environment variables are strings, and the alternative — requiring JSON
        in an env var — is the kind of papercut that ends with someone
        hardcoding the list in Python to make a deploy work.
        """
        if isinstance(value, str):
            return tuple(origin.strip() for origin in value.split(",") if origin.strip())
        return value

    @property
    def cookies_are_secure(self) -> bool:
        """Whether to set the ``Secure`` flag on the session cookie.

        Off locally only. Browsers refuse ``Secure`` cookies over plain HTTP, so
        leaving it on would make local development impossible and invite someone
        to disable it globally — which is how it ends up off in production.
        """
        return self.environment not in NON_DEPLOYED_ENVIRONMENTS

    @field_validator("database_url", "platform_database_url")
    @classmethod
    def require_async_driver(cls, value: PostgresDsn) -> PostgresDsn:
        """Reject a synchronous driver.

        The application is async throughout. A ``postgresql://`` URL would work
        in isolated tests and then block the event loop under real concurrency —
        a performance failure that only appears under load, which is the worst
        time to discover it.
        """
        if value.scheme != "postgresql+asyncpg":
            msg = f"database_url must use the postgresql+asyncpg driver, got {value.scheme!r}"
            raise ValueError(msg)
        return value

    @model_validator(mode="after")
    def reject_development_defaults_outside_local(self) -> Self:
        """Refuse to boot a deployed environment on local defaults.

        Both database URLs carry working local defaults, which is right for
        development and dangerous everywhere else: a Cloud Run revision that
        fails to receive its secret would otherwise start successfully and
        connect to whatever answers on localhost — in a Cloud SQL Proxy
        topology, a real database.

        The module docstring claimed no secret had a production-usable default.
        That was aspiration until this validator existed.
        """
        if self.environment in NON_DEPLOYED_ENVIRONMENTS:
            return self

        for name in ("database_url", "platform_database_url"):
            url = str(getattr(self, name))
            if "localhost" in url or "127.0.0.1" in url:
                msg = (
                    f"{name} points at localhost while CAIRN_ENVIRONMENT is "
                    f"'{self.environment}'. Refusing to start on a development "
                    "default — the secret was probably not injected."
                )
                raise ValueError(msg)
            if LOCAL_DEV_PASSWORD in url:
                msg = (
                    f"{name} contains the development password while "
                    f"CAIRN_ENVIRONMENT is '{self.environment}'. This value is "
                    "public in the repository."
                )
                raise ValueError(msg)

        if self.model_backend == "scripted":
            # The scripted provider answers from a fixed rule table. Its output
            # is indistinguishable in the interface from something a model
            # understood, which is exactly what md/09 §8 forbids reaching a
            # customer.
            msg = (
                "CAIRN_MODEL_BACKEND=scripted is a local-development backend. "
                "It returns canned model output, which would be presented to a "
                "customer as understanding."
            )
            raise ValueError(msg)

        if self.email_backend == "console":
            # The console backend writes the message to the log and reports
            # success. An invited colleague would never hear from us, and
            # nothing in the request or the row would record that.
            msg = (
                "CAIRN_EMAIL_BACKEND=console is a local-development backend. "
                "Invitations and verification links would be written to the log "
                "and delivered to nobody."
            )
            raise ValueError(msg)

        if self.database_echo:
            # Echoed SQL writes customer data into log storage.
            msg = (
                "database_echo must be off outside local development — it "
                "writes customer data to the logs."
            )
            raise ValueError(msg)

        if not self.github_webhook_secret:
            # The webhook endpoint is the only unauthenticated write path in the
            # service. Without a secret, signature verification has nothing to
            # verify against — so a deployed environment without one is an open
            # door that looks closed.
            msg = (
                "CAIRN_GITHUB_WEBHOOK_SECRET is required outside local "
                "development. The webhook endpoint is unauthenticated; without "
                "a secret it accepts anything."
            )
            raise ValueError(msg)

        for origin in self.cors_allowed_origins:
            # A wildcard here would be inert rather than dangerous — browsers
            # reject `*` on credentialed requests — but it signals that nobody
            # decided who may call this API, and the fix someone reaches for
            # next is to stop sending credentials.
            if origin == "*":
                msg = (
                    "cors_allowed_origins cannot be '*' outside local "
                    "development. List the app origins explicitly."
                )
                raise ValueError(msg)
            if origin.startswith("http://"):
                msg = (
                    f"cors_allowed_origins contains the insecure origin "
                    f"{origin!r}. Session cookies are Secure outside local "
                    "development and will not be sent over plain HTTP."
                )
                raise ValueError(msg)

        return self

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def is_deployed(self) -> bool:
        """Whether this environment can hold customer data.

        The distinction the validator below turns on. ``staging`` counts: it is
        a real deployment with real integrations, and treating it as harmless is
        how a development password ends up somewhere reachable.
        """
        return self.environment not in NON_DEPLOYED_ENVIRONMENTS

    @property
    def sync_database_url(self) -> str:
        """Synchronous URL, for Alembic only.

        Derived from the *platform* URL: migrations need DDL privileges the
        application role deliberately does not hold. psycopg 3 is used rather
        than the legacy psycopg2, which is in maintenance mode.
        """
        return str(self.platform_database_url).replace("+asyncpg", "+psycopg")


@lru_cache
def get_settings() -> Settings:
    """Return cached settings.

    Cached so that configuration is parsed once per process rather than on every
    request or dependency resolution.
    """
    return Settings()
