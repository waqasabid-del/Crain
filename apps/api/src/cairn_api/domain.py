"""Core domain vocabulary, mirrored from ``packages/types/src/index.ts``.

These definitions exist on both sides of the language boundary because they are
concepts, not endpoints. Endpoint-shaped types will be *generated* from the
OpenAPI schema once the API exists (md/06-infrastructure.md §6A.2); these are
the small set that must agree independently of any request.

A test asserts that both sides stay in sync — see ``tests/test_domain.py``.
"""

from __future__ import annotations

from enum import StrEnum
from typing import NewType


class Certainty(StrEnum):
    """How much CAIRN trusts a claim.

    Categorical, never numeric. A "73% confident" badge looks rigorous, means
    nothing to a non-technical reader, and invites false precision. Internal
    numeric confidence exists for thresholds and evaluation, but it never
    reaches this type or the interface.

    See md/05-ux-design-privacy.md §A.2.1.
    """

    VERIFIED = "verified"
    """Unambiguous source — a GitHub assignment, a merged commit."""

    OBSERVED = "observed"
    """Corroborated across sources, or extracted from clear discussion."""

    SUGGESTED = "suggested"
    """Single-source inference, typically meeting-derived. Always hedged."""


class TenantRole(StrEnum):
    """Roles within a customer workspace.

    Deliberately limited to four. Role explosion is a documented trap: 500
    customers with 10 custom roles each produces 5,000 roles nobody can reason
    about. Custom roles wait for an enterprise customer who genuinely needs them.

    Note that ``ADMIN`` governs *configuration*, never *surveillance depth* — no
    role grants deeper visibility into an individual than that individual has.

    See md/15-system-roles-and-surfaces.md §2.2 and §2.3.
    """

    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"


class ActivityCategory(StrEnum):
    """The four capture pillars every source normalizes into.

    See md/12-data-model.md §3.
    """

    CODE = "code"
    CONVERSATION = "conversation"
    MEETING = "meeting"
    DOCUMENT = "document"


TenantId = NewType("TenantId", str)
"""A workspace identifier.

The single most important value in the system. A background job that loses
tenant context does not fail loudly — it silently reads across tenants, which
for a trust product is the worst available failure. ``NewType`` makes it
impossible to pass an arbitrary string where a tenant ID is required, catching
a whole class of mistake before runtime.

See md/06-infrastructure.md §4.3.
"""


def as_tenant_id(value: str) -> TenantId:
    """Validate and brand a tenant identifier.

    Raises:
        ValueError: If the identifier is empty or whitespace-only. Failing here
            is deliberate — an empty tenant ID is the first step of a
            cross-tenant read, so it must never be allowed to propagate.
    """
    if not value or not value.strip():
        msg = "Tenant ID cannot be empty"
        raise ValueError(msg)
    return TenantId(value)


#: The one place the certainty tiers are ordered.
#:
#: Three modules in the pipeline each carried a private copy of this mapping.
#: They agreed, which is the dangerous kind of duplication — a fourth copy would
#: also agree, right up until someone edited one of them and a claim quietly
#: started outranking its own evidence.
#:
#: Deliberately not `IntEnum` on `Certainty` itself: an ordered enum invites
#: arithmetic, and "certainty * 0.9" is how a categorical scale becomes the
#: numeric confidence the interface is forbidden to display (md/05 §A.2.1).
CERTAINTY_RANK: dict[Certainty, int] = {
    Certainty.SUGGESTED: 0,
    Certainty.OBSERVED: 1,
    Certainty.VERIFIED: 2,
}


def strongest_certainty(*values: Certainty) -> Certainty:
    """The most confident tier among several.

    What a fact corroborated by two sources is entitled to.
    """
    return max(values, key=lambda value: CERTAINTY_RANK[value])


def weakest_certainty(*values: Certainty) -> Certainty:
    """The least confident tier among several.

    What a claim resting on several facts is entitled to. Taking the strongest
    would let one verified fact launder a meeting inference into a flat
    assertion — the overconfidence the tiers exist to prevent, arriving through
    the citation list.
    """
    return min(values, key=lambda value: CERTAINTY_RANK[value])
