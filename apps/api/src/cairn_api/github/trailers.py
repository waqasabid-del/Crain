"""Commit message trailers, chiefly ``Co-authored-by``.

Squash merges collapse authorship to whoever opened the PR; GitHub's
``Co-authored-by`` trailer recovers the rest, read as attribution data rather
than commit-message text (md/05). An unparseable address is discarded rather
than guessed at: a wrong attribution is worse than a missing one.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

#: `Co-authored-by: Name <email>`. Anchored to line start so a quoted trailer
#: inside a commit body isn't read as attribution.
_TRAILER = re.compile(
    r"^[ \t]*co-authored-by[ \t]*:[ \t]*(?P<name>[^<]*?)[ \t]*<(?P<email>[^>]+)>[ \t]*$",
    re.IGNORECASE | re.MULTILINE,
)

#: GitHub noreply addresses. `[`/`]` admitted for app actors, e.g.
#: `dependabot[bot]@users.noreply.github.com` (md/01 §5.2).
_NOREPLY = re.compile(
    r"^(?:(?P<user_id>\d+)\+)?(?P<login>[A-Za-z0-9](?:[A-Za-z0-9\-\[\]]*[A-Za-z0-9\]])?)"
    r"@users\.noreply\.github\.com$",
    re.IGNORECASE,
)

#: RFC 5321 bound; longer is malformed/hostile.
MAX_EMAIL_LENGTH = 254


@dataclass(frozen=True, slots=True)
class Contributor:
    """A *claim* about a person, not a person; resolved by `identity/resolution.py`."""

    email: str
    name: str | None = None
    login: str | None = None

    @property
    def is_noreply(self) -> bool:
        return self.email.endswith("@users.noreply.github.com")


def normalise_email(raw: str) -> str | None:
    """Canonicalise an address, or None if unusable. Not full RFC 5322 — that
    accepts things no mail system does and rejects things Git happily writes.
    """
    candidate = raw.strip().lower()
    if not candidate or len(candidate) > MAX_EMAIL_LENGTH:
        return None
    local, separator, domain = candidate.partition("@")
    if not separator or not local or "." not in domain or domain.startswith("."):
        return None
    return candidate


def login_from_noreply(email: str) -> str | None:
    """Recover a GitHub login from a privacy address, if it is one."""
    match = _NOREPLY.match(email)
    return match.group("login").lower() if match else None


def parse_coauthors(message: str | None) -> list[Contributor]:
    """Co-authors in trailer order, deduplicated by address."""
    if not message:
        return []

    seen: set[str] = set()
    contributors: list[Contributor] = []

    for match in _TRAILER.finditer(message):
        email = normalise_email(match.group("email"))
        if email is None or email in seen:
            continue
        seen.add(email)

        name = match.group("name").strip() or None
        contributors.append(Contributor(email=email, name=name, login=login_from_noreply(email)))

    return contributors


def author_of(commit: Mapping[str, Any]) -> Contributor | None:
    """Follows `author`, not `committer` — on a rebase/squash the committer
    is whoever ran the command.
    """
    author = commit.get("author")
    if not isinstance(author, dict):
        return None

    raw_email = author.get("email")
    if not isinstance(raw_email, str):
        return None

    email = normalise_email(raw_email)
    if email is None:
        return None

    raw_name = author.get("name")
    raw_login = author.get("username")

    return Contributor(
        email=email,
        name=raw_name.strip() if isinstance(raw_name, str) and raw_name.strip() else None,
        login=(raw_login.lower() if isinstance(raw_login, str) and raw_login else None)
        or login_from_noreply(email),
    )


def contributors_of(commit: Mapping[str, Any]) -> list[Contributor]:
    """Author first, then co-authors in trailer order, deduplicated by address."""
    found: list[Contributor] = []
    seen: set[str] = set()

    author = author_of(commit)
    if author is not None:
        found.append(author)
        seen.add(author.email)

    message = commit.get("message")
    for contributor in parse_coauthors(message if isinstance(message, str) else None):
        if contributor.email not in seen:
            found.append(contributor)
            seen.add(contributor.email)

    return found
