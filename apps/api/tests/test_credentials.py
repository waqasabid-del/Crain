"""Connector credential handling.

Two properties, and every test here fails if either is removed.

**The key is real or the process refuses.** A deployed environment with no key,
or with the key published in this repository, must not start a connector at all.
Degrading quietly is the failure mode: every description of the system would
still say "credentials are encrypted at rest", and it would be true of a key
anyone can read.

**The plaintext does not leak by accident.** Nobody logs a token deliberately.
It escapes through a ``repr`` in a traceback, a log line that rendered an object
whole, or a response model that serialised one field too many. So the tests
below drive it through exactly those four routes — ``repr``, ``str``, a rendered
log record, and ``model_dump`` — plus the exception raised when decryption
fails, which is the one an error tracker keeps forever.
"""

from __future__ import annotations

import uuid

import pytest
import structlog
from cairn_api.config import (
    CONNECTOR_ENCRYPTION_KEY_VAR,
    DEVELOPMENT_CONNECTOR_KEY,
    LOCAL_DEV_PASSWORD,
    Settings,
)
from cairn_api.connectors.credentials import (
    REDACTED,
    CredentialCipher,
    CredentialEncryptionError,
    SecretValue,
    build_cipher,
    clear_secret,
    read_secret,
    store_secret,
)
from cairn_api.db.connector_models import ConnectorProvider, SourceConnection
from cryptography.fernet import Fernet
from pydantic import BaseModel, ValidationError

#: Shaped like a real Slack bot token so a substring check is meaningful. A
#: secret like "x" would be found in half the strings this module builds.
# Deliberately not shaped like a real Slack bot token. The credential path is
# prefix-agnostic, so the test loses nothing — and a fixture that looks like the
# thing the secret scanner exists to catch trains its readers to wave one
# through.
TOKEN = "stand-in-credential-4f2c9a"  # noqa: S105

LOCAL_URL = f"postgresql+asyncpg://cairn:{LOCAL_DEV_PASSWORD}@localhost:5432/cairn"
REMOTE_URL = "postgresql+asyncpg://cairn:s3cret-from-secret-manager@10.0.0.4:5432/cairn"

DEPLOYED = ["staging", "production"]


def _settings(**overrides: object) -> Settings:
    """Build settings without consulting the environment or a .env file.

    Mirrors ``test_config._settings``. Duplicated rather than imported: a
    cross-module import between test files makes the tests directory a package,
    and the conftest is deliberately the only shared surface.
    """
    values: dict[str, object] = {
        "environment": "local",
        "database_url": LOCAL_URL,
        "platform_database_url": LOCAL_URL,
    }
    if overrides.get("environment") in DEPLOYED:
        # Every other deployed-environment guard would fire first and the test
        # would pass for the wrong reason.
        values.update(
            {
                "database_url": REMOTE_URL,
                "platform_database_url": REMOTE_URL,
                "cors_allowed_origins": ("https://app.example.com",),
                "github_webhook_secret": "a-real-secret",
                "email_backend": "smtp",
                "smtp_host": "relay.example.com",
            }
        )
    values.update(overrides)
    return Settings.model_validate(values)


def _generated_key() -> str:
    return Fernet.generate_key().decode()


class TestTheRefusalHappensAtStartup:
    """Caught at boot, not at the first connector write.

    The difference is where the failure lands. Deferred to first use, the
    missing key surfaces at the moment a customer is handing CAIRN an access
    token — the worst possible time to discover there is nowhere safe to put
    it, and a moment when the honest options are all bad. At startup it is a
    deploy that does not go out.

    Asserted by calling the same builder both entry points call, rather than by
    booting the app: `create_app` needs a reachable database, and a check that
    only runs when the database is up is not the check being described.
    """

    @pytest.mark.parametrize("environment", DEPLOYED)
    def test_both_entry_points_build_the_cipher_before_serving(self, environment: str) -> None:
        import inspect

        from cairn_api.api import app as api_app
        from cairn_api.jobs import main as worker_main

        for module, function in ((api_app, "lifespan"), (worker_main, "run_worker")):
            source = inspect.getsource(getattr(module, function))
            assert "build_cipher(settings)" in source, (
                f"{module.__name__}.{function} serves without checking encryption"
            )

        # And the builder those call genuinely refuses, so the wiring above is
        # not pointing at something permissive.
        with pytest.raises(CredentialEncryptionError):
            build_cipher(_settings(environment=environment))


