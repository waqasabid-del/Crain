"""Meeting capture consent: nobody is recorded because an administrator said so.

Three tables and no workspace toggle. The absence is the design — md/03 §3.1
records that in thirteen US all-party states an employer **cannot** mandate AI
recording over an employee's objection, and that the strictest applicable law
generally governs a multi-state call. CAIRN's customers are distributed teams, so
the strict case is the ordinary one. There is deliberately no column here an
administrator could set to mean "everyone agrees".

**Nothing in this migration records a meeting.** CAIRN never joins one (md/03
§4.2). These tables decide only whether it may later ask a platform for an
artifact that platform produced under its own flow.

**No meeting title column, on purpose.** A calendar title is often the most
sensitive string in a workspace — a performance review, a departure, a diagnosis
— and every participant sees this request. The time window and the requester's
stated purpose identify the meeting well enough for somebody who was in it.

Constraints that make the unsafe states unrepresentable rather than merely
discouraged:

- `uq_meeting_consent_live` — exactly one live decision per participant per
  meeting. Two answers arriving together are decided by the index, not by
  whichever handler read first.
- `ck_meeting_consent_decided` — an answered decision must carry both when it was
  given and who gave it. A row that cannot say when somebody agreed is not
  evidence that they did.
- `uq_meeting_participant_person` / `_account` — one row per person and one per
  platform attendee, so a duplicate cannot create a second silent participant
  whose absent answer nobody notices.
- `ck_meeting_window` — a meeting ends after it starts.
- **No DELETE grant on `meeting_consents`.** Changing your mind appends a
  superseding row; the history is the product's evidence that withdrawal was
  possible and honoured, and a delete privilege is what an injection reaches for
  when it wants that evidence gone.

Revision: 4e8b1d90c7a2, on 9c4a1f602e7b.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "4e8b1d90c7a2"
down_revision: str | None = "9c4a1f602e7b"
branch_labels: str | None = None
depends_on: str | None = None

#: Restated, not imported: a migration describes the vocabulary as it was here.
TENANT_SETTING = "app.current_tenant_id"

PROVIDERS = "('google_meet', 'zoom')"
CAPTURE_STATES = "('pending', 'eligible', 'refused', 'expired', 'cancelled', 'completed')"
PARTICIPANT_STATUSES = "('expected', 'removed')"
PARTICIPANT_SOURCES = "('calendar', 'manual')"
DECISIONS = "('pending', 'accepted', 'declined', 'withdrawn', 'expired')"


def _rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"""
        CREATE POLICY tenant_isolation ON {table}
        USING (tenant_id = NULLIF(current_setting('{TENANT_SETTING}', true), '')::uuid)
        WITH CHECK (tenant_id = NULLIF(current_setting('{TENANT_SETTING}', true), '')::uuid)
    """)


def upgrade() -> None:
    op.create_table(
        "meeting_capture_requests",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(length=32), nullable=False),
        # The platform's stable id. Never a title, never a join URL: the first is
        # frequently the most sensitive string in a workspace, the second is a
        # credential.
        sa.Column("external_meeting_ref", sa.String(length=255), nullable=False),
        sa.Column("scheduled_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("scheduled_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "requested_by_user_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # The only free text here, and required: a request nobody had to justify
        # is one every participant has to evaluate blind.
        sa.Column("purpose", sa.String(length=500), nullable=False),
        sa.Column("policy_version", sa.String(length=32), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("state_changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(f"provider IN {PROVIDERS}", name="ck_meeting_capture_provider"),
        sa.CheckConstraint(f"state IN {CAPTURE_STATES}", name="ck_meeting_capture_state"),
        sa.CheckConstraint("scheduled_end > scheduled_start", name="ck_meeting_capture_window"),
        sa.CheckConstraint("length(btrim(purpose)) > 0", name="ck_meeting_capture_purpose"),
    )
    op.create_index(
        "uq_meeting_capture_live",
        "meeting_capture_requests",
        ["tenant_id", "provider", "external_meeting_ref"],
        unique=True,
        postgresql_where=sa.text("state NOT IN ('cancelled', 'refused', 'expired')"),
    )
    op.create_index("ix_meeting_capture_tenant", "meeting_capture_requests", ["tenant_id"])
    _rls("meeting_capture_requests")
    # No DELETE: a request is cancelled, which is a state somebody can read,
    # rather than removed, which is a request nobody can prove was made.
    op.execute("GRANT SELECT, INSERT, UPDATE ON meeting_capture_requests TO cairn_app")

    op.create_table(
        "meeting_participants",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "meeting_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("meeting_capture_requests.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Null is a real and blocking state: somebody CAIRN cannot identify is
        # somebody it cannot ask, and guessing who they are is what Step 34
        # exists to refuse.
        sa.Column(
            "person_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("people.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("provider_account_id", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="expected"),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            f"status IN {PARTICIPANT_STATUSES}", name="ck_meeting_participant_status"
        ),
        sa.CheckConstraint(
            f"source IN {PARTICIPANT_SOURCES}", name="ck_meeting_participant_source"
        ),
        sa.CheckConstraint(
            "(status = 'expected' AND removed_at IS NULL)"
            " OR (status = 'removed' AND removed_at IS NOT NULL)",
            name="ck_meeting_participant_removal_is_dated",
        ),
    )
    op.create_index(
        "uq_meeting_participant_person",
        "meeting_participants",
        ["meeting_id", "person_id"],
        unique=True,
        postgresql_where=sa.text("person_id IS NOT NULL"),
    )
    op.create_index(
        "uq_meeting_participant_account",
        "meeting_participants",
        ["meeting_id", "provider_account_id"],
        unique=True,
        postgresql_where=sa.text("provider_account_id IS NOT NULL"),
    )
    op.create_index("ix_meeting_participant_meeting", "meeting_participants", ["meeting_id"])
    op.create_index("ix_meeting_participant_tenant", "meeting_participants", ["tenant_id"])
    _rls("meeting_participants")
    op.execute("GRANT SELECT, INSERT, UPDATE ON meeting_participants TO cairn_app")

    op.create_table(
        "meeting_consents",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "meeting_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("meeting_capture_requests.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "participant_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("meeting_participants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "decided_by_user_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("policy_version", sa.String(length=32), nullable=False),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(f"decision IN {DECISIONS}", name="ck_meeting_consent_decision"),
        # Silence is never an answer: a pending row has no decision time and no
        # decider, and an answered one must have both. Without this a row could
        # claim somebody agreed without recording when, or who.
        sa.CheckConstraint(
            "(decision = 'pending' AND decided_at IS NULL AND decided_by_user_id IS NULL)"
            " OR (decision <> 'pending' AND decided_at IS NOT NULL)",
            name="ck_meeting_consent_decided",
        ),
    )
    op.create_index(
        "uq_meeting_consent_live",
        "meeting_consents",
        ["meeting_id", "participant_id"],
        unique=True,
        postgresql_where=sa.text("superseded_at IS NULL"),
    )
    op.create_index("ix_meeting_consent_meeting", "meeting_consents", ["meeting_id"])
    op.create_index("ix_meeting_consent_tenant", "meeting_consents", ["tenant_id"])
    _rls("meeting_consents")
    # SELECT, INSERT, UPDATE — **and never DELETE.** Changing your mind appends a
    # superseding row; the history is how the product demonstrates that
    # withdrawal was possible and honoured, and it is exactly what somebody who
    # had just overridden a refusal would want gone.
    op.execute("GRANT SELECT, INSERT, UPDATE ON meeting_consents TO cairn_app")


def downgrade() -> None:
    for table in ("meeting_consents", "meeting_participants", "meeting_capture_requests"):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.drop_table(table)
