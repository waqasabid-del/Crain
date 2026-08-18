"""Retrieving a transcript, and the many times CAIRN must refuse to.

Step 36B is the first code in this product that reads what people said. Almost
every test here is about the paths where it must not: a withdrawal that landed
after the announcement, a workspace that connected Google Meet without granting
transcript access, an artifact that turns out to be a recording, a person who
opted out of the meeting source in the meantime.

Three properties are worth naming, because they are the ones that would decay
silently.

**The restricted scope is separate.** `drive.meet.readonly` is a RESTRICTED scope
and its own consent action on its own OAuth client. A workspace that connected
Meet has not granted it, and the connection's own scope allowlist still refuses
every Drive scope — so the tests in `test_gmeet_boundaries.py` remain true.

**The gate is re-run before every retrieval action**, inside the transaction that
would do the writing. Not once at announcement, not once per batch: the tests
below withdraw consent *between* the announcement and the pass, and between two
artifacts of the same pass.

**Nothing leaks.** Transcript text, speaker names, resource names, Drive ids and
Google's own error strings must not reach a log call, a response model or a
fixture. That is asserted on captured log calls and on the response models
themselves rather than trusted to review.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import pytest
import structlog
from cairn_api.connectors.credentials import SecretValue, store_secret
from cairn_api.db.connector_models import (
    ConnectionState,
    ConnectorProvider,
    SourceConnection,
)
from cairn_api.db.consent_models import SourceOptOut
from cairn_api.db.gmeet_models import (
    GoogleMeetArtifactKind,
    GoogleMeetArtifactSignal,
    GoogleMeetGrantKind,
    GoogleMeetRefusalReason,
    GoogleMeetSubscription,
    GoogleMeetSubscriptionState,
    GoogleMeetTranscriptArtifact,
    GoogleMeetTranscriptGrant,
    GoogleMeetTranscriptRaw,
    GoogleMeetTranscriptState,
)
from cairn_api.db.identity_models import Person
from cairn_api.db.meeting_models import (
    CONSENT_POLICY_VERSION,
    CaptureState,
    ConsentDecision,
    MeetingCaptureRequest,
    MeetingConsent,
    MeetingParticipant,
    MeetingProvider,
    ParticipantSource,
    ParticipantStatus,
)
from cairn_api.db.models import Tenant
from cairn_api.gmeet import artifacts, retrieval
from cairn_api.gmeet import oauth as meet_oauth
from cairn_api.gmeet.artifacts import ArtifactError, ArtifactFailure, RemoteTranscript
from cairn_api.gmeet.oauth import GoogleAccessToken, GoogleTokenGrant
from cairn_api.meetings.guard import CollectionPermit, permit_collection
from cairn_api.sources import Source
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

START = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)
END = START + timedelta(hours=1)
NOW = END + timedelta(minutes=30)

#: A transcript resource name of the shape Google actually sends. Deliberately
#: fictional, and deliberately the only provider identifier in this file: every
#: assertion about leakage checks that *this* string does not appear.
REFERENCE = "conferenceRecords/abc123DEF/transcripts/xyz789GHI"

#: The same shape for a recording. Never accepted.
RECORDING_REFERENCE = "conferenceRecords/abc123DEF/recordings/xyz789GHI"

TRANSCRIPT_TEXT = b"Dana: we agreed to ship on Thursday.\nRiley: I will write it up.\n"


# ---------------------------------------------------------------------------
# Doubles
# ---------------------------------------------------------------------------


@dataclass
class FakeTokens:
    """The OAuth half. Never calls Google, and says which scopes it granted."""

    scopes: frozenset[str] = field(default_factory=lambda: artifacts.TRANSCRIPT_ALLOWED_SCOPES)
    refreshes: int = 0

    async def exchange_code(
        self, *, code: str, redirect_uri: str, code_verifier: str
    ) -> GoogleTokenGrant:  # pragma: no cover - the retrieval path never exchanges
        raise NotImplementedError

    async def refresh_access_token(self, *, refresh_token: SecretValue) -> GoogleAccessToken:
        self.refreshes += 1
        return GoogleAccessToken(
            access_token=SecretValue("access-token-value"),
            granted_scopes=self.scopes,
            expires_in=3600,
        )


@dataclass
class FakeArtifacts:
    """The Drive half: what Google would say, and what it would send."""

    reference: str = REFERENCE
    content: bytes = TRANSCRIPT_TEXT
    content_type: str = "text/plain"
    describe_error: ArtifactFailure | None = None
    download_error: ArtifactFailure | None = None
    describes: int = 0
    downloads: int = 0

    async def describe(self, *, access_token: SecretValue, reference: str) -> RemoteTranscript:
        self.describes += 1
        if self.describe_error is not None:
            raise ArtifactError(self.describe_error)
        return RemoteTranscript(
            reference=self.reference,
            document_id="1AbCdEfGhIjKlMnOp",
            declared_type=artifacts.TRANSCRIPT_DOCUMENT_TYPE,
            generated_at=END,
        )

    def download(
        self, *, access_token: SecretValue, artifact: RemoteTranscript
    ) -> AsyncIterator[bytes]:
        self.downloads += 1
        error = self.download_error
        content = self.content

        async def stream() -> AsyncIterator[bytes]:
            if error is not None:
                raise ArtifactError(error)
            for index in range(0, len(content), 16):
                yield content[index : index + 16]

        return stream()


def a_client(
    *, tokens: FakeTokens | None = None, files: FakeArtifacts | None = None
) -> retrieval.RetrievalClient:
    return retrieval.RetrievalClient(
        tokens=tokens or FakeTokens(), artifacts=files or FakeArtifacts()
    )


# ---------------------------------------------------------------------------
# A whole consented workspace
# ---------------------------------------------------------------------------


@dataclass
class Scenario:
    """One workspace with one consented meeting that produced one transcript."""

    tenant_id: uuid.UUID
    meeting_id: uuid.UUID
    connection_id: uuid.UUID
    subscription_id: uuid.UUID
    signal_id: uuid.UUID
    people: tuple[uuid.UUID, ...]
    user_id: uuid.UUID


async def a_scenario(
    platform: AsyncSession, *, accepted: int = 2, expected: int = 2, granted: bool = True
) -> Scenario:
    """Build the whole chain: consent, connection, lease, announcement, grant."""
    from cairn_api.db.models import User

    tenant = Tenant(name="Acme", slug=f"gmeet-t-{uuid.uuid4().hex[:10]}")
    platform.add(tenant)
    await platform.flush()

    user = User(email=f"{uuid.uuid4().hex[:12]}@example.com", display_name="Ada")
    platform.add(user)
    people = [Person(tenant_id=tenant.id, display_name=f"P{i}") for i in range(expected)]
    platform.add_all(people)
    await platform.flush()

    meeting = MeetingCaptureRequest(
        tenant_id=tenant.id,
        provider=MeetingProvider.GOOGLE_MEET,
        external_meeting_ref=f"spaces/{uuid.uuid4().hex[:12]}",
        scheduled_start=START,
        scheduled_end=END,
        purpose="Write up the launch decisions.",
        policy_version=CONSENT_POLICY_VERSION,
        state=CaptureState.PENDING,
        state_changed_at=START - timedelta(days=1),
    )
    platform.add(meeting)
    await platform.flush()

    for index, person in enumerate(people):
        participant = MeetingParticipant(
            tenant_id=tenant.id,
            meeting_id=meeting.id,
            person_id=person.id,
            status=ParticipantStatus.EXPECTED,
            source=ParticipantSource.MANUAL,
            added_at=START - timedelta(days=1),
        )
        platform.add(participant)
        await platform.flush()
        if index < accepted:
            platform.add(
                MeetingConsent(
                    tenant_id=tenant.id,
                    meeting_id=meeting.id,
                    participant_id=participant.id,
                    decision=ConsentDecision.ACCEPTED,
                    decided_at=START - timedelta(hours=2),
                    policy_version=CONSENT_POLICY_VERSION,
                )
            )

    connection = SourceConnection(
        tenant_id=tenant.id,
        provider=ConnectorProvider.GOOGLE_MEET,
        external_account_id=f"meet:{tenant.id}",
        installation_id=f"meet:{tenant.id}",
        state=ConnectionState.CONNECTED,
        connected_at=START,
    )
    store_secret(connection, SecretValue("connection-refresh-token"))
    platform.add(connection)
    await platform.flush()

    subscription = GoogleMeetSubscription(
        tenant_id=tenant.id,
        connection_id=connection.id,
        meeting_id=meeting.id,
        subscription_name=f"subscriptions/{uuid.uuid4().hex[:16]}",
        state=GoogleMeetSubscriptionState.ACTIVE,
        expire_time=NOW + timedelta(days=3),
        state_changed_at=START,
    )
    platform.add(subscription)
    await platform.flush()

    signal = GoogleMeetArtifactSignal(
        tenant_id=tenant.id,
        subscription_id=subscription.id,
        meeting_id=meeting.id,
        kind=GoogleMeetArtifactKind.TRANSCRIPT,
        artifact_digest=artifacts.digest_of(REFERENCE),
        announced_at=NOW,
    )
    platform.add(signal)
    await platform.flush()

    if granted:
        grant = GoogleMeetTranscriptGrant(
            tenant_id=tenant.id,
            connection_id=connection.id,
            granted_by_user_id=user.id,
            granted_scopes=sorted(artifacts.TRANSCRIPT_SCOPES),
            granted_at=START,
            policy_version=artifacts.TRANSCRIPT_CONSENT_POLICY_VERSION,
        )
        grant._secret_ciphertext = artifacts.seal_refresh_token(
            SecretValue("transcript-refresh-token")
        )
        platform.add(grant)

    await platform.commit()
    retrieval.clear_transcript_token_cache()

    return Scenario(
        tenant_id=tenant.id,
        meeting_id=meeting.id,
        connection_id=connection.id,
        subscription_id=subscription.id,
        signal_id=signal.id,
        people=tuple(person.id for person in people),
        user_id=user.id,
    )


async def announce(
    platform: AsyncSession, scenario: Scenario, *, reference: str = REFERENCE
) -> GoogleMeetTranscriptArtifact | None:
    """Run the availability path exactly as the Pub/Sub receiver does."""
    permit = await permit_collection(
        platform, tenant_id=scenario.tenant_id, meeting_id=scenario.meeting_id, now=NOW
    )
    signal = await platform.get(GoogleMeetArtifactSignal, scenario.signal_id)
    assert signal is not None
    artifact = await retrieval.record_availability(
        platform,
        permit=permit,
        signal=signal,
        connection_id=scenario.connection_id,
        artifact_reference=reference,
        generated_at=END,
        now=NOW,
    )
    await platform.commit()
    return artifact


async def a_permit(platform: AsyncSession, scenario: Scenario) -> CollectionPermit:
    return await permit_collection(
        platform, tenant_id=scenario.tenant_id, meeting_id=scenario.meeting_id, now=NOW
    )


async def withdraw(platform: AsyncSession, scenario: Scenario) -> None:
    """One participant takes their agreement back, after the announcement."""
    consent = await platform.scalar(
        select(MeetingConsent).where(MeetingConsent.meeting_id == scenario.meeting_id)
    )
    assert consent is not None
    consent.decision = ConsentDecision.WITHDRAWN
    await platform.commit()


async def artifact_of(
    platform: AsyncSession, scenario: Scenario
) -> GoogleMeetTranscriptArtifact | None:
    """This scenario's artifact row.

    Tenant-scoped, always. The `platform` fixture commits for real, so an unscoped
    `SELECT` in one test sees the rows another test left behind — and a
    leak-detection test that passed for that reason would be worse than no test.
    """
    found: GoogleMeetTranscriptArtifact | None = await platform.scalar(
        select(GoogleMeetTranscriptArtifact).where(
            GoogleMeetTranscriptArtifact.tenant_id == scenario.tenant_id
        )
    )
    return found


async def raw_of(platform: AsyncSession, scenario: Scenario) -> GoogleMeetTranscriptRaw | None:
    """This scenario's stored transcript, if it still has one."""
    found: GoogleMeetTranscriptRaw | None = await platform.scalar(
        select(GoogleMeetTranscriptRaw).where(
            GoogleMeetTranscriptRaw.tenant_id == scenario.tenant_id
        )
    )
    return found


