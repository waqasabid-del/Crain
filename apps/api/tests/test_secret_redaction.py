"""No credential survives being printed.

**Written the hour a live GitHub App private key was printed to a terminal.**
Not by application code: `uv`'s dotenv parser rejected an unquoted multi-line
PEM and included the whole value in the error it raised. The application never
touched it, and the key was compromised anyway.

That is the point. A credential in a `str` field is one traceback, one debug
`print(settings)`, one third-party parser away from a transcript, and every one
of those paths is outside this repository's control. `SecretStr` is inside it:
the value is unusable without an explicit `.get_secret_value()`, which is
greppable, and every implicit stringification yields `**********`.

The test is over the *fields*, not over a list of names somebody maintains, so a
credential added later is covered the day it is added rather than the day
somebody remembers this file exists.
"""

from __future__ import annotations

import pytest
from cairn_api.config import Settings
from pydantic import SecretStr

#: Substrings that make a field name a credential. Deliberately broad: a false
#: positive costs one `SecretStr`, a false negative costs a rotation.
CREDENTIAL_MARKERS = ("secret", "password", "private_key", "api_key", "encryption_key", "token")

#: Names containing a marker that are not themselves credentials.
NOT_CREDENTIALS = frozenset(
    {
        # A boolean about whether fairness may be skipped; no value to leak.
        "queue_fairness_optional",
        # A per-tenant model spend ceiling. "token" here is a unit of text, not
        # a credential - the marker list is broad on purpose and this is the
        # cost of that, paid once and in the open rather than by loosening it.
        "model_max_tokens_per_tenant",
    }
)


def credential_fields() -> list[str]:
    return sorted(
        name
        for name in Settings.model_fields
        if name not in NOT_CREDENTIALS and any(marker in name for marker in CREDENTIAL_MARKERS)
    )


class TestEveryCredentialIsASecretStr:
    def test_there_are_credentials_to_check(self) -> None:
        """Guards the guard: a marker list that matches nothing passes silently."""
        assert len(credential_fields()) >= 8

    @pytest.mark.parametrize("name", credential_fields())
    def test_the_field_is_a_secret_str(self, name: str) -> None:
        annotation = str(Settings.model_fields[name].annotation)
        assert "SecretStr" in annotation, (
            f"Settings.{name} holds a credential in a plain string. One traceback "
            "or one repr puts it wherever that output goes."
        )


class TestNothingLeaksThroughRepr:
    def test_a_populated_settings_repr_contains_no_value(self) -> None:
        """The end-to-end version of the check above.

        `repr(settings)` is what a debugger, a crash reporter and an over-helpful
        log line all reach for.
        """
        canary = "canary-value-that-must-not-appear"
        overrides = dict.fromkeys(credential_fields(), canary)
        settings = Settings(environment="local", **overrides)  # type: ignore[arg-type]

        assert canary not in repr(settings)
        assert canary not in str(settings)

    def test_the_value_is_still_reachable_deliberately(self) -> None:
        """Redaction that broke the read path would be swapped back out within a
        week. `.get_secret_value()` is the explicit, greppable way through."""
        settings = Settings(environment="local", github_webhook_secret=SecretStr("s3cret"))
        assert settings.github_webhook_secret.get_secret_value() == "s3cret"
