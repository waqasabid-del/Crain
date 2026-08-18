"""Connector credentials, encrypted at rest and awkward to read by accident.

A Slack bot token is a standing grant to read a customer's conversations. It
outlives our process, it is useful to anyone who obtains it, and — unlike a
password hash — it must be recoverable, so hashing is not an option. That leaves
encryption, and encryption is only as good as the two things people get wrong:
where the key comes from, and how easy it is for the plaintext to end up
somewhere it was never meant to be.

**Where the key comes from.** Configuration, never source. A deployed
environment with no key refuses to start, and a deployed environment holding the
published development key refuses too — the same shape as ``jobs/factory.py``
and ``telemetry/startup.py``, and for the same reason: silently degrading to a
weaker mode leaves every description of the system ("credentials are encrypted")
technically true and practically worthless.

**How the plaintext escapes.** Not by anyone deciding to leak it. It escapes
through a ``repr`` in a traceback, a log line that rendered a whole object, or a
response model that serialised one field more than intended. So the plaintext
lives in :class:`SecretValue`, which redacts itself in all three, and the
ciphertext lives on a private column with no property returning it. Getting the
real string requires calling :func:`read_secret` or :meth:`SecretValue.reveal` —
both greppable, both reviewable.
"""

from __future__ import annotations

import hmac
from functools import lru_cache
from typing import TYPE_CHECKING, final

import structlog
from cryptography.fernet import Fernet, InvalidToken
from pydantic_core import core_schema

from cairn_api.config import (
    CONNECTOR_ENCRYPTION_KEY_VAR,
    DEVELOPMENT_CONNECTOR_KEY,
    Settings,
    get_settings,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from pydantic import GetCoreSchemaHandler

    from cairn_api.db.connector_models import SourceConnection

logger = structlog.get_logger(__name__)

#: What a secret renders as everywhere a secret must not render. A single
#: constant so a test can assert the placeholder rather than assert the absence
#: of a token — "the token is not in this string" passes trivially when the
#: string is empty for an unrelated reason.
REDACTED = "***redacted***"


class CredentialEncryptionError(RuntimeError):
    """Credentials cannot be encrypted or decrypted in this environment."""


@final
class SecretValue:
    """A plaintext credential that will not render itself.

    ``__slots__`` because a secret with a ``__dict__`` is a secret that shows up
    in every generic object walker — including ``vars()``, which is what a
    logging helper reaches for when handed something it does not recognise.
    """

    __slots__ = ("_plaintext",)

    def __init__(self, plaintext: str) -> None:
        if not plaintext:
            # An empty credential is never a real one, and storing it produces
            # a connection that looks configured and authenticates as nobody.
            msg = "A credential cannot be empty."
            raise ValueError(msg)
        self._plaintext = plaintext

    def reveal(self) -> str:
        """Return the plaintext.

        The only way out, and named so that a reviewer scanning a diff for
        ``reveal(`` finds every place a credential is handled.
        """
        return self._plaintext

    def __repr__(self) -> str:
        return f"SecretValue({REDACTED})"

    def __str__(self) -> str:
        return REDACTED

    def __eq__(self, other: object) -> bool:
        """Constant-time, so comparison does not leak the value by timing."""
        if not isinstance(other, SecretValue):
            return NotImplemented
        return hmac.compare_digest(self._plaintext, other._plaintext)

    def __hash__(self) -> int:
        # Deliberately not derived from the plaintext: a hash bucket is
        # observable, and equality above is already the supported comparison.
        return hash(SecretValue)

    @classmethod
    def _coerce(cls, value: object) -> SecretValue:
        if isinstance(value, SecretValue):
            return value
        if isinstance(value, str):
            return cls(value)
        msg = f"Cannot build a SecretValue from {type(value).__name__}"
        raise ValueError(msg)

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source_type: object, handler: GetCoreSchemaHandler
    ) -> core_schema.CoreSchema:
        """Serialise as the placeholder, in every Pydantic model, always.

        Opt-out rather than opt-in. A response model that happens to include a
        secret field is a mistake somebody makes once; making the *type* refuse
        to serialise itself means the mistake produces a redacted string in a
        payload instead of a token in a customer's browser.
        """
        return core_schema.no_info_plain_validator_function(
            cls._coerce,
            serialization=core_schema.plain_serializer_function_ser_schema(
                lambda _secret: REDACTED, return_schema=core_schema.str_schema()
            ),
        )


