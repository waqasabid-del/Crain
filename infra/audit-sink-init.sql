-- The audit sink's entire schema, run once by the sink instance at first boot.
--
-- This file is the second trust domain's constitution, so it is deliberately
-- short enough to audit by reading. The application connects as audit_mirror
-- and can INSERT and SELECT - never UPDATE, DELETE, TRUNCATE, or DDL - so a
-- full compromise of the application (or of the primary database's owner, who
-- holds no credential here at all) can append to the mirror but can never
-- rewrite or erase what it already holds.
--
-- SELECT is granted to the same role, deliberately: verification is a read,
-- the threat model here is writes, and a separate read-only role would mean a
-- second DSN in the application's environment for no gain in trust.

CREATE TABLE internal_audit_mirror (
    -- Byte-faithful copies of the primary chain's columns. Same sequence, same
    -- hashes, same payload: cross-verification is pure comparison, and any
    -- transformation on the way in would be a place for a bug to hide an edit.
    id UUID PRIMARY KEY,
    sequence BIGINT NOT NULL UNIQUE,
    occurred_at TIMESTAMPTZ NOT NULL,
    actor_user_id UUID NOT NULL,
    action VARCHAR(64) NOT NULL,
    tenant_id UUID,
    reason VARCHAR(500) NOT NULL,
    detail JSONB NOT NULL,
    previous_hash VARCHAR(64) NOT NULL,
    entry_hash VARCHAR(64) NOT NULL,
    -- When the mirror received it - the one column the primary does not have,
    -- because it is a fact about the sink, not about the action.
    mirrored_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- The role the application ships and verifies through.
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'audit_mirror') THEN
        CREATE ROLE audit_mirror LOGIN PASSWORD 'audit_local_dev' NOSUPERUSER;
    END IF;
END
$$;

GRANT CONNECT ON DATABASE cairn_audit TO audit_mirror;
GRANT SELECT, INSERT ON internal_audit_mirror TO audit_mirror;
-- No sequence grant needed: the mirror never generates values; every value
-- arrives from the primary.
