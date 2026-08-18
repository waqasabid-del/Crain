"""Configuration guards.

Both database URLs carry working local defaults. That is right for development
and dangerous everywhere else: a deployed revision that fails to receive its
secret would otherwise start successfully against whatever answers on localhost
— which, in a Cloud SQL Proxy topology, is a real database.

These are boot-time controls, so they are exactly the kind that appear to work
without being exercised. The tests below construct the settings directly rather
than going through ``get_settings()``, which is cached and reads the developer's
own ``.env``.
"""

from __future__ import annotations

import pytest
from cairn_api.config import LOCAL_DEV_PASSWORD, Settings
from pydantic import ValidationError

LOCAL_URL = f"postgresql+asyncpg://cairn:{LOCAL_DEV_PASSWORD}@localhost:5432/cairn"
REMOTE_URL = "postgresql+asyncpg://cairn:s3cret-from-secret-manager@10.0.0.4:5432/cairn"
SECURE_ORIGIN = "https://app.example.com"

#: Environments that can hold customer data, and so are held to every rule here.
#:
#: `test` is deliberately absent: it names the automated test run against a
#: throwaway container on localhost, not a deployed test environment.
#: Pre-production deployments are `staging`.
DEPLOYED = ["staging", "production"]


def _settings(**overrides: object) -> Settings:
    """Build settings without consulting the environment or a .env file."""
    values: dict[str, object] = {
        "environment": "local",
        "database_url": LOCAL_URL,
        "platform_database_url": LOCAL_URL,
        # Overridden per-case. Supplied here because the default is an
        # http://localhost origin, which every deployed-environment case would
        # otherwise trip on before reaching the rule it is testing.
        "cors_allowed_origins": (SECURE_ORIGIN,),
        # Required outside local development: the webhook endpoint is
        # unauthenticated, so a blank secret makes it an open write path.
        "github_webhook_secret": "a-real-secret",
        # Required outside local development: the console backend writes
        # invitations to the log, where nobody invited will ever read them.
        "email_backend": "smtp",
        "smtp_host": "relay.example.com",
    }
    values.update(overrides)
    return Settings.model_validate(values)


class TestDriver:
    def test_a_synchronous_driver_is_refused(self) -> None:
        # Would work in isolated tests and block the event loop under real
        # concurrency — a failure that only appears under load.
        with pytest.raises(ValidationError, match="postgresql\\+asyncpg"):
            _settings(database_url="postgresql://cairn:pw@localhost:5432/cairn")


class TestLocalDefaults:
    def test_local_development_may_use_the_published_defaults(self) -> None:
        # The guard must not make ordinary development harder; that is how
        # guards get disabled.
        settings = _settings()

        assert settings.environment == "local"
        assert settings.is_production is False

    @pytest.mark.parametrize("environment", DEPLOYED)
    @pytest.mark.parametrize("field", ["database_url", "platform_database_url"])
    def test_localhost_is_refused_outside_local(self, environment: str, field: str) -> None:
        # The realistic failure: the secret was never injected, so the default
        # survives and the process connects to whatever is listening.
        with pytest.raises(ValidationError, match="Refusing to start"):
            _settings(**{"environment": environment, field: LOCAL_URL})

    @pytest.mark.parametrize("field", ["database_url", "platform_database_url"])
    def test_loopback_by_address_is_refused_too(self, field: str) -> None:
        # A guard that only knows the word "localhost" is trivially defeated by
        # writing the address instead, which is common in generated config.
        url = REMOTE_URL.replace("10.0.0.4", "127.0.0.1")

        with pytest.raises(ValidationError, match="Refusing to start"):
            _settings(**{"environment": "production", field: url})

    @pytest.mark.parametrize("field", ["database_url", "platform_database_url"])
    def test_the_published_development_password_is_refused(self, field: str) -> None:
        # A remote host is not sufficient. This password appears in
        # .env.example and docker-compose.yml, so it is public.
        url = f"postgresql+asyncpg://cairn:{LOCAL_DEV_PASSWORD}@10.0.0.4:5432/cairn"
        # Both URLs must be remote, or the localhost rule fires first and this
        # asserts nothing about the password rule.
        values: dict[str, object] = {
            "environment": "production",
            "database_url": REMOTE_URL,
            "platform_database_url": REMOTE_URL,
            field: url,
        }

        with pytest.raises(ValidationError, match="public in the repository"):
            _settings(**values)

    def test_the_automated_test_run_may_use_localhost(self) -> None:
        # `test` means pytest against a throwaway container, in CI or on a
        # laptop. Holding it to the deployed rules would make the API layer's
        # own tests unrunnable, and the fix someone reaches for is to weaken
        # the validator for everyone.
        settings = _settings(environment="test", cors_allowed_origins=("http://localhost:3000",))

        assert settings.is_deployed is False
        assert settings.cookies_are_secure is False

    @pytest.mark.parametrize("environment", DEPLOYED)
    def test_deployed_environments_set_secure_cookies(self, environment: str) -> None:
        settings = _settings(
            environment=environment,
            database_url=REMOTE_URL,
            platform_database_url=REMOTE_URL,
        )

        assert settings.is_deployed is True
        assert settings.cookies_are_secure is True

    def test_a_properly_injected_secret_is_accepted(self) -> None:
        # The positive control. Without it these tests would still pass if the
        # validator rejected everything, and nothing could be deployed at all.
        settings = _settings(
            environment="production",
            database_url=REMOTE_URL,
            platform_database_url=REMOTE_URL,
        )

        assert settings.is_production is True


