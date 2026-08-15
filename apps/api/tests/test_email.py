"""Email delivery, and the two things it must never do.

Closes audit finding P1-5: an invitation reached nobody, so a team could not be
onboarded without database access.

The invariants under test are that a send failure never costs a signup or an
invitation, and that no token or address reaches the log — the console backend,
which deliberately logs both, is refused outside local development.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

import pytest
from cairn_api.config import Settings
from cairn_api.db.auth_models import Invitation
from cairn_api.email import (
    ConsoleSender,
    EmailConfigurationError,
    Message,
    SmtpSender,
    build_sender,
    invitation_message,
    send_best_effort,
    verification_message,
)
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# Every password and token here is a literal by necessity.
# ruff: noqa: S105, S106
PASSWORD = "correct-horse-battery"

APP_URL = "http://localhost:3000"


def _settings(**overrides: object) -> Settings:
    """Build settings without consulting the environment or a .env file."""
    values: dict[str, object] = {
        "environment": "local",
        "public_app_url": APP_URL,
    }
    values.update(overrides)
    return Settings.model_validate(values)


class Recorder:
    """A sender that keeps what it was given, or refuses everything."""

    def __init__(self, *, fails: bool = False) -> None:
        self.sent: list[Message] = []
        self.fails = fails

    async def send(self, message: Message) -> None:
        if self.fails:
            msg = "relay refused the connection"
            raise ConnectionError(msg)
        self.sent.append(message)


class LogSink(logging.Handler):
    """Every record emitted after it is installed.

    Installed after `create_app`, which reconfigures the root logger and would
    otherwise discard pytest's own capture handler.
    """

    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)

    @property
    def text(self) -> str:
        return "\n".join(record.getMessage() for record in self.records)


@pytest.fixture
def recorder(app: FastAPI) -> Recorder:
    """Substitute a recording sender on the app under test."""
    instance = Recorder()
    app.state.email_sender = instance
    return instance


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


async def _signup(client: AsyncClient, *, email: str | None = None) -> dict[str, Any]:
    response = await client.post(
        "/v1/auth/signup",
        json={
            "email": email or f"{_unique('user')}@example.com",
            "password": PASSWORD,
            "workspaceName": "Acme",
            "workspaceSlug": _unique("ws"),
        },
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


class TestBackendSelection:
    def test_console_is_the_local_default(self) -> None:
        assert isinstance(build_sender(_settings()), ConsoleSender)

    def test_smtp_is_chosen_when_configured(self) -> None:
        sender = build_sender(_settings(email_backend="smtp", smtp_host="relay.example.com"))

        assert isinstance(sender, SmtpSender)

    def test_smtp_without_a_host_refuses_to_start(self) -> None:
        # One warning per undelivered message is not a signal anyone acts on.
        with pytest.raises(EmailConfigurationError, match="CAIRN_SMTP_HOST"):
            build_sender(_settings(email_backend="smtp"))

    @pytest.mark.parametrize("environment", ["staging", "production"])
    def test_a_deployed_environment_refuses_the_console_backend(self, environment: str) -> None:
        # Settings validation is the primary guard, so the process cannot even
        # be configured this way.
        with pytest.raises(ValueError, match="console"):
            Settings.model_validate(
                {
                    "environment": environment,
                    "database_url": "postgresql+asyncpg://cairn:s3cret@10.0.0.4:5432/cairn",
                    "platform_database_url": "postgresql+asyncpg://cairn:s3cret@10.0.0.4:5432/c",
                    "cors_allowed_origins": ("https://app.example.com",),
                    "github_webhook_secret": "a-real-secret",
                    "email_backend": "console",
                }
            )

    def test_the_factory_refuses_it_too(self) -> None:
        # Defended twice: the factory is reachable from a worker or a script
        # that built settings some other way.
        deployed = Settings.model_construct(environment="production", email_backend="console")

        with pytest.raises(EmailConfigurationError, match="console"):
            build_sender(deployed)


class TestMessages:
    def test_the_verification_message_carries_the_link(self) -> None:
        message = verification_message(_settings(), to="someone@example.com", token="tok-123")

        assert message.to == "someone@example.com"
        assert f"{APP_URL}/verify?token=tok-123" in message.body

    def test_the_invitation_message_carries_the_link_and_the_workspace(self) -> None:
        message = invitation_message(
            _settings(), to="colleague@example.com", token="tok-456", workspace_name="Acme"
        )

        assert f"{APP_URL}/invite?token=tok-456" in message.body
        assert "Acme" in message.subject

    def test_a_trailing_slash_does_not_double(self) -> None:
        message = verification_message(
            _settings(public_app_url=f"{APP_URL}/"), to="a@example.com", token="t"
        )

        assert "//verify" not in message.body


class TestBestEffort:
    async def test_a_failure_is_reported_rather_than_raised(self) -> None:
        sender = Recorder(fails=True)

        sent = await send_best_effort(
            sender, Message(to="a@example.com", subject="s", body="b"), event="test"
        )

        assert sent is False

    async def test_a_success_is_reported(self) -> None:
        sender = Recorder()

        assert await send_best_effort(
            sender, Message(to="a@example.com", subject="s", body="b"), event="test"
        )


class TestSignupDelivery:
    pytestmark = pytest.mark.integration

    async def test_one_verification_message_with_a_link(
        self, client: AsyncClient, recorder: Recorder
    ) -> None:
        email = f"{_unique('verify')}@example.com"

        await _signup(client, email=email)

        assert len(recorder.sent) == 1
        assert recorder.sent[0].to == email
        assert f"{APP_URL}/verify?token=" in recorder.sent[0].body

    async def test_resending_issues_a_second_message(
        self, client: AsyncClient, recorder: Recorder
    ) -> None:
        await _signup(client)

        response = await client.post("/v1/auth/resend-verification")

        assert response.status_code == 202
        assert len(recorder.sent) == 2
        assert recorder.sent[1].body != recorder.sent[0].body

    async def test_a_failed_send_still_creates_the_account(
        self, app: FastAPI, client: AsyncClient
    ) -> None:
        # The whole point of best-effort delivery: an unreachable relay must not
        # cost somebody their account.
        app.state.email_sender = Recorder(fails=True)
        email = f"{_unique('failed')}@example.com"

        body = await _signup(client, email=email)

        workspace_id = body["workspaces"][0]["workspace"]["id"]
        signed_in = await client.get(f"/v1/workspaces/{workspace_id}")
        assert signed_in.status_code == 200

    async def test_no_token_or_address_is_logged(
        self, app: FastAPI, client: AsyncClient, recorder: Recorder
    ) -> None:
        sink = LogSink()
        root = logging.getLogger()
        root.addHandler(sink)
        email = f"{_unique('quiet')}@example.com"
        try:
            await _signup(client, email=email)
        finally:
            root.removeHandler(sink)

        token = recorder.sent[0].body.split("token=")[1].strip()
        assert token not in sink.text
        assert email not in sink.text


class TestInvitationDelivery:
    pytestmark = pytest.mark.integration

    async def test_one_invitation_message_with_a_link(
        self, client: AsyncClient, recorder: Recorder
    ) -> None:
        body = await _signup(client)
        workspace_id = body["workspaces"][0]["workspace"]["id"]
        recorder.sent.clear()
        invited = f"{_unique('colleague')}@example.com"

        response = await client.post(
            f"/v1/workspaces/{workspace_id}/invitations",
            json={"email": invited, "role": "member"},
        )

        assert response.status_code == 201, response.text
        assert len(recorder.sent) == 1
        assert recorder.sent[0].to == invited
        assert f"{APP_URL}/invite?token=" in recorder.sent[0].body
        assert "Acme" in recorder.sent[0].subject

    async def test_a_failed_send_still_issues_the_invitation(
        self, app: FastAPI, client: AsyncClient, platform: AsyncSession
    ) -> None:
        app.state.email_sender = Recorder(fails=True)
        body = await _signup(client)
        workspace_id = body["workspaces"][0]["workspace"]["id"]
        invited = f"{_unique('lost')}@example.com"

        response = await client.post(
            f"/v1/workspaces/{workspace_id}/invitations",
            json={"email": invited, "role": "member"},
        )

        assert response.status_code == 201, response.text
        row = await platform.scalar(select(Invitation).where(Invitation.email == invited))
        assert row is not None
