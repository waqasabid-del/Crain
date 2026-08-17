"""Send one real message, to close the email release gate.

    uv run python -m cairn_api.email.probe --to you@example.com

The gate this closes cannot be closed any other way. Configuration proves a
relay was *named*; it does not prove the credentials are right, that the relay
accepts CAIRN's envelope sender, that the message is not silently dropped for
SPF or DKIM, or that it lands anywhere but a spam folder. Every one of those
fails after startup, on the first invitation a real customer never receives.

So this sends an actual message through the configured sender and reports what
happened. It refuses to run on the console backend, because "written to the log"
is exactly the outcome the gate exists to rule out — a probe that succeeded
against `ConsoleSender` would be the false pass this is written to prevent.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from cairn_api.config import get_settings
from cairn_api.email.factory import build_sender
from cairn_api.email.message import Message
from cairn_api.email.senders import ConsoleSender

SUBJECT = "CAIRN delivery probe"

BODY = (
    "This is a delivery probe from CAIRN.\n\n"
    "If you are reading it in an inbox, transactional email works: the relay "
    "accepted the message, authentication passed, and it was not filtered.\n\n"
    "Nothing was recorded about you, and this address was not stored.\n"
)


async def probe(recipient: str) -> int:
    settings = get_settings()
    sender = build_sender(settings)

    if isinstance(sender, ConsoleSender):
        print(
            "REFUSED: the console backend writes to the log and delivers nothing.\n"
            "         A pass here would mean nothing. Set CAIRN_EMAIL_BACKEND=smtp "
            "with\n         CAIRN_SMTP_HOST, CAIRN_SMTP_USERNAME and CAIRN_SMTP_PASSWORD.",
            file=sys.stderr,
        )
        return 2

    try:
        await sender.send(Message(to=recipient, subject=SUBJECT, body=BODY))
    # Broad on purpose: a relay can fail with an SMTP error, a TLS error, a DNS
    # error or a timeout, and the operator needs to be told which rather than
    # given a traceback.
    except Exception as error:
        print(f"FAILED: the relay refused the message ({type(error).__name__}).", file=sys.stderr)
        return 1

    print(
        f"SENT to {recipient} via {settings.smtp_host}.\n"
        "The gate is closed only when it ARRIVES. Check the inbox, and check spam —\n"
        "a relay accepting a message is not the same as a person receiving one."
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Send one real message to verify delivery.")
    parser.add_argument("--to", required=True, help="An address you can actually read.")
    return asyncio.run(probe(parser.parse_args().to))


if __name__ == "__main__":
    sys.exit(main())
