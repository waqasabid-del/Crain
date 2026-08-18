"""What the Meet connector asks Google for, and what it refuses to ask for.

Step 36A adds authorisation and subscriptions and **nothing that reads a
meeting**. No transcript is downloaded, no artifact content is touched, nothing
is transcribed, and no model is called — that is Step 36B, behind a restricted
scope this connector deliberately does not hold.

These tests are about the two lists that decide what the connector *is*: the
scopes on the authorise URL and the event types on a subscription. Both are the
kind of thing that grows by one line in a hurry, and both change the product's
promise when they do — a Drive scope turns "we may be told a transcript exists"
into "we may read your files", and an attendance event turns a consent record
into a presence log.

The other subject here is the boundary between Meet and the Google Chat
connector. They are two Google integrations in one codebase sharing a JWKS
endpoint, a Pub/Sub shape and most of a design; almost every cross-wiring failure
between them is silent.
"""

from __future__ import annotations

import inspect

import pytest
from cairn_api.db.connector_models import ConnectorProvider
from cairn_api.gmeet import oauth as meet_oauth
from cairn_api.gmeet import pubsub as meet_pubsub
from cairn_api.gmeet import subscriptions as meet_subscriptions
from cairn_api.sources import SOURCES, Source

pytestmark = pytest.mark.integration

DRIVE_SCOPES = (
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/drive.meet.readonly",
)


class TestItAsksForTheSmallestThingThatWorks:
    def test_exactly_one_scope_is_requested(self) -> None:
        """`meetings.space.readonly` and nothing else.

        Subscribing to an announcement that a transcript exists needs to know the
        meeting space. It does not need to read the transcript, the recording,
        the participants or the calendar, and asking for any of those here would
        buy nothing this step uses while widening what a customer is consenting
        to on the Google screen.
        """
        assert meet_oauth.REQUIRED_SCOPES == (
            "https://www.googleapis.com/auth/meetings.space.readonly",
        )
        assert frozenset(meet_oauth.REQUIRED_SCOPES) == meet_oauth.ALLOWED_SCOPES

    @pytest.mark.parametrize("scope", DRIVE_SCOPES)
    def test_no_drive_scope_is_requested_or_accepted(self, scope: str) -> None:
        """**Drive is Step 36B and is restricted.**

        `drive.meet.readonly` needs OAuth verification plus an independent CASA
        security assessment. Requesting it here would put this step behind that
        gate for no benefit, and requesting the broader `drive.readonly` would
        ask for every file in the account to read one transcript.
        """
        assert scope not in meet_oauth.REQUIRED_SCOPES
        assert scope not in meet_oauth.ALLOWED_SCOPES

    def test_the_authorise_url_carries_no_forbidden_scope(self) -> None:
        """Asserted on the built URL, not on the constant.

        The constant is what a reader checks; the URL is what Google receives,
        and they are only the same while nobody appends to the query string.
        """
        from cairn_api.config import Settings

        settings = Settings(
            environment="test",
            cors_allowed_origins=("http://localhost:3000",),
            google_meet_client_id="1234.apps.googleusercontent.com",
            google_meet_client_secret="not-a-real-secret",  # noqa: S106
            google_meet_redirect_uri="https://cairn.test/v1/integrations/google-meet/callback",
        )

        url = meet_oauth.build_authorize_url(
            settings, state="state-value", code_verifier="verifier-value"
        )

        for scope in (*DRIVE_SCOPES, *meet_oauth.FORBIDDEN_SCOPES):
            assert scope not in url
        assert "meetings.space.readonly" in url
        # PKCE, and the challenge rather than the verifier.
        assert "code_challenge_method=S256" in url
        assert "verifier-value" not in url


class TestItSubscribesToOneAnnouncementAndNothingElse:
    def test_only_the_transcript_announcement_is_subscribed(self) -> None:
        assert meet_subscriptions.EVENT_TYPES == (
            "google.workspace.meet.transcript.v2.fileGenerated",
        )

    def test_the_two_lists_are_disjoint(self) -> None:
        """A type in both would be a rule contradicting itself, and the one that
        wins would be whichever list a future reader checked."""
        assert not set(meet_subscriptions.EVENT_TYPES) & meet_subscriptions.FORBIDDEN_EVENT_TYPES

    @pytest.mark.parametrize(
        "fragment",
        ["participant", "attendance", "recording", "smartNotes", "conferenceRecord.v2"],
    )
    def test_nothing_that_watches_people_is_subscribed(self, fragment: str) -> None:
        """**Attendance is the line this product does not cross.**

        Participant join and leave events would turn a consent record into a
        presence log — who was late, who left early, who was there at all — which
        is md/05 §B.3.3's forbidden territory and md/03 §5.4's explicit
        non-capability. Recording and smart-notes events would announce artifacts
        this connector must never touch.
        """
        assert not any(fragment.lower() in item.lower() for item in meet_subscriptions.EVENT_TYPES)


