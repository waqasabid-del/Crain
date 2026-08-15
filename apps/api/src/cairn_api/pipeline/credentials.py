"""Google Cloud credentials for the model adapters.

Uses Application Default Credentials, not a configurable key file path: Cloud
Run supplies the attached service account with no secret to store or leak.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:  # pragma: no cover - typing only
    from google.auth.credentials import Credentials


class CredentialsError(RuntimeError):
    """No usable Google Cloud credentials are available."""


class TokenSource(Protocol):
    """A protocol so adapters can be tested without real credentials."""

    async def token(self) -> str: ...


class ApplicationDefaultCredentials:
    """Bearer tokens from Application Default Credentials. The refresh call
    is synchronous I/O, so it runs in a thread, not the event loop."""

    #: Seconds of margin before expiry, to cover clock skew vs. Google's clock.
    REFRESH_MARGIN_SECONDS = 60

    def __init__(
        self, *, scopes: tuple[str, ...] = ("https://www.googleapis.com/auth/cloud-platform",)
    ) -> None:
        self._scopes = scopes
        self._credentials: Credentials | None = None
        self._lock = asyncio.Lock()  # one refresh at a time

    async def token(self) -> str:
        async with self._lock:
            credentials = await asyncio.to_thread(self._ensure)
        token = getattr(credentials, "token", None)
        if not isinstance(token, str) or not token:
            msg = "Google credentials produced no access token"
            raise CredentialsError(msg)
        return token

    def _ensure(self) -> Credentials:
        try:
            import google.auth
            from google.auth.transport.requests import Request
        except ImportError as exc:  # pragma: no cover - dependency is declared
            msg = "google-auth is not installed; the Vertex adapters cannot authenticate"
            raise CredentialsError(msg) from exc

        if self._credentials is None:
            try:
                self._credentials, _ = google.auth.default(scopes=list(self._scopes))
            except Exception as exc:
                msg = (
                    "No Google Cloud credentials found. On Cloud Run attach a "
                    "service account; locally run `gcloud auth "
                    "application-default login`."
                )
                raise CredentialsError(msg) from exc

        if not self._credentials.valid or self._is_expiring(self._credentials):
            self._credentials.refresh(Request())  # type: ignore[no-untyped-call]
        return self._credentials

    def _is_expiring(self, credentials: Credentials) -> bool:
        expiry = getattr(credentials, "expiry", None)
        if expiry is None:
            return False
        from datetime import UTC, datetime, timedelta

        deadline = expiry.replace(tzinfo=UTC) - timedelta(seconds=self.REFRESH_MARGIN_SECONDS)
        return bool(datetime.now(UTC) >= deadline)


class StaticToken:
    """For tests and a proxy that injects auth upstream."""

    def __init__(self, value: str) -> None:
        self._value = value

    async def token(self) -> str:
        return self._value
