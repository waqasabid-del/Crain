"""Backend selection, and the one way to send."""

from __future__ import annotations

import structlog

from cairn_api.config import Settings, get_settings
from cairn_api.email.message import EmailSender, Message
from cairn_api.email.senders import ConsoleSender, SmtpSender

logger = structlog.get_logger(__name__)


class EmailConfigurationError(RuntimeError):
    """The configured backend cannot be used in this environment."""


def build_sender(settings: Settings | None = None) -> EmailSender:
    """Construct the sender for this process."""
    settings = settings or get_settings()

    if settings.email_backend == "console":
        if settings.is_deployed:
            msg = (
                "email_backend is 'console' but CAIRN_ENVIRONMENT is "
                f"'{settings.environment}'. Invitations and verification links "
                "would be written to the log and reach nobody. Set "
                "CAIRN_EMAIL_BACKEND=smtp."
            )
            raise EmailConfigurationError(msg)

        logger.info("email.using_console_sender", environment=settings.environment)
        return ConsoleSender()

    if not settings.smtp_host:
        msg = (
            "email_backend is 'smtp' but CAIRN_SMTP_HOST is not set. Nothing "
            "would be delivered, and the failure would be one warning per "
            "message rather than a refusal to start."
        )
        raise EmailConfigurationError(msg)

    logger.info("email.using_smtp_sender", host=settings.smtp_host, port=settings.smtp_port)
    return SmtpSender(
        host=settings.smtp_host,
        port=settings.smtp_port,
        sender=settings.email_from,
        username=settings.smtp_username,
        password=(settings.smtp_password.get_secret_value() if settings.smtp_password else None),
    )


async def send_best_effort(sender: EmailSender, message: Message, *, event: str) -> bool:
    """Send, reporting failure rather than raising it.

    Every exception is swallowed on purpose: the row this announces is already
    committed, and losing a signup to a brief outage is worse than a resent link.
    """
    try:
        await sender.send(message)
    except Exception as exc:
        # The class name, not the traceback: an SMTP error carries the
        # recipient address, and this log store holds no addresses.
        await logger.awarning(f"{event}.email_failed", error=type(exc).__name__)
        return False
    return True
