"""Outbound email. Callers use `build_sender` and `send_best_effort`, never a sender directly."""

from __future__ import annotations

from cairn_api.email.factory import EmailConfigurationError, build_sender, send_best_effort
from cairn_api.email.message import (
    EmailSender,
    Message,
    invitation_message,
    password_reset_message,
    verification_message,
)
from cairn_api.email.senders import ConsoleSender, SmtpSender

__all__ = [
    "ConsoleSender",
    "EmailConfigurationError",
    "EmailSender",
    "Message",
    "SmtpSender",
    "build_sender",
    "invitation_message",
    "password_reset_message",
    "send_best_effort",
    "verification_message",
]