class TestFailClosed:
    """A deployed environment gets a real key or gets nothing."""

    @pytest.mark.parametrize("environment", DEPLOYED)
    def test_a_deployed_environment_with_no_key_refuses(self, environment: str) -> None:
        with pytest.raises(CredentialEncryptionError) as caught:
            build_cipher(_settings(environment=environment))

        message = str(caught.value)
        # The message has to be actionable at three in the morning. "Encryption
        # is not configured" sends someone reading source; naming the variable
        # ends the incident.
        assert CONNECTOR_ENCRYPTION_KEY_VAR in message
        assert environment in message

    @pytest.mark.parametrize("environment", DEPLOYED)
    def test_the_development_key_is_refused_when_deployed(self, environment: str) -> None:
        # Refused twice over, because there are two doors. `Settings` rejects it
        # at construction, so an ordinary process never boots; `build_cipher`
        # rejects it again for a `Settings` built by hand in a worker
        # entrypoint or a script.
        with pytest.raises(ValidationError, match=CONNECTOR_ENCRYPTION_KEY_VAR):
            _settings(environment=environment, connector_encryption_key=DEVELOPMENT_CONNECTOR_KEY)

        hand_built = _settings(environment=environment)
        # Assignment does not re-run the model validator, which is the point:
        # `build_cipher` must not depend on the validator having seen this
        # value.
        hand_built.connector_encryption_key = DEVELOPMENT_CONNECTOR_KEY

        with pytest.raises(CredentialEncryptionError, match="published in this repository"):
            build_cipher(hand_built)

    def test_local_development_falls_back_to_the_development_key(self) -> None:
        # The guard must not make ordinary development harder; that is how
        # guards get disabled. The fallback exists so the *real* encryption path
        # runs locally — an "encryption optional" branch is a branch something
        # eventually takes in production.
        cipher = build_cipher(_settings(environment="local"))

        assert cipher.decrypt(cipher.encrypt(SecretValue(TOKEN))).reveal() == TOKEN

    def test_a_malformed_key_names_the_variable(self) -> None:
        # Fernet's own message is accurate and says nothing about which setting
        # produced it.
        with pytest.raises(CredentialEncryptionError, match=CONNECTOR_ENCRYPTION_KEY_VAR):
            build_cipher(_settings(connector_encryption_key="not-base64"))


class TestRoundTrip:
    def test_a_credential_survives_encryption(self) -> None:
        cipher = CredentialCipher(_generated_key())

        assert cipher.decrypt(cipher.encrypt(SecretValue(TOKEN))).reveal() == TOKEN

    def test_the_ciphertext_is_not_the_plaintext(self) -> None:
        # Guards against the encrypt method being reduced to a pass-through by
        # a future "make the tests pass" change.
        ciphertext = CredentialCipher(_generated_key()).encrypt(SecretValue(TOKEN))

        assert TOKEN not in ciphertext

    def test_encryption_is_not_deterministic(self) -> None:
        # Fernet includes a random IV. Two identical tokens must not produce
        # identical ciphertext, or the database reveals which workspaces share
        # a credential.
        cipher = CredentialCipher(_generated_key())

        assert cipher.encrypt(SecretValue(TOKEN)) != cipher.encrypt(SecretValue(TOKEN))

    def test_the_wrong_key_fails_loudly(self) -> None:
        """Never garbage, and never ``None``.

        Returning ``None`` would read as "this connection has no credential",
        and the handling for that is to mark it disconnected and ask the
        customer to re-authorise — which, during a half-finished key rotation,
        means every integration in the product asking every customer to
        reconnect for no reason.
        """
        ciphertext = CredentialCipher(_generated_key()).encrypt(SecretValue(TOKEN))

        with pytest.raises(CredentialEncryptionError, match="could not be decrypted"):
            CredentialCipher(_generated_key()).decrypt(ciphertext)

    def test_tampered_ciphertext_is_rejected(self) -> None:
        # Fernet is authenticated; this asserts we did not disable that by
        # reaching for a raw cipher.
        cipher = CredentialCipher(_generated_key())
        ciphertext = cipher.encrypt(SecretValue(TOKEN))
        tampered = ciphertext[:-4] + ("AAAA" if not ciphertext.endswith("AAAA") else "BBBB")

        with pytest.raises(CredentialEncryptionError):
            cipher.decrypt(tampered)

    def test_an_empty_credential_is_refused(self) -> None:
        # A stored empty string is a connection that looks configured and
        # authenticates as nobody.
        with pytest.raises(ValueError, match="cannot be empty"):
            SecretValue("")