async def connection_of(platform: AsyncSession, scenario: Scenario) -> SourceConnection:
    connection = await platform.get(SourceConnection, scenario.connection_id)
    assert connection is not None
    return connection


# ---------------------------------------------------------------------------
# The restricted scope
# ---------------------------------------------------------------------------


class TestTheTranscriptScopeIsSeparateAndExplicit:
    def test_it_is_the_narrowest_scope_that_can_read_a_transcript(self) -> None:
        """`drive.meet.readonly`, not `drive.readonly`.

        Both work. The second also grants every other file in the authorising
        account, which is the difference between reading a transcript people
        consented to and holding a key to their filing cabinet.
        """
        assert artifacts.TRANSCRIPT_SCOPES == (
            "https://www.googleapis.com/auth/drive.meet.readonly",
        )
        assert frozenset(artifacts.TRANSCRIPT_SCOPES) == artifacts.TRANSCRIPT_ALLOWED_SCOPES

    def test_the_connection_grant_still_refuses_every_drive_scope(self) -> None:
        """**The property Step 36A rests on, and the one 36B could have broken.**

        Connecting Google Meet must still grant no artifact access at all. If the
        transcript scope had been added to `oauth.REQUIRED_SCOPES` — the obvious
        shortcut, one line — then every workspace that had connected Meet would
        acquire transcript access on its next reconnect, having agreed to nothing.
        """
        assert artifacts.TRANSCRIPT_SCOPES[0] not in meet_oauth.ALLOWED_SCOPES
        assert meet_oauth.is_forbidden_scope(artifacts.TRANSCRIPT_SCOPES[0])
        with pytest.raises(meet_oauth.GoogleMeetInstallError) as caught:
            meet_oauth.verify_granted_scopes(artifacts.TRANSCRIPT_ALLOWED_SCOPES)
        assert caught.value.failure is meet_oauth.GoogleMeetInstallFailure.SCOPES_FORBIDDEN

    def test_a_token_carrying_both_grants_is_refused(self) -> None:
        """The shared-OAuth-client symptom, refused rather than accepted.

        Two consent actions on one client means Google returns the union in both
        token responses. Accepting it "because it contains what we needed" would
        turn the separation into a comment.
        """
        both = artifacts.TRANSCRIPT_ALLOWED_SCOPES | meet_oauth.ALLOWED_SCOPES

        with pytest.raises(ArtifactError) as caught:
            artifacts.verify_granted_transcript_scopes(frozenset(both))
        assert caught.value.failure is ArtifactFailure.SCOPE_UNEXPECTED

    @pytest.mark.parametrize(
        "scope",
        [
            "https://www.googleapis.com/auth/drive",
            "https://www.googleapis.com/auth/drive.readonly",
            "https://www.googleapis.com/auth/drive.file",
            "https://www.googleapis.com/auth/documents.readonly",
            "https://www.googleapis.com/auth/admin.reports.audit.readonly",
            "https://www.googleapis.com/auth/meetings.space.settings",
        ],
    )
    def test_broader_scopes_are_forbidden(self, scope: str) -> None:
        assert artifacts.is_forbidden_transcript_scope(scope)
        with pytest.raises(ArtifactError) as caught:
            artifacts.verify_granted_transcript_scopes(frozenset({scope}))
        assert caught.value.failure is ArtifactFailure.SCOPE_FORBIDDEN

    def test_an_empty_grant_is_insufficient_rather_than_acceptable(self) -> None:
        with pytest.raises(ArtifactError) as caught:
            artifacts.verify_granted_transcript_scopes(frozenset())
        assert caught.value.failure is ArtifactFailure.SCOPE_INSUFFICIENT

    def test_the_authorise_url_asks_for_one_scope_on_its_own_client(self) -> None:
        """Asserted on the built URL, not on the constant: they are only the same
        while nobody appends to the query string."""
        from cairn_api.config import Settings

        settings = Settings(
            environment="test",
            cors_allowed_origins=("http://localhost:3000",),
            google_meet_client_id="meet-1234.apps.googleusercontent.com",
            google_meet_transcript_client_id="transcripts-5678.apps.googleusercontent.com",
            google_meet_transcript_client_secret="not-a-real-secret",  # noqa: S106
            google_meet_transcript_redirect_uri=(
                "https://cairn.test/v1/integrations/google-meet/transcript-callback"
            ),
        )

        url = artifacts.build_transcript_authorize_url(
            settings, state="state-value", code_verifier="verifier-value"
        )

        assert "drive.meet.readonly" in url
        assert "transcripts-5678" in url
        # The connection's client and its scope must not appear on this screen.
        assert "meet-1234" not in url
        assert "meetings.space.readonly" not in url
        for forbidden in artifacts.FORBIDDEN_TRANSCRIPT_SCOPES:
            assert forbidden not in url
        assert "code_challenge_method=S256" in url
        assert "verifier-value" not in url

    def test_the_release_gate_says_restricted_and_does_not_claim_it_is_live(self) -> None:
        """The scope's cost is a calendar constraint owned outside this
        repository, and the wording has to keep saying so."""
        gate = artifacts.RESTRICTED_SCOPE_RELEASE_GATE

        assert "RESTRICTED" in gate
        assert "CASA" in gate
        assert "12 months" in gate
        assert "Do not describe transcript retrieval as live" in gate

    def test_the_ops_gate_blocks_and_names_the_assessment_first(self) -> None:
        from cairn_api.config import Settings
        from cairn_api.ops.release_gates import GateStatus, evaluate_release_gates

        gate = next(
            item
            for item in evaluate_release_gates(
                Settings(environment="test", cors_allowed_origins=("http://localhost:3000",))
            )
            if item.name == "meeting-transcripts"
        )

        assert gate.status is GateStatus.BLOCKED
        assert gate.blocks_release
        assert "CASA" in gate.next_step
        # Before the configuration instructions: an operator who reads "set these
        # three variables" first will do that, see it work, and conclude the
        # feature is ready to launch.
        assert gate.next_step.index("CASA") < gate.next_step.index("CLIENT_ID")

    def test_the_connector_spec_records_the_restricted_tier(self) -> None:
        from cairn_api.ops import connectors

        scopes = {item.name: item for item in connectors.GOOGLE_MEET_TRANSCRIPT_SCOPES}

        assert scopes["drive.meet.readonly"].tier is connectors.ScopeTier.RESTRICTED
        assert scopes["drive.meet.readonly"].requires_security_assessment is True
        # And the connection scope is still SENSITIVE: the announcement half can
        # ship while the assessment for this half is outstanding.
        connection_scopes = {item.name: item for item in connectors.GOOGLE_MEET_SCOPES}
        assert connection_scopes["meetings.space.readonly"].tier is connectors.ScopeTier.SENSITIVE

    def test_the_two_consent_actions_cannot_redeem_each_other(self) -> None:
        """The state's grant kind is written when the button is pressed, and is
        part of the claim predicate on the way back."""
        import inspect

        signature = inspect.signature(meet_oauth.consume_state)

        assert signature.parameters["grant"].default is GoogleMeetGrantKind.CONNECTION
        assert "requested_grant" in inspect.getsource(meet_oauth.consume_state)


