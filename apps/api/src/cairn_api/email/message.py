"""What gets sent, and the interface that sends it. Plain text only."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from cairn_api.config import Settings


@dataclass(frozen=True, slots=True)
class Message:
    to: str
    subject: str
    body: str


class EmailSender(Protocol):
    async def send(self, message: Message) -> None: ...


def _link(settings: Settings, path: str, token: str) -> str:
    return f"{settings.public_app_url.rstrip('/')}/{path}?token={token}"


def verification_message(settings: Settings, *, to: str, token: str) -> Message:
    """The link that proves control of an address."""
    url = _link(settings, "verify", token)
    return Message(
        to=to,
        subject="Confirm your CAIRN email address",
        body=(
            "Welcome to CAIRN.\n\n"
            f"Confirm this address to finish setting up your account:\n\n{url}\n\n"
            "If you did not create a CAIRN account, ignore this message.\n"
        ),
    )


def password_reset_message(settings: Settings, *, to: str, token: str) -> Message:
    """The link that redeems a password reset. Silent about whether the
    account exists — this is only ever called for one that does — and the
    body itself says nothing an interceptor couldn't already infer from
    having the link."""
    url = _link(settings, "reset-password", token)
    return Message(
        to=to,
        subject="Reset your CAIRN password",
        body=(
            "We received a request to reset your CAIRN password.\n\n"
            f"Choose a new one here:\n\n{url}\n\n"
            "This link expires in 30 minutes and works once. If you did not "
            "request this, ignore this message — your password will not change.\n"
        ),
    )


def invitation_message(settings: Settings, *, to: str, token: str, workspace_name: str) -> Message:
    """The link that redeems an invitation. The inviter is deliberately not named."""
    url = _link(settings, "invite", token)
    return Message(
        to=to,
        subject=f"You have been invited to {workspace_name} on CAIRN",
        body=(
            f"You have been invited to join the {workspace_name} workspace on CAIRN.\n\n"
            f"Accept the invitation here:\n\n{url}\n\n"
            "If you were not expecting this, ignore this message.\n"
        ),
    )
