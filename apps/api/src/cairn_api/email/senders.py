"""The two backends: `ConsoleSender` for local development, `SmtpSender` for real delivery."""

from __future__ import annotations

import asyncio
import smtplib
from email.message import EmailMessage

import structlog

from cairn_api.email.message import Message

logger = structlog.get_logger(__name__)

#: Bounded: delivery happens inside a request, so an unbounded connect hangs it.
SMTP_TIMEOUT = 10.0


class ConsoleSender:
    """Write the message to the log instead of sending it.

    The one place a token and an address are deliberately logged, so a developer
    can follow the link out of a terminal. `config.py` refuses it when deployed.
    """

    async def send(self, message: Message) -> None:
        await logger.ainfo(
            "email.console",
            to=message.to,
            subject=message.subject,
            body=message.body,
        )


class SmtpSender:
    """Deliver over SMTP, using the standard library in a worker thread."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        sender: str,
        username: str | None = None,
        password: str | None = None,
    ) -> None:
        self._host = host
        self._port = port
        self._sender = sender
        self._username = username
        self._password = password

    async def send(self, message: Message) -> None:
        await asyncio.to_thread(self._send_blocking, message)

    def _send_blocking(self, message: Message) -> None:
        payload = EmailMessage()
        payload["From"] = self._sender
        payload["To"] = message.to
        payload["Subject"] = message.subject
        payload.set_content(message.body)

        with smtplib.SMTP(self._host, self._port, timeout=SMTP_TIMEOUT) as client:
            client.ehlo()
            if client.has_extn("starttls"):
                client.starttls()
                client.ehlo()
            if self._username and self._password:
                client.login(self._username, self._password)
            client.send_message(payload)