# ---------------------------------------------------------------------------
# Transcripts only
# ---------------------------------------------------------------------------


class TestOnlyTranscriptsAreEverRetrieved:
    @pytest.mark.parametrize(
        "reference",
        [
            RECORDING_REFERENCE,
            "conferenceRecords/abc123DEF/smartNotes/xyz",
            "conferenceRecords/abc123DEF",
            "files/1AbCdEf",
            "spaces/abcdef",
            "abc-defg-hij",
        ],
    )
    def test_nothing_but_a_transcript_reference_is_accepted(self, reference: str) -> None:
        """An allowlist on the shape, so whatever Google adds next is refused too."""
        assert not artifacts.is_transcript_reference(reference)
        with pytest.raises(ArtifactError) as caught:
            artifacts.conference_reference_of(reference)
        assert caught.value.failure is ArtifactFailure.NOT_A_TRANSCRIPT

    @pytest.mark.parametrize(
        "content_type",
        [
            "audio/mpeg",
            "video/mp4",
            "application/vnd.google-apps.video",
            "application/octet-stream",
            "application/pdf",
            "application/zip",
        ],
    )
    def test_no_media_content_type_may_be_stored(self, content_type: str) -> None:
        assert not artifacts.is_allowed_content_type(content_type)

    def test_the_allowlist_is_matched_by_equality_not_containment(self) -> None:
        """`"text/plain" in "audio/x-text/plain"` is true, and a check satisfiable
        by a type nobody allowed is not a check."""
        assert artifacts.is_allowed_content_type("text/plain; charset=UTF-8")
        assert not artifacts.is_allowed_content_type("audio/x-text/plain")

    async def test_a_recording_announcement_records_no_artifact(
        self, platform: AsyncSession
    ) -> None:
        """Refused before a row exists, so there is nothing to explain away."""
        scenario = await a_scenario(platform)

        artifact = await announce(platform, scenario, reference=RECORDING_REFERENCE)

        assert artifact is None
        assert await artifact_of(platform, scenario) is None

    async def test_an_artifact_that_describes_as_media_is_retired(
        self, platform: AsyncSession
    ) -> None:
        """Announced as a transcript, described as something else. The download
        never happens, and the row says why."""
        scenario = await a_scenario(platform)
        artifact = await announce(platform, scenario)
        assert artifact is not None
        files = FakeArtifacts(describe_error=ArtifactFailure.NOT_A_TRANSCRIPT)

        outcome = await retrieval.retrieve_artifact(
            platform,
            a_client(files=files),
            await connection_of(platform, scenario),
            artifact,
            permit=await a_permit(platform, scenario),
            now=NOW,
        )

        assert outcome is retrieval.RetrievalOutcome.RETIRED
        assert artifact.state is GoogleMeetTranscriptState.RETIRED
        assert artifact.refusal_reason is GoogleMeetRefusalReason.NOT_A_TRANSCRIPT
        assert files.downloads == 0


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------


