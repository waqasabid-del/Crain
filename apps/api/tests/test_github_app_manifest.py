"""The App CAIRN asks GitHub to create is read-only, and provably so.

`scripts/create_github_app.py` declares the permissions GitHub builds the App
from. That declaration is the only thing standing between "read-only" as a claim
in the marketing sense and read-only as a property of the installation, because
once an App exists with a write permission, every repository it is installed on
has granted it — silently, and to a product that promises the opposite.

A checklist cannot hold this. A test can.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "create_github_app.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("create_github_app", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def script() -> ModuleType:
    return _load()


class TestThePermissionsAreReadOnly:
    def test_every_permission_is_read(self, script: ModuleType) -> None:
        """**The product invariant, as an assertion.**

        `write` or `admin` on any resource makes the App capable of changing a
        customer's repository. CAIRN never writes to a source; a permission it
        does not need is one an attacker who reaches an installation token
        inherits.
        """
        offenders = {name: level for name, level in script.PERMISSIONS.items() if level != "read"}
        assert not offenders, f"non-read permission in the manifest: {offenders}"

    def test_it_asks_for_exactly_what_the_code_reads(self, script: ModuleType) -> None:
        """Not a superset. An unused permission is granted access nobody needs
        and nobody is watching, and it survives every later review because it
        was never the thing that broke."""
        assert set(script.PERMISSIONS) == {"contents", "pull_requests", "issues", "metadata"}

    def test_no_account_or_organisation_permissions(self, script: ModuleType) -> None:
        """Nothing in `cairn_api` calls an endpoint that needs one, and asking
        for organisation access to receive a push reads - correctly - as a
        product that wants more than it says."""
        forbidden = {"members", "organization_administration", "administration", "emails"}
        assert not forbidden & set(script.PERMISSIONS)


class TestTheEventsMatchWhatIsHandled:
    def test_push_is_subscribed(self, script: ModuleType) -> None:
        """The only event carrying commits, and therefore the only one that
        produces an attributed fact today."""
        assert "push" in script.EVENTS

    def test_every_event_becomes_evidence_or_carries_commits(self, script: ModuleType) -> None:
        """A subscription to an event nothing reads is noise arriving at the one
        unauthenticated endpoint in the service."""
        assert set(script.EVENTS) <= {"push", "pull_request", "issues", "issue_comment"}


class TestTheManifestIsWellFormed:
    def test_it_is_json_serialisable_and_private(self, script: ModuleType) -> None:
        """`public: true` would let anybody install CAIRN on their repositories."""
        built = script.manifest(
            name="CAIRN (test)",
            webhook_url="https://example.test/hook",
            app_url="https://example.test",
        )
        json.dumps(built)
        assert built["public"] is False

    def test_the_webhook_url_is_the_one_passed(self, script: ModuleType) -> None:
        """A manifest that quietly rewrote this would create an App delivering
        somewhere nobody chose."""
        built = script.manifest(
            name="x", webhook_url="https://smee.io/abc", app_url="https://example.test"
        )
        assert built["hook_attributes"] == {"url": "https://smee.io/abc", "active": True}


class TestSecretsAreNotPrinted:
    def test_the_script_never_prints_the_credentials(self) -> None:
        """The credentials exist in one place: `.env`.

        GitHub returns the private key exactly once. A `print` of the conversion
        payload would put it in a terminal history and, in a session like the
        one this was built in, in a transcript.
        """
        source = SCRIPT.read_text(encoding="utf-8")
        for secret_field in ("pem", "webhook_secret"):
            assert f"print({secret_field}" not in source
            assert f'print(f"{{{secret_field}' not in source
        # The payload dict itself must never be printed whole.
        assert "print(converted)" not in source
        assert "print(_Handler.payload)" not in source
