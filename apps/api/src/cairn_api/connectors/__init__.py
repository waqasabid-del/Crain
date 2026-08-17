"""Provider-neutral connector foundation.

What Slack and Google Chat (Step 32) will both need and neither should invent:
the connection record (``db/connector_models.py``), and encryption for the
credentials a connection holds (``credentials.py``).

Nothing here reaches a provider. Transport, OAuth and event parsing are per
connector and belong with the connector.
"""

from cairn_api.connectors.credentials import (
    REDACTED,
    CredentialCipher,
    CredentialEncryptionError,
    SecretValue,
    build_cipher,
    clear_secret,
    get_cipher,
    read_secret,
    store_secret,
)

__all__ = [
    "REDACTED",
    "CredentialCipher",
    "CredentialEncryptionError",
    "SecretValue",
    "build_cipher",
    "clear_secret",
    "get_cipher",
    "read_secret",
    "store_secret",
]