@final
class CredentialCipher:
    """Fernet, wrapped so the key cannot be read back off it."""

    __slots__ = ("_fernet",)

    def __init__(self, key: str) -> None:
        try:
            self._fernet = Fernet(key)
        except (TypeError, ValueError) as exc:
            # Fernet's own message is "Fernet key must be 32 url-safe
            # base64-encoded bytes", which is accurate and says nothing about
            # which variable was wrong.
            msg = (
                f"{CONNECTOR_ENCRYPTION_KEY_VAR} is not a valid Fernet key. It "
                f"must be 32 url-safe base64-encoded bytes; generate one with "
                f'`python -c "from cryptography.fernet import Fernet; '
                f'print(Fernet.generate_key().decode())"`.'
            )
            raise CredentialEncryptionError(msg) from exc

    def encrypt(self, secret: SecretValue) -> str:
        """Encrypt a credential for storage."""
        return self._fernet.encrypt(secret.reveal().encode()).decode()

    def decrypt(self, ciphertext: str) -> SecretValue:
        """Decrypt stored ciphertext.

        Raises rather than returning ``None`` on failure. A wrong key is a
        configuration incident — usually a half-finished key rotation — and the
        one response that must not happen is treating it as "no credential" and
        marking the connection disconnected, which erases the evidence and
        prompts the customer to re-authorise every integration.
        """
        try:
            plaintext = self._fernet.decrypt(ciphertext.encode()).decode()
        except InvalidToken as exc:
            # Deliberately no ciphertext, no key fingerprint, no length in the
            # message: this string reaches logs and error trackers.
            msg = (
                "A connector credential could not be decrypted. The value was "
                f"encrypted with a different key than {CONNECTOR_ENCRYPTION_KEY_VAR} "
                "currently holds, or it was modified in storage."
            )
            raise CredentialEncryptionError(msg) from exc
        return SecretValue(plaintext)

    def __repr__(self) -> str:
        return f"CredentialCipher(key={REDACTED})"

    __str__ = __repr__


def build_cipher(settings: Settings | None = None) -> CredentialCipher:
    """Construct the cipher for this process, or refuse.

    Mirrors ``jobs.factory.build_queue``: the environment decides whether a
    development default is acceptable, and a deployed one never is.
    """
    settings = settings or get_settings()
    key = settings.connector_encryption_key.get_secret_value()

    if not key:
        if settings.is_deployed:
            # Also caught by the `Settings` validator, so a normally-configured
            # process fails at startup rather than here. Repeated because this
            # function is reachable with a hand-built `Settings` — a worker
            # entrypoint, a script, a test — and the guard that only exists in
            # one of two doors is the one that gets walked around.
            msg = (
                f"{CONNECTOR_ENCRYPTION_KEY_VAR} is not set but CAIRN_ENVIRONMENT "
                f"is '{settings.environment}'. Connector credentials are "
                f"third-party access tokens and cannot be stored without a key. "
                f"Set {CONNECTOR_ENCRYPTION_KEY_VAR} to a generated Fernet key."
            )
            raise CredentialEncryptionError(msg)

        logger.info(
            "connectors.using_development_encryption_key",
            environment=settings.environment,
            detail=(
                "No key configured. Using the development key published in "
                "config.py — credentials in this database are readable by "
                "anyone with the source."
            ),
        )
        return CredentialCipher(DEVELOPMENT_CONNECTOR_KEY)

    if settings.is_deployed and key == DEVELOPMENT_CONNECTOR_KEY:
        msg = (
            f"{CONNECTOR_ENCRYPTION_KEY_VAR} is set to the development key, "
            f"which is published in this repository, while CAIRN_ENVIRONMENT is "
            f"'{settings.environment}'. Every stored connector credential would "
            f"be decryptable by anyone who has read the source."
        )
        raise CredentialEncryptionError(msg)

    return CredentialCipher(key)


@lru_cache
def get_cipher() -> CredentialCipher:
    """Cached: key derivation and validation are per-process work, not per-call."""
    return build_cipher()


def store_secret(
    connection: SourceConnection,
    secret: SecretValue,
    *,
    cipher: CredentialCipher | None = None,
) -> None:
    """Attach an encrypted credential to a connection."""
    connection._secret_ciphertext = (cipher or get_cipher()).encrypt(secret)


def read_secret(
    connection: SourceConnection, *, cipher: CredentialCipher | None = None
) -> SecretValue | None:
    """Decrypt a connection's credential, or ``None`` if it holds one.

    A function rather than a property on the model, which is the whole design.
    A property is evaluated by anything that walks an object and is invisible at
    the call site; this is an import and a call, so "where do we decrypt
    credentials" is answerable with grep.
    """
    if connection._secret_ciphertext is None:
        return None
    return (cipher or get_cipher()).decrypt(connection._secret_ciphertext)


def clear_secret(connection: SourceConnection) -> None:
    """Drop a connection's credential.

    Used on disconnect and on revocation. A revoked connection that keeps its
    token keeps a live grant we no longer have consent to hold.
    """
    connection._secret_ciphertext = None
