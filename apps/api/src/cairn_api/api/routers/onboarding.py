"""What the workspace has managed so far, for the screen that watches it happen.

**md/11's requirement is not "show a progress bar".** It is that the reader
never sees an empty state: signup to first real output in under ten minutes,
with something true on screen at every moment in between. A workspace connected
ninety seconds ago genuinely has no brief, and the honest choices are to say
"nothing yet" — which reads as a broken product on the one screen where
abandonment costs most — or to show what *is* true: the integration is
connected, four repositories are being read, three hundred commits have arrived,
and here are the first facts from them.

This endpoint exists so the interface can do the second. It returns the real
counters that already exist on the backfill runs, not an estimate: a synthetic
percentage that reaches 90% and stops is worse than an honest count that climbs.

**One request, not four.** The screen polls while a backfill runs, and asking it
to assemble this from `/integrations`, `/backfill`, `/facts` and `/brief` would
mean four round trips per tick and four chances for one of them to disagree with
the others about what stage the workspace is in.
"""

from __future__ import annotations

import enum
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends
from sqlalchemy import func, select

from cairn_api.api.dependencies import (
    PlatformDb,
    TenantDb,
    WorkspaceContext,
    requires,
)
from cairn_api.api.schemas import OnboardingResponse, RepositoryProgress
from cairn_api.auth.permissions import Permission
from cairn_api.db.backfill_models import BackfillRun, BackfillState
from cairn_api.db.fact_models import Fact
from cairn_api.db.github_models import GitHubInstallation

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/workspaces", tags=["onboarding"])


class OnboardingStage(enum.StrEnum):
    """Where the workspace is, as one value the interface can switch on.

    Derived here rather than in the client. Three surfaces will eventually read
    this — the onboarding screen, the brief's empty state, and the admin
    integrations page — and each deriving "are we still importing?" from the same
    four counters is how they end up disagreeing about it.
    """

    #: No integration connected. The reader has an account and nothing else.
    NOT_CONNECTED = "not_connected"

    #: Connected, and the history import has not produced anything yet.
    IMPORTING = "importing"

    #: Facts exist. There is something real to show, even if the import
    #: continues in the background.
    UNDERSTANDING = "understanding"

    #: The import finished. Everything from here is live activity.
    READY = "ready"


@router.get(
    "/{workspace_id}/onboarding",
    response_model=OnboardingResponse,
    summary="How far this workspace has got, for the onboarding screen",
    responses={
        403: {"description": "Requires permission to read content."},
        404: {"description": "No such workspace, or you are not a member."},
    },
)
async def get_onboarding(
    context: Annotated[WorkspaceContext, Depends(requires(Permission.CONTENT_READ))],
    db: TenantDb,
    platform: PlatformDb,
) -> OnboardingResponse:
    """Assemble the state of the workspace's first ten minutes.

    Cheap enough to poll. The three queries are a count, a small indexed select
    and one lookup on a unique column; the screen refreshes every few seconds
    while an import runs, and a query that grew with the workspace would turn
    onboarding into the most expensive page in the product.
    """
    installation = await platform.scalar(
        select(GitHubInstallation).where(
            GitHubInstallation.tenant_id == context.tenant_id,
            GitHubInstallation.uninstalled_at.is_(None),
        )
    )

    runs = list(
        await db.scalars(
            select(BackfillRun)
            .where(BackfillRun.tenant_id == context.tenant_id)
            .order_by(BackfillRun.created_at)
        )
    )

    # Currently-valid facts only. A count that included superseded rows would
    # climb during a re-import and tell the reader the workspace was growing
    # when it was correcting itself.
    fact_count = (
        await db.scalar(
            select(func.count())
            .select_from(Fact)
            .where(Fact.tenant_id == context.tenant_id, Fact.valid_until.is_(None))
        )
    ) or 0

    repositories = [
        RepositoryProgress(
            repository=run.repository,
            state=run.state.value,
            commits_imported=run.commits_imported,
            # Deliberately no percentage. GitHub does not tell us how many
            # commits a repository has before we walk it, so any percentage
            # would be invented — and an invented one always stalls at 90%,
            # which reads as broken rather than as unknown.
            finished=run.state is BackfillState.COMPLETED,
        )
        for run in runs
    ]

    commits = sum(run.commits_imported for run in runs)
    active = any(
        run.state in {BackfillState.PENDING, BackfillState.RUNNING, BackfillState.THROTTLED}
        for run in runs
    )

    if installation is None:
        stage = OnboardingStage.NOT_CONNECTED
    elif fact_count > 0:
        # Facts first, deliberately. A workspace with facts has something worth
        # reading even while more history arrives, and the screen should say so
        # rather than holding it back until the import finishes.
        stage = OnboardingStage.UNDERSTANDING if active else OnboardingStage.READY
    elif active or not runs:
        stage = OnboardingStage.IMPORTING
    else:
        # Every run finished and produced no fact. Not "importing" — that would
        # be a spinner that never resolves — and not "ready" either. The
        # interface says the repositories were quiet, which is the truth.
        stage = OnboardingStage.READY

    return OnboardingResponse(
        stage=stage.value,
        connected=installation is not None,
        account_login=installation.account_login if installation is not None else None,
        repositories=repositories,
        commits_imported=commits,
        facts_available=fact_count,
        importing=active,
    )
