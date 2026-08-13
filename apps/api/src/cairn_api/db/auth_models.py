"""Authentication schema — credentials, sessions and invitations.

Three modelling decisions worth stating, because each prevents a specific
failure:

**Credentials live apart from users.** A user is an identity; a password is one
way of proving it. Separating them means an OAuth-only account simply has no
password row, rather than a nullable hash that every query must remember to
treat as "not really set".

**Sessions are not tenant-scoped.** A session identifies a *person*, and a
person may belong to several workspaces. Scoping sessions to a tenant would make
it impossible to look one up before knowing which tenant the request concerns —
which is exactly the order things happen in. Session lookup is therefore a
platform operation, like signup.

**Invitations are tenant-scoped**, and carry the tenant they belong to. This is
what makes accepting an invitation join the *existing* workspace rather than
creating a new one — a confusing and common failure mode (md/15 §3).

Secrets are stored hashed. A leaked database must not yield usable session
tokens or invitation links.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from cairn_api.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from cairn_api.db.models import TenantRole


class OAuthProvider(enum.StrEnum):
    """Supported identity providers.

    GitHub first: it is the primary integration, so most target users already
    have an account and the connection is one they will make anyway.
    """

    GITHUB = "github"
    GOOGLE = "google"


class PasswordCredential(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A password, stored as an Argon2 hash.

    One row per user, at most. An account authenticating only through OAuth has
    no row here at all.
    """

    __tablename__ = "password_credentials"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )

    #: Argon2id hash. The algorithm and parameters are encoded in the string
    #: itself, so a future parameter change can be detected and the hash
    #: upgraded on the user's next successful login without a migration.
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)


class OAuthIdentity(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A link between a CAIRN user and an external provider account."""

    __tablename__ = "oauth_identities"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    provider: Mapped[OAuthProvider] = mapped_column(
        String(32),
        nullable=False,
    )

    #: The provider's stable identifier for the account — GitHub's numeric ID,
    #: Google's `sub`. Deliberately not the email: people change their email
    #: address at a provider, and matching on it would either lose the link or,
    #: worse, attach the account to whoever inherited the old address.
    provider_subject: Mapped[str] = mapped_column(String(255), nullable=False)

    __table_args__ = (
        UniqueConstraint("provider", "provider_subject", name="uq_oauth_provider_subject"),
        Index("ix_oauth_identities_user_id", "user_id"),
    )


class Session(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """An authenticated session.

    Not tenant-scoped — see the module docstring.
    """

    __tablename__ = "sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    #: SHA-256 of the session token. The token itself is returned to the client
    #: once and never stored, so a database leak yields no usable sessions.
    #:
    #: A fast hash rather than Argon2 is correct here: the token is 256 bits of
    #: entropy we generated, not a human-chosen secret, so there is nothing for
    #: an attacker to brute-force and no reason to pay a slow-hash cost on every
    #: request.
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)

    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    #: Set when the session is deliberately ended. Revoked sessions are retained
    #: rather than deleted so that "when did this session end, and was it a
    #: logout or an expiry" remains answerable during an incident.
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_sessions_user_id", "user_id"),)


class Invitation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """An invitation to join an existing workspace."""

    __tablename__ = "invitations"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )

    #: Who the invitation was addressed to. Stored lower-cased, and checked on
    #: acceptance: an invitation is for a person, not a bearer token that anyone
    #: who obtains the link may redeem.
    email: Mapped[str] = mapped_column(String(320), nullable=False)

    role: Mapped[TenantRole] = mapped_column(
        String(16),
        nullable=False,
        default=TenantRole.MEMBER,
    )

    #: SHA-256 of the invitation token, for the same reason as sessions.
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)

    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    invited_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    tenant = relationship("Tenant")

    __table_args__ = (
        Index("ix_invitations_tenant_id", "tenant_id"),
        # One outstanding invitation per address per workspace. Without this, a
        # double-click on "invite" produces two live invitations and an
        # ambiguous audit trail.
        Index(
            "uq_invitations_pending",
            "tenant_id",
            "email",
            unique=True,
            postgresql_where=(accepted_at.is_(None)),
        ),
    )