class TestTheGateIsReCheckedBeforeEveryRetrieval:
    def test_every_retrieval_entry_point_requires_a_permit_or_derives_one(self) -> None:
        """`permit` is required, keyword-only, and unforgeable — the same device
        `ensure_subscription` uses, and for the same reason: a function that
        *calls* a check can be copied without it."""
        import inspect

        for function in (retrieval.retrieve_artifact, retrieval.record_availability):
            permit = inspect.signature(function).parameters["permit"]
            assert permit.kind is inspect.Parameter.KEYWORD_ONLY
            assert permit.default is inspect.Parameter.empty
            assert "CollectionPermit" in str(permit.annotation)

    def test_there_is_no_way_to_skip_the_gate(self) -> None:
        import inspect

        for function in (
            retrieval.retrieve_artifact,
            retrieval.retrieve_pending_transcripts,
            retrieval.reprocess_artifact,
            retrieval.record_availability,
        ):
            names = set(inspect.signature(function).parameters)
            for forbidden in ("force", "skip", "override", "bypass", "unchecked"):
                assert not any(forbidden in name for name in names)

    async def test_a_withdrawal_after_the_announcement_collects_nothing(
        self, platform: AsyncSession
    ) -> None:
        """**The window this whole step exists to close.** The transcript is
        announced hours after the meeting, and consent can move in between."""
        scenario = await a_scenario(platform)
        await announce(platform, scenario)
        await withdraw(platform, scenario)
        files = FakeArtifacts()

        result = await retrieval.retrieve_pending_transcripts(
            platform, client=a_client(files=files), tenant_id=scenario.tenant_id, now=NOW
        )
        await platform.commit()

        assert result.retrieved == 0
        assert result.refused == 1
        assert files.describes == 0
        assert files.downloads == 0
        artifact = await platform.scalar(
            select(GoogleMeetTranscriptArtifact).where(
                GoogleMeetTranscriptArtifact.tenant_id == scenario.tenant_id
            )
        )
        assert artifact is not None
        assert artifact.state is GoogleMeetTranscriptState.REFUSED
        assert artifact.refusal_reason is GoogleMeetRefusalReason.CONSENT_NOT_CURRENT
        assert await raw_of(platform, scenario) is None

    async def test_a_refusal_is_terminal_rather_than_retried_forever(
        self, platform: AsyncSession
    ) -> None:
        """Consent does not un-withdraw, so a refused row must not be picked up
        by every later pass — which would re-derive the same refusal hourly."""
        scenario = await a_scenario(platform)
        await announce(platform, scenario)
        await withdraw(platform, scenario)

        await retrieval.retrieve_pending_transcripts(
            platform, client=a_client(), tenant_id=scenario.tenant_id, now=NOW
        )
        await platform.commit()
        second = await retrieval.retrieve_pending_transcripts(
            platform, client=a_client(), tenant_id=scenario.tenant_id, now=NOW + timedelta(days=1)
        )

        assert second.considered == 0

    async def test_a_workspace_without_the_transcript_grant_records_nothing(
        self, platform: AsyncSession
    ) -> None:
        """Connecting Google Meet grants no artifact access — so not even the
        encrypted reference is stored, and Step 36A's promise is untouched."""
        scenario = await a_scenario(platform, granted=False)

        artifact = await announce(platform, scenario)

        assert artifact is None
        assert await artifact_of(platform, scenario) is None

    async def test_revoking_the_grant_stops_a_retrieval_already_recorded(
        self, platform: AsyncSession
    ) -> None:
        """The grant is re-read on every retrieval, not cached on the row."""
        scenario = await a_scenario(platform)
        artifact = await announce(platform, scenario)
        assert artifact is not None
        await retrieval.revoke_grant(
            platform, tenant_id=scenario.tenant_id, connection_id=scenario.connection_id, now=NOW
        )
        await platform.commit()
        files = FakeArtifacts()

        outcome = await retrieval.retrieve_artifact(
            platform,
            a_client(files=files),
            await connection_of(platform, scenario),
            artifact,
            permit=await a_permit(platform, scenario),
            now=NOW,
        )

        assert outcome is retrieval.RetrievalOutcome.NOT_AUTHORISED
        assert artifact.refusal_reason is GoogleMeetRefusalReason.SCOPE_NOT_GRANTED
        assert files.describes == 0

    async def test_revoking_destroys_the_credential_as_well_as_the_flag(
        self, platform: AsyncSession
    ) -> None:
        """A revoked grant that keeps its refresh token is a standing
        restricted-scope grant held after the customer asked us to stop."""
        scenario = await a_scenario(platform)

        await retrieval.revoke_grant(
            platform, tenant_id=scenario.tenant_id, connection_id=scenario.connection_id, now=NOW
        )
        await platform.commit()

        grant = await platform.scalar(
            select(GoogleMeetTranscriptGrant).where(
                GoogleMeetTranscriptGrant.tenant_id == scenario.tenant_id
            )
        )
        assert grant is not None
        assert grant.revoked_at == NOW
        assert grant._secret_ciphertext is None
        # And the row survives: "access was held between these dates" is what
        # somebody asks after finding a stored transcript.
        assert grant.granted_at is not None

    async def test_a_disconnected_connection_never_downloads(self, platform: AsyncSession) -> None:
        scenario = await a_scenario(platform)
        artifact = await announce(platform, scenario)
        assert artifact is not None
        connection = await connection_of(platform, scenario)
        connection.state = ConnectionState.DISCONNECTED
        await platform.commit()
        files = FakeArtifacts()

        outcome = await retrieval.retrieve_artifact(
            platform,
            a_client(files=files),
            connection,
            artifact,
            permit=await a_permit(platform, scenario),
            now=NOW,
        )

        assert outcome is retrieval.RetrievalOutcome.REFUSED
        assert artifact.refusal_reason is GoogleMeetRefusalReason.CONNECTION_INACTIVE
        assert files.describes == 0

    async def test_a_torn_down_lease_never_downloads(self, platform: AsyncSession) -> None:
        """`remove_subscription` marks a lease deleted *before* it calls Google,
        so that a withdrawal takes effect whether or not Google is reachable.
        Retrieving under a lease in that state would step around it."""
        scenario = await a_scenario(platform)
        artifact = await announce(platform, scenario)
        assert artifact is not None
        subscription = await platform.get(GoogleMeetSubscription, scenario.subscription_id)
        assert subscription is not None
        subscription.state = GoogleMeetSubscriptionState.DELETED
        await platform.commit()

        outcome = await retrieval.retrieve_artifact(
            platform,
            a_client(),
            await connection_of(platform, scenario),
            artifact,
            permit=await a_permit(platform, scenario),
            now=NOW,
        )

        assert outcome is retrieval.RetrievalOutcome.REFUSED
        assert artifact.refusal_reason is GoogleMeetRefusalReason.CONSENT_NOT_CURRENT

    async def test_a_permit_for_another_meeting_is_refused(self, platform: AsyncSession) -> None:
        """The one argument that carries authority, checked against the thing it
        is being used with rather than trusted."""
        first = await a_scenario(platform)
        second = await a_scenario(platform)
        artifact = await announce(platform, first)
        assert artifact is not None

        outcome = await retrieval.retrieve_artifact(
            platform,
            a_client(),
            await connection_of(platform, first),
            artifact,
            permit=await a_permit(platform, second),
            now=NOW,
        )

        assert outcome is retrieval.RetrievalOutcome.REFUSED
        assert artifact.refusal_reason is GoogleMeetRefusalReason.REFERENCE_MISMATCH

    async def test_another_workspaces_connection_is_refused(self, platform: AsyncSession) -> None:
        first = await a_scenario(platform)
        second = await a_scenario(platform)
        artifact = await announce(platform, first)
        assert artifact is not None

        outcome = await retrieval.retrieve_artifact(
            platform,
            a_client(),
            await connection_of(platform, second),
            artifact,
            permit=await a_permit(platform, first),
            now=NOW,
        )

        assert outcome is retrieval.RetrievalOutcome.REFUSED
        assert artifact.refusal_reason is GoogleMeetRefusalReason.REFERENCE_MISMATCH

    async def test_an_opted_out_participant_stops_the_retrieval(
        self, platform: AsyncSession
    ) -> None:
        """A standing refusal of the meeting source, made once and applying to
        every meeting. Honouring the narrow consent while ignoring the broad
        refusal is not consent."""
        scenario = await a_scenario(platform)
        artifact = await announce(platform, scenario)
        assert artifact is not None
        platform.add(
            SourceOptOut(
                tenant_id=scenario.tenant_id,
                person_id=scenario.people[0],
                source=Source.MEETING.value,
            )
        )
        await platform.commit()
        files = FakeArtifacts()

        outcome = await retrieval.retrieve_artifact(
            platform,
            a_client(files=files),
            await connection_of(platform, scenario),
            artifact,
            permit=await a_permit(platform, scenario),
            now=NOW,
        )

        assert outcome is retrieval.RetrievalOutcome.REFUSED
        assert artifact.refusal_reason is GoogleMeetRefusalReason.OPTED_OUT
        assert files.describes == 0

    async def test_an_identity_that_stopped_resolving_stops_the_retrieval(
        self, platform: AsyncSession
    ) -> None:
        """Step 34 refuses to decide an identity by inference, and the consequence
        is refusing here rather than proceeding on a resolution that was withdrawn
        after the announcement.

        Asserted through the pass rather than through a hand-made permit, because
        this is one of the cases the *guard* also refuses: `permit_collection` will
        not issue a permit for a meeting with an unresolved expected participant at
        all. `_gate` checks it a second time anyway — a defence that exists in only
        one of two doors is the one that gets walked around — and what this test
        pins is the outcome: nothing is fetched.
        """
        scenario = await a_scenario(platform)
        artifact = await announce(platform, scenario)
        assert artifact is not None
        participant = await platform.scalar(
            select(MeetingParticipant).where(
                MeetingParticipant.meeting_id == scenario.meeting_id,
                MeetingParticipant.person_id == scenario.people[0],
            )
        )
        assert participant is not None
        participant.person_id = None
        await platform.commit()
        files = FakeArtifacts()

        result = await retrieval.retrieve_pending_transcripts(
            platform, client=a_client(files=files), tenant_id=scenario.tenant_id, now=NOW
        )
        await platform.commit()

        assert result.refused == 1
        assert files.describes == 0
        assert artifact.state is GoogleMeetTranscriptState.REFUSED
        assert artifact.refusal_reason in {
            GoogleMeetRefusalReason.CONSENT_NOT_CURRENT,
            GoogleMeetRefusalReason.IDENTITY_REVOKED,
        }

    async def test_reprocessing_runs_the_whole_gate_again(self, platform: AsyncSession) -> None:
        """An operator re-running a batch to fix an unrelated problem must not be
        the way a withdrawn meeting gets collected."""
        scenario = await a_scenario(platform)
        artifact = await announce(platform, scenario)
        assert artifact is not None
        await withdraw(platform, scenario)
        files = FakeArtifacts()

        outcome = await retrieval.reprocess_artifact(
            platform,
            a_client(files=files),
            tenant_id=scenario.tenant_id,
            artifact_id=artifact.id,
            now=NOW,
        )

        assert outcome is retrieval.RetrievalOutcome.REFUSED
        assert files.describes == 0


