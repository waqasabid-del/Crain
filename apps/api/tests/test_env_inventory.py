"""`.env.example` is the inventory, or it is decoration.

Every configurable thing this service reads comes from `Settings`, and the only
place a person can discover what a deployment needs is `.env.example`. When the
two disagree the failure is not a missing comment: it is a staging environment
that boots, passes its probes, and is missing the credential for a connector
nobody remembered — which reads as "that integration is quiet this week".

This is checked rather than reviewed because it drifts silently and in one
direction. Adding a setting is a change to `config.py`; documenting it is a
change to a file no test touched, so the second half is what gets dropped. When
this was first written, 29 of 55 settings were undocumented, including the
connector encryption key and every Slack, Google Chat and Google Meet
credential.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from cairn_api.config import Settings

#: Repository root, from `apps/api/tests/`.
ENV_EXAMPLE = Path(__file__).resolve().parents[3] / ".env.example"

#: The prefix `SettingsConfigDict` puts in front of every field name.
PREFIX = "CAIRN_"

#: Read from the environment by something other than `Settings`, and therefore
#: legitimately documented without a matching field.
#:
#: Both belong to migrations, which run before the application does and cannot
#: use `Settings` to decide how to build the roles the application will later
#: connect as. Listed explicitly rather than pattern-matched: the point of the
#: check below is that an undeclared name is a typo, and an allow-list nobody
#: has to justify defeats it.
NON_SETTINGS_NAMES = frozenset(
    {
        # The password for the NOBYPASSRLS application role, required when
        # migrating a deployed environment.
        "CAIRN_APP_ROLE_PASSWORD",
        # Which role the platform connection uses, where it is not the default.
        "CAIRN_PLATFORM_ROLE",
    }
)


def documented_names() -> set[str]:
    """Every `CAIRN_*` name `.env.example` mentions anywhere.

    Deliberately not "every uncommented assignment": most entries there are
    commented out, because a `.env.example` whose values are live defaults is a
    file somebody copies to `.env` and deploys. Being *named* is the contract.
    """
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    found = set()
    for line in text.splitlines():
        for word in line.replace("=", " ").split():
            if not word.startswith(PREFIX):
                continue
            # These names appear in prose as well as in assignments, so trailing
            # punctuation is normal: "CAIRN_PLATFORM_DATABASE_URL," is the same
            # name as the entry two lines above it.
            found.add(word.strip("=#:,.;'\"`()[]"))
    return found


def setting_names() -> set[str]:
    return {PREFIX + name.upper() for name in Settings.model_fields}


class TestEverySettingIsDocumented:
    def test_the_example_file_exists_where_the_test_expects_it(self) -> None:
        assert ENV_EXAMPLE.is_file(), f"{ENV_EXAMPLE} is missing"

    def test_no_setting_is_missing_from_the_example(self) -> None:
        """A setting nobody documented is a setting nobody sets.

        The expensive version of this is not the missing feature — it is the
        one that half-works. A connector whose credential was never injected
        reports a healthy connection and delivers nothing, which the runbook
        calls the worst state to be in because it looks like a quiet week.
        """
        missing = sorted(setting_names() - documented_names())
        assert not missing, (
            f"{len(missing)} setting(s) exist in config.py and are undocumented "
            f"in .env.example: {', '.join(missing)}"
        )

    def test_the_example_invents_nothing(self) -> None:
        """The other direction, which is the more misleading one.

        A documented variable that no `Settings` field reads is a value somebody
        sets in a deployment and that the application silently ignores —
        `extra="ignore"` means there is no error, ever. Somebody setting
        `CAIRN_SMTP_PASWORD` gets a staging environment that cannot send mail
        and a configuration file that says it can.
        """
        # `VITE_*` belongs to the web app and is deliberately in the same file:
        # one place to look. Only the API's own namespace is checked here.
        invented = sorted(documented_names() - setting_names() - NON_SETTINGS_NAMES)
        assert not invented, (
            f"{len(invented)} name(s) documented in .env.example are read by "
            f"nothing in config.py: {', '.join(invented)}"
        )


class TestSecretsAreNotValued:
    """The file is an inventory, not a source of credentials."""

    #: Names whose value would be a credential if one were ever committed.
    SECRETISH = ("SECRET", "PASSWORD", "PRIVATE_KEY", "API_KEY", "ENCRYPTION_KEY", "TOKEN")

    @pytest.mark.parametrize("marker", SECRETISH)
    def test_no_secret_carries_a_value(self, marker: str) -> None:
        offenders = [
            line
            for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines()
            if not line.lstrip().startswith("#")
            and marker in line
            and "=" in line
            and line.split("=", 1)[1].strip()
        ]
        assert not offenders, (
            f"a secret-shaped name has a value in .env.example: {offenders}. "
            "The file is committed; anything after the '=' is published."
        )