class TestCors:
    def test_a_wildcard_origin_is_refused_when_deployed(self) -> None:
        # Inert rather than dangerous — browsers reject `*` on credentialed
        # requests — but it signals that nobody decided who may call this API,
        # and the fix someone reaches for next is to stop sending credentials.
        with pytest.raises(ValidationError, match=r"cannot be '\*'"):
            _settings(
                environment="production",
                database_url=REMOTE_URL,
                platform_database_url=REMOTE_URL,
                cors_allowed_origins=("*",),
            )

    def test_an_insecure_origin_is_refused_when_deployed(self) -> None:
        # The session cookie is Secure outside local development, so a browser
        # on an http:// origin would never send it. Failing at startup beats
        # debugging "I am signed in but every request is a 401".
        with pytest.raises(ValidationError, match="insecure origin"):
            _settings(
                environment="production",
                database_url=REMOTE_URL,
                platform_database_url=REMOTE_URL,
                cors_allowed_origins=("http://app.example.com",),
            )

    def test_origins_may_be_given_as_a_comma_separated_string(self) -> None:
        # Environment variables are strings. The alternative — requiring JSON in
        # an env var — is the kind of papercut that ends with someone hardcoding
        # the list in Python to make a deploy work.
        settings = _settings(cors_allowed_origins="http://localhost:3000, http://localhost:3001")

        assert settings.cors_allowed_origins == ("http://localhost:3000", "http://localhost:3001")


class TestGitHubWebhookSecret:
    @pytest.mark.parametrize("environment", DEPLOYED)
    def test_a_missing_secret_is_refused_when_deployed(self, environment: str) -> None:
        # The webhook endpoint is the only unauthenticated write path in the
        # service. Without a secret there is nothing to verify against, so it
        # accepts anything — an open door that looks closed.
        with pytest.raises(ValidationError, match="GITHUB_WEBHOOK_SECRET"):
            _settings(
                environment=environment,
                database_url=REMOTE_URL,
                platform_database_url=REMOTE_URL,
                github_webhook_secret="",
            )

    def test_local_development_may_omit_it(self) -> None:
        # Requiring it locally would mean every contributor needs a GitHub App
        # before they can run the API, which is how a guard gets disabled.
        # Overridden explicitly because the shared helper supplies one.
        assert _settings(github_webhook_secret="").environment == "local"


class TestSqlEcho:
    def test_echo_is_refused_outside_local(self) -> None:
        # Echoed SQL writes customer data into log storage, where it outlives
        # any retention policy the database has.
        with pytest.raises(ValidationError, match="writes customer data"):
            _settings(
                environment="staging",
                database_url=REMOTE_URL,
                platform_database_url=REMOTE_URL,
                database_echo=True,
            )

    def test_echo_is_allowed_locally(self) -> None:
        assert _settings(database_echo=True).database_echo is True


class TestDerivedUrls:
    def test_migrations_use_the_platform_url_with_a_sync_driver(self) -> None:
        # Alembic needs DDL privileges the application role deliberately does
        # not hold, so this must derive from the platform URL — deriving it from
        # `database_url` would produce migrations that fail on permissions in
        # production and pass locally, where the two often coincide.
        settings = _settings(
            environment="production",
            database_url="postgresql+asyncpg://cairn_app:pw@10.0.0.4:5432/cairn",
            platform_database_url=REMOTE_URL,
        )

        assert settings.sync_database_url.startswith("postgresql+psycopg://cairn:")
        assert "+asyncpg" not in settings.sync_database_url