# ---------------------------------------------------------------------------
# Secure intake
# ---------------------------------------------------------------------------


class TestTheDownloadIsBounded:
    async def test_it_stores_the_transcript_with_its_checksum(self, platform: AsyncSession) -> None:
        import hashlib

        scenario = await a_scenario(platform)
        artifact = await announce(platform, scenario)
        assert artifact is not None

        outcome = await retrieval.retrieve_artifact(
            platform,
            a_client(),
            await connection_of(platform, scenario),
            artifact,
            permit=await a_permit(platform, scenario),
            now=NOW,
        )
        await platform.commit()

        assert outcome is retrieval.RetrievalOutcome.RETRIEVED
        assert artifact.state is GoogleMeetTranscriptState.STORED
        assert artifact.content_checksum == hashlib.sha256(TRANSCRIPT_TEXT).hexdigest()
        assert artifact.content_bytes == len(TRANSCRIPT_TEXT)
        assert artifact.content_type == "text/plain"

        raw = await platform.scalar(
            select(GoogleMeetTranscriptRaw).where(
                GoogleMeetTranscriptRaw.artifact_id == artifact.id
            )
        )
        assert raw is not None
        # Encrypted at rest: the ciphertext must not contain the plaintext.
        assert TRANSCRIPT_TEXT.decode() not in raw.content_ciphertext
        assert artifacts.open_content(raw.content_ciphertext) == TRANSCRIPT_TEXT

    async def test_a_transcript_over_the_cap_is_refused_rather_than_truncated(
        self, platform: AsyncSession
    ) -> None:
        """A truncated transcript is a record of a meeting that stops in the
        middle with nothing saying so, which is worse than not having one."""
        scenario = await a_scenario(platform)
        artifact = await announce(platform, scenario)
        assert artifact is not None
        oversized = FakeArtifacts(content=b"x" * (artifacts.MAX_TRANSCRIPT_BYTES + 1))

        outcome = await retrieval.retrieve_artifact(
            platform,
            a_client(files=oversized),
            await connection_of(platform, scenario),
            artifact,
            permit=await a_permit(platform, scenario),
            now=NOW,
        )
        await platform.commit()

        assert outcome is retrieval.RetrievalOutcome.RETIRED
        assert artifact.refusal_reason is GoogleMeetRefusalReason.TOO_LARGE
        assert await raw_of(platform, scenario) is None

    async def test_the_cap_is_enforced_while_streaming(self) -> None:
        """Not after the body is in memory: by then the failure it prevents — a
        mislabelled recording, a compression bomb — has already happened."""
        consumed = 0

        async def endless() -> AsyncIterator[bytes]:
            nonlocal consumed
            while True:
                consumed += 1
                yield b"y" * 1024

        with pytest.raises(ArtifactError) as caught:
            await artifacts.read_capped(endless(), max_bytes=4096)

        assert caught.value.failure is ArtifactFailure.TOO_LARGE
        assert consumed <= 6

    async def test_a_disallowed_content_type_is_refused(self) -> None:
        async def empty() -> AsyncIterator[bytes]:
            yield b""

        with pytest.raises(ArtifactError) as caught:
            await artifacts.read_capped(empty(), content_type="audio/mpeg")

        assert caught.value.failure is ArtifactFailure.CONTENT_TYPE_NOT_ALLOWED

    async def test_an_artifact_that_changed_underneath_us_is_retired(
        self, platform: AsyncSession
    ) -> None:
        """Google answered about a different artifact than the one announced.
        Either a cache serving somebody else's response or an artifact replaced
        since — and both are recorded rather than stored."""
        scenario = await a_scenario(platform)
        artifact = await announce(platform, scenario)
        assert artifact is not None
        other = FakeArtifacts(reference="conferenceRecords/other999/transcripts/other999")

        outcome = await retrieval.retrieve_artifact(
            platform,
            a_client(files=other),
            await connection_of(platform, scenario),
            artifact,
            permit=await a_permit(platform, scenario),
            now=NOW,
        )

        assert outcome is retrieval.RetrievalOutcome.RETIRED
        assert artifact.refusal_reason is GoogleMeetRefusalReason.ARTIFACT_CHANGED
        assert other.downloads == 0

    async def test_a_deleted_artifact_is_retired_truthfully(self, platform: AsyncSession) -> None:
        scenario = await a_scenario(platform)
        artifact = await announce(platform, scenario)
        assert artifact is not None

        outcome = await retrieval.retrieve_artifact(
            platform,
            a_client(files=FakeArtifacts(describe_error=ArtifactFailure.GONE)),
            await connection_of(platform, scenario),
            artifact,
            permit=await a_permit(platform, scenario),
            now=NOW,
        )

        assert outcome is retrieval.RetrievalOutcome.RETIRED
        assert artifact.state is GoogleMeetTranscriptState.RETIRED
        assert artifact.refusal_reason is GoogleMeetRefusalReason.ARTIFACT_GONE

    async def test_an_outage_is_retried_with_a_growing_delay(self, platform: AsyncSession) -> None:
        scenario = await a_scenario(platform)
        artifact = await announce(platform, scenario)
        assert artifact is not None
        unavailable = FakeArtifacts(describe_error=ArtifactFailure.PROVIDER_UNAVAILABLE)

        first = await retrieval.retrieve_artifact(
            platform,
            a_client(files=unavailable),
            await connection_of(platform, scenario),
            artifact,
            permit=await a_permit(platform, scenario),
            now=NOW,
        )

        assert first is retrieval.RetrievalOutcome.RETRY_SCHEDULED
        assert artifact.state is GoogleMeetTranscriptState.FAILED
        assert artifact.attempts == 1
        assert artifact.next_attempt_at == NOW + timedelta(minutes=5)

        second = await retrieval.retrieve_artifact(
            platform,
            a_client(files=unavailable),
            await connection_of(platform, scenario),
            artifact,
            permit=await a_permit(platform, scenario),
            now=NOW,
        )

        assert second is retrieval.RetrievalOutcome.RETRY_SCHEDULED
        assert artifact.next_attempt_at == NOW + timedelta(minutes=10)

    async def test_it_dead_letters_rather_than_retrying_forever(
        self, platform: AsyncSession
    ) -> None:
        """A queue that retries forever spends a customer's quota to produce the
        same refusal, and hides the failures somebody could act on."""
        scenario = await a_scenario(platform)
        artifact = await announce(platform, scenario)
        assert artifact is not None
        unavailable = a_client(
            files=FakeArtifacts(describe_error=ArtifactFailure.PROVIDER_UNAVAILABLE)
        )

        outcomes = [
            await retrieval.retrieve_artifact(
                platform,
                unavailable,
                await connection_of(platform, scenario),
                artifact,
                permit=await a_permit(platform, scenario),
                now=NOW,
            )
            for _ in range(retrieval.MAX_ATTEMPTS)
        ]
        await platform.commit()

        assert outcomes[-1] is retrieval.RetrievalOutcome.DEAD_LETTERED
        assert artifact.state is GoogleMeetTranscriptState.DEAD_LETTERED
        assert artifact.next_attempt_at is None
        # And a dead-lettered row keeps its reason: a job that vanished cannot be
        # distinguished from one that was never sent.
        assert artifact.error_category is not None

    async def test_a_permission_failure_dead_letters_immediately(
        self, platform: AsyncSession
    ) -> None:
        """A revoked permission is fixed by a person, not by waiting, so burning
        four more attempts on it buys nothing."""
        scenario = await a_scenario(platform)
        artifact = await announce(platform, scenario)
        assert artifact is not None

        outcome = await retrieval.retrieve_artifact(
            platform,
            a_client(files=FakeArtifacts(describe_error=ArtifactFailure.PERMISSION_DENIED)),
            await connection_of(platform, scenario),
            artifact,
            permit=await a_permit(platform, scenario),
            now=NOW,
        )

        assert outcome is retrieval.RetrievalOutcome.DEAD_LETTERED
        assert artifact.attempts == 1

    async def test_a_duplicate_announcement_produces_one_artifact(
        self, platform: AsyncSession
    ) -> None:
        """Pub/Sub delivers at least once and Workspace Events may republish."""
        scenario = await a_scenario(platform)

        first = await announce(platform, scenario)
        second = await announce(platform, scenario)

        assert first is not None
        assert second is None
        rows = (
            await platform.scalars(
                select(GoogleMeetTranscriptArtifact).where(
                    GoogleMeetTranscriptArtifact.tenant_id == scenario.tenant_id
                )
            )
        ).all()
        assert len(rows) == 1

    async def test_a_second_retrieval_does_not_download_again(self, platform: AsyncSession) -> None:
        scenario = await a_scenario(platform)
        artifact = await announce(platform, scenario)
        assert artifact is not None
        files = FakeArtifacts()
        client = a_client(files=files)

        await retrieval.retrieve_artifact(
            platform,
            client,
            await connection_of(platform, scenario),
            artifact,
            permit=await a_permit(platform, scenario),
            now=NOW,
        )
        outcome = await retrieval.retrieve_artifact(
            platform,
            client,
            await connection_of(platform, scenario),
            artifact,
            permit=await a_permit(platform, scenario),
            now=NOW,
        )
        await platform.commit()

        assert outcome is retrieval.RetrievalOutcome.DUPLICATE
        assert files.downloads == 1

    def test_the_timeouts_are_bounded(self) -> None:
        """A download that hangs holds a worker while everything else waits."""
        assert 0 < artifacts.DOWNLOAD_TIMEOUT_SECONDS <= 60
        assert 0 < artifacts.METADATA_TIMEOUT_SECONDS <= 30
        assert artifacts.MAX_TRANSCRIPT_BYTES <= 8 * 1024 * 1024

    def test_every_failure_reduces_to_a_category(self) -> None:
        """Total over the enum, so a value added later cannot arrive at a column
        as `None` and read as "nothing wrong"."""
        for failure in ArtifactFailure:
            assert artifacts.category_for(failure) is not None


