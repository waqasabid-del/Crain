"""The GraphQL client used for bulk history.

GraphQL rather than REST for backfill (md/01 §4.2): one query gets a page of
commits with authors and co-author trailers, where REST needs one call per
commit. Every query asks for its own `rateLimit` block so cost is measured,
not estimated. Pages are 100, not the default 30, at no extra point cost.

Secondary limits are handled separately from primary ones: exhausting points
is a schedule (park and resume at reset); a secondary limit means slow down
now, has no reliable reset time, and is what GitHub escalates against.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import httpx
import structlog

from cairn_api.github.auth import GITHUB_API, InstallationTokenCache
from cairn_api.github.budget import (
    BudgetExhaustedError,
    RateBudget,
    parse_rate_limit,
)

logger = structlog.get_logger(__name__)

#: Maximum GraphQL page size. The default is 30.
PAGE_SIZE = 100

#: Commits with everything attribution needs, in one request. `message` is
#: fetched in full, not `messageHeadline` — co-author trailers live in the body.
COMMIT_HISTORY_QUERY = """
query CommitHistory($owner: String!, $name: String!, $since: GitTimestamp!,
                    $pageSize: Int!, $after: String) {
  rateLimit { limit cost remaining resetAt }
  repository(owner: $owner, name: $name) {
    defaultBranchRef {
      target {
        ... on Commit {
          history(since: $since, first: $pageSize, after: $after) {
            pageInfo { hasNextPage endCursor }
            nodes {
              oid
              message
              committedDate
              author { name email user { login } }
            }
          }
        }
      }
    }
  }
}
"""


class GitHubApiError(RuntimeError):
    """A GraphQL request failed."""


class SecondaryRateLimitError(RuntimeError):
    """A secondary limit was hit.

    Distinct from `BudgetExhaustedError`: points exhaustion is a schedule
    (park and resume), a secondary limit means slow down immediately.
    """

    def __init__(self, retry_after_seconds: float) -> None:
        super().__init__(f"Secondary rate limit; back off {retry_after_seconds:.0f}s")
        self.retry_after_seconds = retry_after_seconds


@dataclass(frozen=True, slots=True)
class CommitPage:
    """One page of commit history."""

    commits: list[dict[str, Any]]
    end_cursor: str | None
    has_next_page: bool


class GitHubGraphQLClient:
    """Reads history for one installation, accounting as it goes."""

    def __init__(
        self,
        *,
        tokens: InstallationTokenCache,
        client: httpx.AsyncClient,
        base_url: str = GITHUB_API,
    ) -> None:
        self._tokens = tokens
        self._client = client
        self._base_url = base_url.rstrip("/")
        self._budgets: dict[int, RateBudget] = {}  # per installation; see budget.py

    def budget_for(self, installation_id: int) -> RateBudget:
        return self._budgets.setdefault(installation_id, RateBudget())

    async def fetch_commits(
        self,
        *,
        installation_id: int,
        owner: str,
        name: str,
        since: str,
        after: str | None = None,
    ) -> CommitPage:
        """Fetch one page of commit history.

        Raises:
            BudgetExhaustedError: No usable points. Park the run.
            SecondaryRateLimitError: Slow down now.
            GitHubApiError: Anything else.
        """
        budget = self.budget_for(installation_id)
        if not budget.can_afford_next():
            # Checked before the request: asking anyway would spend the
            # reserve live traffic depends on.
            raise BudgetExhaustedError(budget.seconds_until_reset)

        payload = {
            "query": COMMIT_HISTORY_QUERY,
            "variables": {
                "owner": owner,
                "name": name,
                "since": since,
                "pageSize": PAGE_SIZE,
                "after": after,
            },
        }
        body = await self._post(installation_id, payload)

        rate_block = body.get("data", {}).get("rateLimit")
        if isinstance(rate_block, dict):
            limit, remaining, reset_at, cost = parse_rate_limit(rate_block)
            budget.observe(limit=limit, remaining=remaining, reset_at=reset_at, cost=cost)

        return _read_history(body)

    async def _post(self, installation_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        token = await self._tokens.token_for(installation_id)
        response = await self._client.post(
            f"{self._base_url}/graphql",
            json=payload,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )

        if response.status_code == httpx.codes.UNAUTHORIZED:
            # Cached token rejected; drop it so the retry mints a fresh one.
            self._tokens.forget(installation_id)
            msg = "GitHub rejected the installation token"
            raise GitHubApiError(msg)

        if response.status_code in {httpx.codes.FORBIDDEN, httpx.codes.TOO_MANY_REQUESTS}:
            raise SecondaryRateLimitError(_retry_after(response))

        if response.status_code >= httpx.codes.BAD_REQUEST:
            msg = f"GitHub GraphQL returned {response.status_code}"
            raise GitHubApiError(msg)

        body: dict[str, Any] = response.json()

        # GraphQL returns 200 with an `errors` array; treating 200 as success
        # is the classic client bug — the walk appears to succeed but the
        # cursor never advances.
        errors = body.get("errors")
        if errors:
            first = errors[0] if isinstance(errors, list) and errors else {}
            message = first.get("message") if isinstance(first, dict) else str(errors)
            if isinstance(message, str) and "rate limit" in message.lower():
                raise SecondaryRateLimitError(60.0)
            msg = f"GitHub GraphQL error: {message}"
            raise GitHubApiError(msg)

        return body


def _retry_after(response: httpx.Response) -> float:
    """How long GitHub asked us to wait: `Retry-After`, then time to primary
    window reset, then a minute. Guessing short risks escalating the limit.
    """
    header = response.headers.get("retry-after")
    if header:
        try:
            return float(header)
        except ValueError:
            pass

    reset = response.headers.get("x-ratelimit-reset")
    if reset:
        try:
            import time

            return max(0.0, float(reset) - time.time())
        except ValueError:
            pass

    return 60.0


def _read_history(body: dict[str, Any]) -> CommitPage:
    """Pull the commit page out of a GraphQL response.

    Read defensively at every level: an empty repository returns
    `defaultBranchRef: null`, and that's normal, not an error.
    """
    repository = (body.get("data") or {}).get("repository") or {}
    branch = repository.get("defaultBranchRef") or {}
    target = branch.get("target") or {}
    history = target.get("history") or {}

    nodes = history.get("nodes")
    page_info = history.get("pageInfo") or {}

    return CommitPage(
        commits=[node for node in nodes if isinstance(node, dict)]
        if isinstance(nodes, list)
        else [],
        end_cursor=page_info.get("endCursor"),
        has_next_page=bool(page_info.get("hasNextPage")),
    )


def to_commit_payload(node: dict[str, Any]) -> dict[str, Any]:
    """Reshape a GraphQL commit into the shape the webhook path already uses.

    So attribution has one implementation, not a second parser for the same
    commit arriving by a different route.
    """
    author = node.get("author") or {}
    user = author.get("user") or {}
    return {
        "id": node.get("oid"),
        "message": node.get("message"),
        "timestamp": node.get("committedDate"),
        "author": {
            "name": author.get("name"),
            "email": author.get("email"),
            "username": user.get("login"),
        },
    }


async def sleep_for_backoff(seconds: float) -> None:
    """Wait out a secondary limit. Its own function so tests can patch it and
    the wait is visible in the log."""
    await logger.awarning("github.secondary_rate_limit_backoff", seconds=round(seconds, 1))
    await asyncio.sleep(seconds)
