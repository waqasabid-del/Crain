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