# ---------------------------------------------------------------------------
# Provenance, retention and leakage
# ---------------------------------------------------------------------------


class TestProvenanceIsImmutableAndComplete:
    async def test_it_records_where_the_transcript_came_from(self, platform: AsyncSession) -> None:
        scenario = await a_scenario(platform)
        artifact = await announce(platform, scenario)
        assert artifact is not None

        await retrieval.retrieve_artifact(
            platform,
            a_client(),
            await connection_of(platform, scenario),
            artifact,
            permit=await a_permit(platform, scenario),
            now=NOW,
        )
        await platform.commit()

        assert artifact.provider == ConnectorProvider.GOOGLE_MEET.value
        assert artifact.meeting_id == scenario.meeting_id
        assert artifact.signal_id == scenario.signal_id
        assert artifact.subscription_id == scenario.subscription_id
        assert artifact.artifact_digest == artifacts.digest_of(REFERENCE)
        assert artifact.conference_digest == artifacts.digest_of("conferenceRecords/abc123DEF")
        assert artifact.generated_at == END
        assert artifact.announced_at == NOW
        assert artifact.retrieved_at == NOW
        assert artifact.consent_policy_version == CONSENT_POLICY_VERSION

    async def test_the_reference_is_stored_encrypted(self, platform: AsyncSession) -> None:
        """A Meet transcript resource name embeds the conference record id, which
        is a durable handle to one specific meeting."""
        scenario = await a_scenario(platform)
        artifact = await announce(platform, scenario)
        assert artifact is not None

        assert REFERENCE not in artifact.artifact_reference_ciphertext
        assert "conferenceRecords" not in artifact.artifact_reference_ciphertext
        assert artifacts.open_reference(artifact.artifact_reference_ciphertext) == REFERENCE

    async def test_retention_deletes_the_transcript_and_keeps_the_record(
        self, platform: AsyncSession
    ) -> None:
        """ "This was collected and has since been deleted" is a different sentence
        from "this never happened", and only the first one is true."""
        scenario = await a_scenario(platform)
        artifact = await announce(platform, scenario)
        assert artifact is not None
        await retrieval.retrieve_artifact(
            platform,
            a_client(),
            await connection_of(platform, scenario),
            artifact,
            permit=await a_permit(platform, scenario),
            now=NOW,
        )
        await platform.commit()
        assert artifact.retention_expires_at is not None

        purged = await retrieval.purge_expired_transcripts(
            platform, now=artifact.retention_expires_at + timedelta(seconds=1)
        )
        await platform.commit()

        assert purged >= 1
        assert artifact.raw_purged_at is not None
        assert (
            await platform.scalar(
                select(GoogleMeetTranscriptRaw).where(
                    GoogleMeetTranscriptRaw.artifact_id == artifact.id
                )
            )
            is None
        )
        # The provenance row survives, with everything that says what happened.
        assert artifact.retrieved_at == NOW
        assert artifact.content_checksum is not None

    async def test_retention_leaves_transcripts_inside_the_window_alone(
        self, platform: AsyncSession
    ) -> None:
        scenario = await a_scenario(platform)
        artifact = await announce(platform, scenario)
        assert artifact is not None
        await retrieval.retrieve_artifact(
            platform,
            a_client(),
            await connection_of(platform, scenario),
            artifact,
            permit=await a_permit(platform, scenario),
            now=NOW,
        )
        await platform.commit()

        purged = await retrieval.purge_expired_transcripts(platform, now=NOW + timedelta(days=1))

        assert purged == 0
        assert artifact.raw_purged_at is None

    async def test_a_controlled_deletion_removes_the_bytes_early(
        self, platform: AsyncSession
    ) -> None:
        scenario = await a_scenario(platform)
        artifact = await announce(platform, scenario)
        assert artifact is not None
        await retrieval.retrieve_artifact(
            platform,
            a_client(),
            await connection_of(platform, scenario),
            artifact,
            permit=await a_permit(platform, scenario),
            now=NOW,
        )
        await platform.commit()

        deleted = await retrieval.delete_transcript(
            platform, tenant_id=scenario.tenant_id, artifact_id=artifact.id, now=NOW
        )
        await platform.commit()

        assert deleted is True
        assert artifact.raw_purged_at == NOW
        assert await raw_of(platform, scenario) is None
        # Idempotent, and honest about it.
        assert (
            await retrieval.delete_transcript(
                platform, tenant_id=scenario.tenant_id, artifact_id=artifact.id, now=NOW
            )
            is False
        )

    async def test_a_withdrawal_after_retrieval_stops_the_future_and_keeps_the_past(
        self, platform: AsyncSession
    ) -> None:
        """Withdrawal stops processing. It does not silently rewrite history —
        that would destroy the evidence that the withdrawal was honoured."""
        scenario = await a_scenario(platform)
        artifact = await announce(platform, scenario)
        assert artifact is not None
        await retrieval.retrieve_artifact(
            platform,
            a_client(),
            await connection_of(platform, scenario),
            artifact,
            permit=await a_permit(platform, scenario),
            now=NOW,
        )
        await platform.commit()

        affected = await retrieval.note_withdrawal(
            platform, tenant_id=scenario.tenant_id, meeting_id=scenario.meeting_id, now=NOW
        )
        await platform.commit()

        assert affected == 1
        assert artifact.withdrawn_at == NOW
        assert artifact.retrieved_at == NOW
        assert artifact.state is GoogleMeetTranscriptState.STORED
        # And nothing will process it again.
        later = await retrieval.retrieve_pending_transcripts(
            platform, client=a_client(), tenant_id=scenario.tenant_id, now=NOW + timedelta(hours=1)
        )
        assert later.considered == 0


