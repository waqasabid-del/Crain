"""Authentication schema — credentials, sessions and invitations.

Credentials live apart from users (OAuth-only accounts have no password row).
Sessions are not tenant-scoped, since they identify a person and must be
looked up before the tenant is known (a platform operation, like signup).
Invitations are tenant-scoped (md/15 §3). Secrets are stored hashed.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from cairn_api.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from cairn_api.db.models import TenantRole


class OAuthProvider(enum.StrEnum):
    """Supported identity providers."""

    GITHUB = "github"
    GOOGLE = "google"


class PasswordCredential(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A password, stored as an Argon2 hash. One row per user, at most."""

    __tablename__ = "password_credentials"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )

    #: Argon2id hash; algorithm/parameters encoded for upgrade detection.
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

    #: GitHub's numeric ID, Google's `sub`. Not email — people change it.
    provider_subject: Mapped[str] = mapped_column(String(255), nullable=False)

    __table_args__ = (
        UniqueConstraint("provider", "provider_subject", name="uq_oauth_provider_subject"),
        Index("ix_oauth_identities_user_id", "user_id"),
    )


class Session(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """An authenticated session. Not tenant-scoped — see module docstring."""

    __tablename__ = "sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    #: SHA-256 of the token, returned once and never stored.
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)

    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
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

    email: Mapped[str] = mapped_column(String(320), nullable=False)

    #: Same ``tenant_role`` enum as ``Membership.role``, not ``VARCHAR``.
    role: Mapped[TenantRole] = mapped_column(
        Enum(TenantRole, name="tenant_role", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=TenantRole.MEMBER,
    )

    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    #: A later invitation to the address replaces this one.
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    invited_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    tenant = relationship("Tenant")

    __table_args__ = (
        Index("ix_invitations_tenant_id", "tenant_id"),
        Index(
            "uq_invitations_pending",
            "tenant_id",
            "email",
            unique=True,
            postgresql_where=(accepted_at.is_(None) & superseded_at.is_(None)),
        ),
    )


class EmailVerification(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A token proving control of an email address. Not tenant-scoped, like
    `Session`. The application role holds no privilege on this table at all."""

    __tablename__ = "email_verifications"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    #: Captured at issue time, not read from the user row.
    email: Mapped[str] = mapped_column(String(320), nullable=False)

    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_email_verifications_user_id", "user_id"),)


class PasswordReset(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A token proving control of the address on file, redeemable once to set
    a new password. Not tenant-scoped, like `Session` and `EmailVerification`
    — it identifies a person, not a workspace member, and the application
    role holds no privilege on this table at all (same reasoning as
    `EmailVerification`: a scoped session able to insert here could reset a
    password it does not own).

    No `email` column, unlike `EmailVerification`: the token is keyed to
    `user_id`, and resetting a password does not re-assert anything about the
    address it was mailed to — there is nothing here an address change could
    make stale.
    """

    __tablename__ = "password_resets"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_password_resets_user_id", "user_id"),)
