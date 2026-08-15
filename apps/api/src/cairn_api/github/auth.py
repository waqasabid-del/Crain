"""GitHub App authentication.

The App JWT is exchanged for an installation access token, scoped to one
installation and expiring in an hour. Tokens are cached until shortly before
expiry. The private key never leaves this module — downstream sees only the
installation token, which bounds the blast radius of a logging mistake.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import httpx
import jwt
import structlog

logger = structlog.get_logger(__name__)

GITHUB_API = "https://api.github.com"

#: 9 min, not GitHub's 10 min max: clock skew could put `iat` in the future.
JWT_LIFETIME_SECONDS = 9 * 60

#: Backdate `iat` to absorb clock skew in the other direction.
JWT_CLOCK_SKEW_SECONDS = 60

#: Refresh this long before expiry so a token cannot expire mid-request.
TOKEN_REFRESH_MARGIN_SECONDS = 300


class GitHubAuthError(RuntimeError):
    """Authentication failed in a way that retrying will not fix."""


@dataclass(frozen=True, slots=True)
class InstallationToken:
    """A short-lived credential for one installation."""

    token: str
    expires_at: float

    @property
    def is_usable(self) -> bool:
        return time.time() < self.expires_at - TOKEN_REFRESH_MARGIN_SECONDS


def mint_app_jwt(*, app_id: str, private_key: str, now: float | None = None) -> str:
    """Sign an App JWT. `now` is injected in tests to pin clock-dependent crypto."""
    issued = int(now if now is not None else time.time())
    payload = {
        "iat": issued - JWT_CLOCK_SKEW_SECONDS,
        "exp": issued + JWT_LIFETIME_SECONDS,
        "iss": app_id,
    }
    try:
        return jwt.encode(payload, private_key, algorithm="RS256")
    except Exception as exc:
        # Cause kept out of the message: PyJWT error strings can include key
        # material, and this message is logged.
        msg = "Could not sign the GitHub App JWT; check CAIRN_GITHUB_PRIVATE_KEY"
        raise GitHubAuthError(msg) from exc


class InstallationTokenCache:
    """Mints and caches installation tokens, in-memory and per-process.

    Deliberately not shared across instances: that would put a credential in a
    shared store, and tokens are cheap to mint.
    """

    def __init__(
        self,
        *,
        app_id: str,
        private_key: str,
        client: httpx.AsyncClient | None = None,
        base_url: str = GITHUB_API,
    ) -> None:
        self._app_id = app_id
        self._private_key = private_key
        self._client = client
        self._base_url = base_url.rstrip("/")
        self._tokens: dict[int, InstallationToken] = {}

    async def token_for(self, installation_id: int) -> str:
        """Return a usable token, minting one if needed."""
        cached = self._tokens.get(installation_id)
        if cached is not None and cached.is_usable:
            return cached.token

        minted = await self._mint(installation_id)
        self._tokens[installation_id] = minted
        return minted.token

    async def _mint(self, installation_id: int) -> InstallationToken:
        app_jwt = mint_app_jwt(app_id=self._app_id, private_key=self._private_key)
        client = self._client or httpx.AsyncClient(timeout=30)
        owns_client = self._client is None

        try:
            response = await client.post(
                f"{self._base_url}/app/installations/{installation_id}/access_tokens",
                headers={
                    "Authorization": f"Bearer {app_jwt}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
        finally:
            if owns_client:
                await client.aclose()

        if response.status_code == httpx.codes.NOT_FOUND:
            # App uninstalled: not retryable, run should stop rather than back off.
            msg = f"Installation {installation_id} no longer exists"
            raise GitHubAuthError(msg)
        if response.status_code >= httpx.codes.BAD_REQUEST:
            # Body omitted: GitHub echoes request details on some auth errors.
            msg = (
                f"GitHub refused an installation token for {installation_id} "
                f"({response.status_code})"
            )
            raise GitHubAuthError(msg)

        body = response.json()
        token = body.get("token")
        if not isinstance(token, str):
            msg = "GitHub returned no token"
            raise GitHubAuthError(msg)

        expires_at = _parse_expiry(body.get("expires_at"))
        await logger.ainfo(
            "github.installation_token_minted",
            installation_id=installation_id,
            # Never the token: log retention outlives an hour-lived credential.
            expires_in_seconds=round(expires_at - time.time()),
        )
        return InstallationToken(token=token, expires_at=expires_at)

    def forget(self, installation_id: int) -> None:
        """Drop a cached token. Called after a 401, so a rejected credential is not reused."""
        self._tokens.pop(installation_id, None)


def _parse_expiry(raw: object) -> float:
    """Read GitHub's expiry timestamp, falling back to one hour.

    Underestimating costs one extra mint; overestimating costs a 401 mid-walk.
    """
    from datetime import datetime

    if isinstance(raw, str):
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
        except ValueError:
            pass
    return time.time() + 3600