class TestNothingLeaks:
    async def test_no_log_call_carries_a_transcript_or_a_reference(
        self, platform: AsyncSession
    ) -> None:
        """Asserted on the captured calls rather than trusted to review.

        A resource name, a document id, a line of transcript or a Google error
        string in a log line is a disclosure into a store that sits outside the
        erasure path.
        """
        scenario = await a_scenario(platform)

        with structlog.testing.capture_logs() as captured:
            artifact = await announce(platform, scenario)
            assert artifact is not None
            await retrieval.retrieve_artifact(
                platform,
                a_client(),
                await connection_of(platform, scenario),
                artifact,
                permit=await a_permit(platform, scenario),
                now=NOW,
            )
            await platform.commit()

        assert captured
        rendered = repr(captured)
        for secret in (
            REFERENCE,
            "conferenceRecords",
            "1AbCdEfGhIjKlMnOp",
            TRANSCRIPT_TEXT.decode(),
            "Dana",
            "transcript-refresh-token",
            "access-token-value",
        ):
            assert secret not in rendered

    async def test_a_refusal_logs_a_category_and_nothing_else(self, platform: AsyncSession) -> None:
        scenario = await a_scenario(platform)
        await announce(platform, scenario)
        await withdraw(platform, scenario)

        with structlog.testing.capture_logs() as captured:
            await retrieval.retrieve_pending_transcripts(
                platform, client=a_client(), tenant_id=scenario.tenant_id, now=NOW
            )
            await platform.commit()

        refusals = [item for item in captured if item["event"].endswith("retrieval_refused")]
        assert refusals
        for entry in refusals:
            assert entry["reason"] in {member.value for member in GoogleMeetRefusalReason}
            assert "meeting_id" not in entry
            assert REFERENCE not in repr(entry)

    def test_the_status_model_cannot_carry_content(self) -> None:
        """The response model is the boundary. A field that could hold a
        transcript is a field that eventually does."""
        from cairn_api.api.schemas import GoogleMeetTranscriptStatus

        fields = set(GoogleMeetTranscriptStatus.model_fields)

        for forbidden in (
            "content",
            "text",
            "transcript",
            "reference",
            "document_id",
            "checksum",
            "url",
            "speaker",
            "artifact_reference",
        ):
            assert forbidden not in fields
        # What it *does* carry is availability.
        assert {"state", "content_held", "announced_at"} <= fields

    def test_the_status_dataclass_cannot_carry_content_either(self) -> None:
        """The internal read model, checked as well as the wire model: a leak
        added there would reach the router before anybody noticed."""
        import dataclasses

        fields = {item.name for item in dataclasses.fields(retrieval.TranscriptStatus)}

        for forbidden in ("content", "checksum", "reference", "ciphertext", "document_id"):
            assert forbidden not in fields

    def test_the_openapi_document_exposes_no_transcript_content_route(self) -> None:
        """**There is no endpoint that returns a transcript**, and the contract is
        where that is checkable."""
        import json
        from pathlib import Path

        from cairn_api.api.export_openapi import OPENAPI_PATH

        schema = json.loads(Path(OPENAPI_PATH).read_text(encoding="utf-8"))
        transcript_paths = [path for path in schema["paths"] if "transcript" in path]

        assert transcript_paths
        for path in transcript_paths:
            assert not path.endswith(("/content", "/download", "/text"))

    def test_the_models_repr_prints_no_provider_value(self) -> None:
        """A `repr` is what a traceback and a structlog rendering reach for."""
        artifact = GoogleMeetTranscriptArtifact(
            id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            meeting_id=uuid.uuid4(),
            state=GoogleMeetTranscriptState.STORED,
            artifact_digest="a" * 64,
        )
        raw = GoogleMeetTranscriptRaw(
            id=uuid.uuid4(),
            artifact_id=uuid.uuid4(),
            content_ciphertext="ciphertext-value",
            content_checksum="b" * 64,
            content_bytes=10,
        )

        assert "a" * 64 not in repr(artifact)
        assert "ciphertext-value" not in repr(raw)
        assert "b" * 64 not in repr(raw)
