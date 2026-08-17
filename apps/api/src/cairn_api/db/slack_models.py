"""The two tables the Slack install flow adds, and nothing else.

There is deliberately no Slack *connection* table here. ``SourceConnection``
already answers "which workspace is connected to which external account, with
what granted, authorised by whom" for every provider, and a parallel Slack table
would be a second place to get row-level security right and a second answer to
"is this workspace connected". These two tables hold only what
``SourceConnection`` genuinely cannot:

:class:`SlackOAuthState` — the server side of the OAuth ``state`` parameter. It
exists for the window between "an admin pressed Connect" and "Slack redirected a
browser back to us", which is the window a CSRF attack lives in.

:class:`SlackChannelSelection` — which public channels a workspace has chosen to
let CAIRN read. **Selection is the whole permission model.** A connected Slack
workspace with no row here is a workspace CAIRN processes nothing from; there is
no "all channels" flag, because a flag that means "everything, including the one
you create tomorrow" is consent nobody actually gave.

Neither table stores a credential — ``connectors/credentials.py`` owns that — and
neither stores a channel *name*. See the comment on ``channel_id``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from cairn_api.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

#: A Slack public-channel id: ``C`` followed by uppercase alphanumerics.
#:
#: Kept as a string here and as a CHECK constraint in the migration, so the two
#: cannot drift and neither can be bypassed by a caller that skips the ORM.
CHANNEL_ID_PATTERN = r"^C[A-Z0-9]{2,31}$"


class SlackOAuthState(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One in-flight Slack install, identified by an unguessable nonce.

    **Server-side, not a signed cookie.** A signed value the client holds cannot
    be revoked and cannot be single-use without server state anyway — and
    single-use is the property that stops a captured callback URL being replayed
    to bind a second, attacker-chosen Slack workspace to someone else's account.
    """

    __tablename__ = "slack_oauth_states"

    #: Which workspace the install was started from. Carried here rather than
    #: recovered from the callback, because the callback URL is registered with
    #: Slack once and therefore cannot name a workspace — the state *is* the only
    #: link between the browser coming back and the workspace that asked.
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )

    #: Who pressed Connect. Checked again on the callback, so a state handed to
    #: (or stolen by) a different person cannot be redeemed — being a member of
    #: the same workspace is not enough.
    #:
    #: RESTRICT rather than CASCADE, matching `source_connections`: an in-flight
    #: install is a consent record in miniature, and losing it because someone
    #: left the company is exactly backwards.
    initiated_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )

    #: SHA-256 of the nonce, never the nonce itself.
    #:
    #: The same reasoning as `invitations.token_hash`: this row is readable by
    #: anything that can read the database, and a stored plaintext nonce would
    #: let a reader complete an install that a workspace admin started. Hashing
    #: costs one function call and makes a database dump useless for that.
    state_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)

    #: Short — see `slack/oauth.STATE_TTL`. An install is a browser round trip
    #: through one consent screen, so anything measured in hours is a window
    #: held open for no one's benefit.
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    #: Stamped the moment the callback claims it, *before* the code is exchanged.
    #:
    #: Before, deliberately. Consuming on success would make a failed exchange
    #: leave a live state behind, and "retry the callback until it works" is
    #: indistinguishable from an attacker replaying one.
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_slack_oauth_states_tenant_id", "tenant_id"),
        # Supports the expiry sweep. Without it, deleting lapsed states is a
        # sequential scan over a table that grows by one row per abandoned
        # install — which is the shape a scanner can inflate for free.
        Index("ix_slack_oauth_states_expires_at", "expires_at"),
    )

    def is_usable(self, *, now: datetime | None = None) -> bool:
        """Whether this state may still be redeemed.

        Computed rather than stored, for the reason `SupportSession.is_active`
        gives: a `used` boolean is only correct until something forgets to set
        it, and a stale "unused" reads as a live authorisation.
        """
        moment = now or datetime.now(UTC)
        return self.consumed_at is None and self.expires_at > moment

    def __repr__(self) -> str:
        """Identity and lifecycle only — never `state_hash`.

        The hash is not a credential, but printing it makes the nonce
        correlatable across logs, and a log line that identifies an in-flight
        install by its nonce is one that identifies it by the thing the nonce
        exists to keep private.
        """
        return (
            f"SlackOAuthState(id={self.id!r}, tenant_id={self.tenant_id!r}, "
            f"consumed={self.consumed_at is not None!r})"
        )

    __str__ = __repr__


class SlackChannelSelection(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One public channel a workspace has permitted CAIRN to read.

    The presence of the row is the permission. There is no ``enabled`` column,
    for the reason ``source_opt_outs`` has none: a boolean adds a second state
    that has to agree with the first, and the disagreement is always resolved in
    the direction of reading more.
    """

    __tablename__ = "slack_channel_selections"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )

    #: The Slack connection this selection belongs to. CASCADE, because a
    #: selection outliving its connection is a permission attached to nothing —
    #: and the next connection to the same workspace would silently inherit it.
    connection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source_connections.id", ondelete="CASCADE"), nullable=False
    )

    #: Slack's channel id (``C0123ABCD``), and never the display name.
    #:
    #: Two reasons, and both matter. **Names change** — renaming ``#hiring`` to
    #: ``#hiring-2026`` would silently revoke a permission if the name were the
    #: key, or silently grant one if a different channel took the old name.
    #: **A name is customer data**: `#acme-layoffs-legal` in a log line, an error
    #: message or a staff diagnostics screen is a disclosure on its own, which is
    #: why `ConnectorErrorCategory` exists and why nothing here stores a name to
    #: begin with. The picker fetches names live from Slack and shows them to the
    #: admin who is already looking at them in Slack; nothing persists them.
    channel_id: Mapped[str] = mapped_column(String(32), nullable=False)

    #: Consent, recorded the same way `source_connections` records it: who
    #: decided, with `created_at` answering when. An audit asking "who let CAIRN
    #: into this channel" has to have an answer that is not a shrug.
    selected_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )

    __table_args__ = (
        # Per connection rather than per tenant. A workspace that disconnects one
        # Slack team and connects another must not inherit the first one's
        # selection — channel ids are unique per Slack workspace, not globally.
        UniqueConstraint(
            "connection_id", "channel_id", name="uq_slack_channel_selections_connection_channel"
        ),
        # Rejects a display name at the database, not only in the request model.
        # `#general` is what a caller sends when an interface passed the label
        # through, and accepting it would create a permission that matches no
        # inbound event — a channel that looks selected and delivers nothing.
        CheckConstraint(
            f"channel_id ~ '{CHANNEL_ID_PATTERN}'",
            name="ck_slack_channel_selections_channel_id_is_an_id",
        ),
        Index("ix_slack_channel_selections_tenant_id", "tenant_id"),
        # The ingestion lookup: "may this tenant process this channel". Every
        # inbound Slack event runs it, so it is the one index that has to exist.
        Index(
            "ix_slack_channel_selections_tenant_channel",
            "tenant_id",
            "channel_id",
        ),
    )

    def __repr__(self) -> str:
        """Ids only. There is no name to leak, which is the point."""
        return (
            f"SlackChannelSelection(id={self.id!r}, connection_id={self.connection_id!r}, "
            f"channel_id={self.channel_id!r})"
        )

    __str__ = __repr__