class TestNothingHappensWithoutAPermit:
    def test_creating_a_subscription_requires_a_permit(self) -> None:
        """The consent gate is in the signature, not in a docstring.

        `CollectionPermit` is issued only by `meetings.guard.permit_collection`,
        which loads the capture request, its participants and their live consents
        and refuses anything short of unanimous current agreement. Because the
        parameter is required and the type cannot be constructed elsewhere, there
        is no way to reach this function without having asked.
        """
        signature = inspect.signature(meet_subscriptions.ensure_subscription)

        assert "permit" in signature.parameters
        permit = signature.parameters["permit"]
        assert permit.kind is inspect.Parameter.KEYWORD_ONLY
        assert permit.default is inspect.Parameter.empty
        assert "CollectionPermit" in str(permit.annotation)

    def test_there_is_no_way_to_skip_the_gate(self) -> None:
        """No `force`, no `skip_consent`, no precomputed verdict. A safeguard
        with an override is a safeguard that gets overridden."""
        signature = set(inspect.signature(meet_subscriptions.ensure_subscription).parameters)

        for forbidden in ("force", "skip", "override", "bypass", "unchecked"):
            assert not any(forbidden in name for name in signature)


class TestMeetAndChatAreNotCrossWired:
    """Two Google connectors in one codebase, and every confusion is silent."""

    def test_the_provider_string_is_meets_own(self) -> None:
        """`gchat.pubsub.PROVIDER` is imported by Chat's subscription code and
        used for spans, logs and the idempotency digest. A copy that kept it
        would label Meet as Chat and let a Meet event dedupe against a Chat one.
        """
        # No `!= "google_chat"` assertion here: `PROVIDER` is a literal, so mypy
        # rejects that comparison as statically impossible — which is a stronger
        # guarantee than the runtime check would have been, and the reason to
        # delete the check rather than silence the error.
        assert ConnectorProvider.GOOGLE_MEET.value == meet_pubsub.PROVIDER

    def test_meet_does_not_read_chats_push_configuration(self) -> None:
        """Sharing Google's JWKS endpoint is right — the certificates are the
        same. Sharing the audience, the service account or the subscription name
        is not: a token minted for Chat's push subscription would then verify at
        Meet's endpoint.
        """
        source = inspect.getsource(meet_pubsub)

        for chat_var in (
            "CAIRN_GCHAT_PUSH_AUDIENCE",
            "CAIRN_GCHAT_PUSH_SERVICE_ACCOUNT",
            "CAIRN_GCHAT_PUSH_SUBSCRIPTION",
            "CAIRN_GCHAT_EVENTS_TOPIC",
        ):
            assert chat_var not in source

    def test_meet_uses_its_own_oauth_client(self) -> None:
        """**The trap that breaks both connectors at once.**

        `verify_granted_scopes` compares by set equality and Chat sends
        `include_granted_scopes=true`. With one shared client id, a person who
        had authorised Chat would get Chat's scopes echoed in Meet's token
        response — and Chat's in Meet's — so both would fail with
        `SCOPES_UNEXPECTED`. Chat's own module says the client "exists for this
        connector alone"; that is a precondition, not an observation.
        """
        source = inspect.getsource(meet_oauth)

        assert "settings.google_meet_client_id" in source
        # Asserted on the *read*, not on the word: the module's docstring names
        # Chat's setting while explaining this very trap, and a test that failed
        # on the explanation would be pressure to delete the explanation.
        assert "settings.google_chat_client_id" not in source
        assert "google_chat_client_secret" not in source.replace(
            "google_chat_client_secret`", ""
        ).replace("`google_chat_client_secret", "")


class TestMeetingsAreOneRefusableSource:
    def test_meet_evidence_is_filed_as_meeting_not_google_meet(self) -> None:
        """`ConnectorProvider.GOOGLE_MEET` and `Source.MEETING` are different
        strings on purpose.

        A person opts out of "Meetings", not of "Google Meet" — the consent
        surface names what somebody is refusing, not which vendor produced it. So
        the canonical source set has `meeting` and deliberately no `google_meet`,
        and evidence minted under the provider name would fail closed at
        ingestion with `UnknownSourceError`.
        """
        assert Source.MEETING.value == "meeting"
        assert "google_meet" not in SOURCES
        assert ConnectorProvider.GOOGLE_MEET.value == "google_meet"


class TestTheJoiningCodeStaysPrivate:
    def test_no_module_logs_a_meeting_reference(self) -> None:
        """For Meet the meeting reference is the joining code — a credential.
        Step 35 removed it from every API response for that reason; the same
        holds for the log store, which sits outside the erasure path.
        """
        for module in (meet_oauth, meet_pubsub, meet_subscriptions):
            source = inspect.getsource(module)
            for line in source.splitlines():
                stripped = line.strip()
                if not stripped.startswith(("await logger.", "logger.")):
                    continue
                assert "meeting_ref" not in stripped
                assert "space_name" not in stripped
                assert "joining" not in stripped.lower()