class TestTheSecretDoesNotLeak:
    """The four routes a token actually escapes through, plus the fifth."""

    def test_repr_redacts(self) -> None:
        assert TOKEN not in repr(SecretValue(TOKEN))
        assert REDACTED in repr(SecretValue(TOKEN))

    def test_str_redacts(self) -> None:
        secret = SecretValue(TOKEN)

        assert str(secret) == REDACTED
        assert TOKEN not in f"{secret}"
        assert TOKEN not in f"{secret!r}"

    def test_it_has_no_dict_for_an_object_walker_to_find(self) -> None:
        # `__slots__`, so `vars()` — what a generic logging helper reaches for
        # when handed something it does not recognise — raises rather than
        # handing back the plaintext.
        with pytest.raises(TypeError):
            vars(SecretValue(TOKEN))

    def test_a_rendered_log_record_redacts(self) -> None:
        # Rendered rather than captured. `capture_logs` holds the event dict
        # with the object still in it, so a test asserting against that proves
        # nothing about what reaches log storage.
        rendered = structlog.processors.KeyValueRenderer()(
            None, "info", {"event": "connector.connected", "token": SecretValue(TOKEN)}
        )

        assert TOKEN not in rendered
        assert REDACTED in rendered

    def test_model_dump_redacts(self) -> None:
        class ConnectionPayload(BaseModel):
            name: str
            token: SecretValue

        payload = ConnectionPayload(name="slack", token=SecretValue(TOKEN))

        assert payload.model_dump()["token"] == REDACTED
        assert TOKEN not in payload.model_dump_json()

    def test_a_decryption_failure_message_carries_neither_key_nor_ciphertext(self) -> None:
        # The string an error tracker keeps forever, attached to a stack trace
        # and a workspace name.
        key = _generated_key()
        ciphertext = CredentialCipher(key).encrypt(SecretValue(TOKEN))

        with pytest.raises(CredentialEncryptionError) as caught:
            CredentialCipher(_generated_key()).decrypt(ciphertext)

        message = str(caught.value)
        assert TOKEN not in message
        assert ciphertext not in message
        assert key not in message

    def test_the_cipher_does_not_render_its_key(self) -> None:
        key = _generated_key()
        cipher = CredentialCipher(key)

        assert key not in repr(cipher)
        assert key not in str(cipher)
        assert REDACTED in repr(cipher)


class TestTheConnectionRow:
    """Storing a credential on a model must not put it back in reach."""

    @staticmethod
    def _connection() -> SourceConnection:
        return SourceConnection(
            tenant_id=uuid.uuid4(),
            provider=ConnectorProvider.SLACK,
            external_account_id="T0123ABCD",
            installation_id="I0123ABCD",
            scopes=["channels:history"],
        )

    def test_store_and_read_round_trip(self) -> None:
        cipher = CredentialCipher(_generated_key())
        connection = self._connection()

        store_secret(connection, SecretValue(TOKEN), cipher=cipher)

        secret = read_secret(connection, cipher=cipher)
        assert secret is not None
        assert secret.reveal() == TOKEN

    def test_a_connection_without_a_credential_reads_as_none(self) -> None:
        assert read_secret(self._connection(), cipher=CredentialCipher(_generated_key())) is None

    def test_clearing_removes_it(self) -> None:
        # Used on revoke. A revoked connection holding a live token holds a
        # grant we no longer have consent for.
        cipher = CredentialCipher(_generated_key())
        connection = self._connection()
        store_secret(connection, SecretValue(TOKEN), cipher=cipher)

        clear_secret(connection)

        assert read_secret(connection, cipher=cipher) is None

    def test_no_public_attribute_returns_the_ciphertext(self) -> None:
        """The design property, asserted rather than described.

        Reading the credential must be an explicit call. If someone adds a
        convenience property — `connection.secret`, `connection.credential`,
        anything — it lands in `repr`, in serialisers, and in every generic
        object walker, and this fails.
        """
        cipher = CredentialCipher(_generated_key())
        connection = self._connection()
        store_secret(connection, SecretValue(TOKEN), cipher=cipher)

        for name in dir(connection):
            if name.startswith("_"):
                continue
            value = getattr(connection, name, None)
            assert value != TOKEN, f"{name} returns the plaintext credential"
            assert value != connection._secret_ciphertext, f"{name} returns the ciphertext"

    def test_the_connection_repr_carries_neither(self) -> None:
        cipher = CredentialCipher(_generated_key())
        connection = self._connection()
        store_secret(connection, SecretValue(TOKEN), cipher=cipher)

        ciphertext = connection._secret_ciphertext
        assert ciphertext is not None, "the secret was not stored, so this proves nothing"

        for rendered in (repr(connection), str(connection)):
            assert TOKEN not in rendered
            assert ciphertext not in rendered
        # Identity is still there — a repr that says nothing useful gets
        # replaced by one that says everything.
        assert "I0123ABCD" in repr(connection)