class TestPipelineTuningMirrorsTheConstants:
    """The mirrored numbers must equal the constants they mirror.

    `Settings` carries copies of `pipeline.synthesize.MAX_FACTS` and the
    `pipeline.retrieval.DEFAULT_*` constants rather than importing them —
    importing `pipeline.retrieval` from `config` would drag SQLAlchemy and every
    ORM model into the import graph of the module `db/session.py` already
    imports, which is a cycle.

    The cost of mirroring is drift, and a comment saying "keep these in sync" is
    not a control. This is. The imports are local to the test so that the
    production cycle stays absent.
    """

    def test_synthesis_ceiling_matches(self) -> None:
        from cairn_api.pipeline.synthesize import MAX_FACTS

        assert _settings().synthesis_max_facts == MAX_FACTS

    def test_retrieval_defaults_match(self) -> None:
        from cairn_api.pipeline import retrieval

        settings = _settings()
        assert settings.retrieval_entry_points == retrieval.DEFAULT_ENTRY_POINTS
        assert settings.retrieval_max_hops == retrieval.DEFAULT_MAX_HOPS
        assert settings.retrieval_budget_chars == retrieval.DEFAULT_BUDGET_CHARS

    def test_config_does_not_import_the_pipeline(self) -> None:
        """The reason the values are mirrored at all.

        Asserted against the source rather than the import graph: by the time a
        test runs, `pipeline` is imported anyway. A top-level import added here
        would reintroduce the cycle and nothing else would notice.
        """
        import pathlib

        import cairn_api.config

        source = pathlib.Path(cairn_api.config.__file__).read_text(encoding="utf-8")
        assert "from cairn_api.pipeline" not in source
        assert "import cairn_api.pipeline" not in source


class TestOpenAIBackend:
    """The key must be present at boot, not discovered at the first model call.

    A missing key is not a transient failure. It is a deployment that cannot do
    the one thing the backend was selected for, and the difference between
    finding out at boot and finding out at the first customer request is the
    difference between a revision that never serves traffic and a workspace whose
    briefs are quietly empty.
    """

    @pytest.mark.parametrize("environment", ["local", "test", "staging", "production"])
    def test_the_backend_without_a_key_refuses_to_start(self, environment: str) -> None:
        """**Every environment, including local.**

        The other development guards are about deployed environments holding
        customer data; this one is about a setting that cannot work anywhere. A
        local developer who selects the OpenAI backend and forgets the key should
        be told at boot rather than reading an empty brief and wondering which
        layer swallowed it.
        """
        with pytest.raises(ValidationError, match="CAIRN_OPENAI_API_KEY"):
            _settings(
                environment=environment,
                database_url=REMOTE_URL if environment in DEPLOYED else LOCAL_URL,
                platform_database_url=REMOTE_URL if environment in DEPLOYED else LOCAL_URL,
                model_backend="openai",
                openai_api_key="",
            )

    def test_the_backend_with_a_key_is_accepted(self) -> None:
        settings = _settings(model_backend="openai", openai_api_key="sk-not-a-real-key")

        assert settings.model_backend == "openai"

    def test_a_key_without_the_backend_is_not_required_to_do_anything(self) -> None:
        """Holding a key is not selecting the backend.

        Someone may set the key in a shared environment file long before
        switching the pipeline over, and refusing that would make the safe
        preparation step the thing that breaks boot.
        """
        settings = _settings(openai_api_key="sk-not-a-real-key")

        assert settings.model_backend == "auto"

    def test_the_defaults_name_the_cheap_models(self) -> None:
        """Pinned, because an unpinned default is a silent cost and quality
        change on somebody else's release day."""
        settings = _settings()

        assert settings.openai_model == "gpt-4o-mini"
        assert settings.openai_embedding_model == "text-embedding-3-small"
        # A `SecretStr`, so the comparison goes through `get_secret_value`.
        # The type is the point: an equality test that passed against a bare
        # string would mean the key could be interpolated into one.
        assert settings.openai_api_key.get_secret_value() == ""

    def test_the_key_never_appears_in_a_repr(self) -> None:
        """`Settings` is logged at startup and appears in tracebacks.

        A key that reaches either is a key in the log store, which sits outside
        the erasure path and is read by more people than the secret manager is.
        """
        settings = _settings(openai_api_key="sk-super-secret-value")

        assert "sk-super-secret-value" not in repr(settings)
        assert "sk-super-secret-value" not in str(settings)

    def test_the_existing_backends_are_still_accepted(self) -> None:
        """The new member widens the union; it must not narrow it."""
        for backend in ("auto", "vertex", "offline"):
            assert _settings(model_backend=backend).model_backend == backend

    def test_scripted_is_still_refused_when_deployed(self) -> None:
        """Untouched by this change, and asserted so that adding a backend
        cannot quietly relax the rule that guards the others."""
        with pytest.raises(ValidationError, match="scripted"):
            _settings(
                environment="production",
                database_url=REMOTE_URL,
                platform_database_url=REMOTE_URL,
                cors_allowed_origins=(SECURE_ORIGIN,),
                model_backend="scripted",
            )
