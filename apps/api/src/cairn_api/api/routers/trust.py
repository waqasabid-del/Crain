"""The Trust & Privacy Center (md/05 §B.6).

**A page in the product, not a policy PDF**, and readable by every member rather
than by administrators. Two audiences, identical content: the engineer deciding
each morning whether this thing is on their side, and the buyer whose AI
governance review increasingly gates the purchase. Writing one version for each
is how the two versions come to disagree.

**Every number is read from this workspace.** The retention period, which sources
are actually connected, how many people are still waiting to be notified — all
queried, none written into the copy. A trust page stating a retention period the
system does not apply is the most damaging sentence this product could publish,
because its whole audience is people deciding whether the rest is true. That is
also why the retention figure here is enforced by a sweep that deletes
(`pipeline/retention.py`) rather than by a filter that hides.

**The refusals are shared with the notification screen, not restated.** md/05
§B.3.4's commitments appear at the moment somebody is deciding whether to opt out
*and* here, and two hand-maintained lists of promises is one list plus a way for
the product to start making different promises in different places.
"""

from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, status
from sqlalchemy import func, select

from cairn_api.api.dependencies import CurrentMembership, TenantDb
from cairn_api.api.errors import ProblemDetailError
from cairn_api.api.routers.me import REFUSALS, SOURCE_COPY
from cairn_api.api.schemas import TrustCenter, TrustCommitment, TrustSource
from cairn_api.db.github_models import GitHubInstallation
from cairn_api.db.models import Membership, Tenant
from cairn_api.pipeline import consent

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/workspaces", tags=["trust"])

#: How the product behaves, in the reader's terms.
#:
#: Distinct from the refusals, which are things CAIRN will not do. These are
#: things it does — and each one is a property somebody could check by using the
#: product for an afternoon, which is the test a commitment has to pass before it
#: belongs on this page. "We take privacy seriously" fails it.
COMMITMENTS: tuple[TrustCommitment, ...] = (
    TrustCommitment(
        title="Everyone sees the same thing",
        detail=(
            "Roles decide what you can configure — connecting an integration, inviting a "
            "colleague. They never decide how much is visible about a person. An Owner sees "
            "exactly what you see about you, which is exactly what you see about them."
        ),
    ),
    TrustCommitment(
        title="Every claim carries its evidence",
        detail=(
            "Anything CAIRN says about your work links to the pull request, message or "
            "meeting it came from, in one click. A statement CAIRN cannot show you the source "
            "of is one it does not make."
        ),
    ),
    TrustCommitment(
        title="Your record is yours to correct",
        detail=(
            "You can correct anything CAIRN says about you, in one action, without asking "
            "anybody. The original is kept alongside the correction rather than overwritten, "
            "so nobody can quietly rewrite what was said."
        ),
    ),
    TrustCommitment(
        title="Uncertainty is stated, never scored",
        detail=(
            "CAIRN says whether something is verified, observed or suggested. There is no "
            "confidence percentage anywhere in the product, because a number invites a "
            "comparison the underlying evidence cannot support."
        ),
    ),
    TrustCommitment(
        title="You can switch off any source, and it applies backwards",
        detail=(
            "Opting out of a source removes the attributions already made from it, not just "
            "future ones. The work stays in the team's history; CAIRN stops saying it was you."
        ),
    ),
    TrustCommitment(
        title="Nobody is told before you are",
        detail=(
            "CAIRN attributes nothing to a person until it has shown them what it reads and "
            "how to switch it off. Until then their name is text in a message, linked to "
            "nobody."
        ),
    ),
)

#: Third parties that process customer content.
#:
#: Named, with what they see. md/02 §5 makes this a requirement rather than a
#: courtesy: "trusted partners" is the phrasing of a company that would rather
#: its customers did not check, and a subprocessor list is the first thing a
#: governance review asks for.
SUBPROCESSORS: tuple[TrustCommitment, ...] = (
    TrustCommitment(
        title="Google Cloud (Vertex AI)",
        detail=(
            "Runs the models that read your activity and write your briefs. Content is sent "
            "for processing and is not used to train anybody's model."
        ),
    ),
    TrustCommitment(
        title="Google Cloud (infrastructure)",
        detail="Hosts the database and services. Data is stored in the region shown above.",
    ),
    TrustCommitment(
        title="GitHub",
        detail=(
            "The source of the activity, when connected. CAIRN reads commit messages, pull "
            "request titles and reviews — never the contents of your code."
        ),
    ),
)


@router.get(
    "/{workspace_id}/trust",
    response_model=TrustCenter,
    summary="What CAIRN reads, what it refuses to do, and what happens to it",
    responses={404: {"description": "No such workspace, or you are not a member."}},
)
async def trust_center(context: CurrentMembership, db: TenantDb) -> TrustCenter:
    """The Trust & Privacy Center for this workspace.

    **Every member, no permission check beyond membership.** An engineer should
    not need their manager's role to find out what is read about them — and a
    page about trust that some of the team cannot open has answered the question
    it was written to address.

    Sources are listed exhaustively with a connected flag rather than filtered to
    the connected ones. "What could CAIRN read here if somebody switched it on"
    is the question a person joining a workspace is actually asking, and a list
    that grows silently as integrations are added answers it only in hindsight.
    """
    tenant = await db.scalar(select(Tenant).where(Tenant.id == context.tenant_id))
    if tenant is None:  # pragma: no cover — membership proves the tenant exists
        raise ProblemDetailError(
            status_code=status.HTTP_404_NOT_FOUND,
            title="No such workspace",
            detail="This workspace does not exist.",
            problem_type="workspace-not-found",
        )

    connected = await _connected_sources(db, context.tenant_id)

    awaiting = await db.scalar(
        select(func.count())
        .select_from(Membership)
        .where(Membership.tenant_id == context.tenant_id, Membership.notified_at.is_(None))
    )

    return TrustCenter(
        sources=[
            TrustSource(
                source=source,
                label=SOURCE_COPY[source][0],
                reads=SOURCE_COPY[source][1],
                connected=source in connected,
            )
            for source in consent.SOURCES
        ],
        refusals=list(REFUSALS),
        commitments=list(COMMITMENTS),
        retention_days=tenant.retention_days,
        region=tenant.region,
        # A count and not names, matching the administrator's screen: "has
        # everyone here been told?" is a question the whole team has a stake in,
        # and "who has not been told" is administration.
        awaiting_notification=int(awaiting or 0),
        subprocessors=list(SUBPROCESSORS),
    )


async def _connected_sources(db: TenantDb, tenant_id: uuid.UUID) -> set[str]:
    """Which sources are actually reading for this workspace.

    Only GitHub can be connected today. Written as a set built from a query
    rather than a boolean so that adding chat is a query and not a redesign of
    this response.
    """
    installation = await db.scalar(
        select(GitHubInstallation).where(
            GitHubInstallation.tenant_id == tenant_id,
            GitHubInstallation.uninstalled_at.is_(None),
        )
    )
    return {"github"} if installation is not None else set()
