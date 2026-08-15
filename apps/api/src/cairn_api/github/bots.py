"""Bot identification.

Automated accounts out-commit humans, so counting them in attribution makes
humans look idle. AI agents (md/01 §5.4) are recognised only by identifiable
login, never by heuristically scoring a diff (md/05).
"""

from __future__ import annotations

from collections.abc import Iterable

from cairn_api.github.trailers import Contributor

#: GitHub App actors commit under a login ending in `[bot]`.
BOT_LOGIN_SUFFIX = "[bot]"

#: Automation without the `[bot]` suffix. Deliberately short — a long
#: speculative list risks mis-classifying a human.
KNOWN_BOT_LOGINS = frozenset(
    {
        "dependabot",
        "dependabot-preview",
        "renovate",
        "renovate-bot",
        "github-actions",
        "greenkeeper",
        "snyk-bot",
        "imgbot",
        "codecov",
        "semantic-release-bot",
        "web-flow",  # GitHub's own committer identity for web-UI edits
    }
)

#: Addresses used by automation that has no meaningful login.
KNOWN_BOT_EMAILS = frozenset(
    {
        "noreply@github.com",
        "action@github.com",
        "actions@github.com",
        "support@github.com",
    }
)

#: Agent actors whose commits are reliably machine-authored.
AI_AGENT_LOGINS = frozenset(
    {
        "github-copilot",
        "copilot-swe-agent",
        "devin-ai-integration",
        "cursoragent",
        "claude",
    }
)


def _base_login(login: str) -> str:
    lowered = login.strip().lower()
    if lowered.endswith(BOT_LOGIN_SUFFIX):
        return lowered[: -len(BOT_LOGIN_SUFFIX)]
    return lowered


def is_bot_login(login: str | None, *, custom: Iterable[str] = ()) -> bool:
    """Whether a GitHub login belongs to automation. `custom` is per-tenant additions."""
    if not login:
        return False

    lowered = login.strip().lower()
    if lowered.endswith(BOT_LOGIN_SUFFIX):
        return True

    base = _base_login(lowered)
    if base in KNOWN_BOT_LOGINS or base in AI_AGENT_LOGINS:
        return True

    return any(base == entry.strip().lower() for entry in custom)


def is_bot_email(email: str | None) -> bool:
    """Exact match only — a "contains bot" pattern would misclassify `robert@…`."""
    if not email:
        return False
    return email.strip().lower() in KNOWN_BOT_EMAILS


def is_bot(contributor: Contributor, *, custom: Iterable[str] = ()) -> bool:
    """Whether a contributor is automation rather than a person."""
    return is_bot_login(contributor.login, custom=custom) or is_bot_email(contributor.email)


def is_ai_agent(contributor: Contributor) -> bool:
    """Narrower than `is_bot`: Dependabot is a bot, not an agent."""
    return _base_login(contributor.login or "") in AI_AGENT_LOGINS


def partition(
    contributors: Iterable[Contributor], *, custom_bots: Iterable[str] = ()
) -> tuple[list[Contributor], list[Contributor]]:
    """Split into `(people, bots)`; bots are returned, not discarded."""
    custom = list(custom_bots)
    people: list[Contributor] = []
    bots: list[Contributor] = []

    for contributor in contributors:
        (bots if is_bot(contributor, custom=custom) else people).append(contributor)

    return people, bots
