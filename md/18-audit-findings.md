# Stage A Security & Correctness Audit

**Date:** 14 August 2026
**Scope:** Everything built in Steps 1–8
**Method:** Four independent adversarial reviews — security, tenant isolation, correctness, and test quality — followed by manual verification of every finding before acting on it.

**Why this file exists:** the fixes are in the code, but the _reasoning_ is not. A future engineer who sees `DROP POLICY tenant_insert` needs to know it closed a reproduced tenant takeover, not that someone tidied up.

---

## Fixed — verified by reproducing the exploit, then re-running it after the fix

### 1. Cross-tenant takeover via invitations 🔴 CRITICAL

**Reproduced.** A session scoped to Tenant A inserted an `owner` invitation for Tenant B and the database accepted it.

`invitations` carried two permissive policies: `tenant_isolation` (WITH CHECK `tenant_id = current setting`) and `tenant_insert` (WITH CHECK `true`). **PostgreSQL ORs permissive policies**, so the effective INSERT check was `true` — the isolation policy was dead for writes.

The attacker chooses the token, so being unable to read the row back is irrelevant. They redeem it through the ordinary public flow, which runs platform-side, and become Owner of a workspace they were never part of.

The policy's stated justification was also wrong: acceptance does not INSERT into `invitations`, it UPDATEs `accepted_at`.

**Fixed** in migration `d7a91f4c2e58`. Re-tested: `new row violates row-level security policy`.

### 2. Authentication tables fully exposed to the application role 🔴 CRITICAL

**Reproduced.** The application role inserted a session row for an arbitrary user, with no tenant context set, and read the sessions table freely.

`sessions`, `password_credentials` and `oauth_identities` were created without RLS and granted to `cairn_app` — the role every request and every background job uses. Any injection or scoping bug anywhere became account takeover: mint a session for any user, or overwrite any password hash.

These tables genuinely cannot be tenant-scoped (a session must resolve before the tenant is known). The right answer was therefore **no access at all** from the application role, since authentication already runs platform-side. Deny-all RLS sits behind the revoke so a future `GRANT` cannot silently reopen it.

**Fixed** in the same migration. Re-tested: `permission denied for table sessions`.

### 3. Production database password published in the repository 🔴 CRITICAL

The role-creation migration hardcoded `cairn_local_dev`, with a comment claiming production supplied its own via Secret Manager. **Nothing implemented that.** The first `alembic upgrade head` against any fresh cluster — initial deploy, DR restore, new region — would have created the application login role with a password committed to git.

Unrecoverable, too: `CREATE ROLE` is guarded by `IF NOT EXISTS` and `downgrade` deliberately does not drop the role, so no later migration would ever have fixed it.

Every layer of the secret story missed it: the pre-commit scanner matches only vendor-prefixed keys, gitleaks' defaults do the same, and `# noqa: S105` silenced Ruff's own check.

**Fixed.** The password now comes from `CAIRN_APP_ROLE_PASSWORD` and the migration **refuses to run** outside local development without it. Passed via `set_config` and `format(%L)` rather than interpolation.

### 4. Privilege escalation through invitations 🟠 HIGH

`invite_to_workspace` took a bare `tenant_id` and `invited_by`, checked neither, and never consulted the permission model. `require()` appeared nowhere outside its own tests.

Two paths: a **Member** could invite an address they controlled as `OWNER` and redeem it; and even after adding a permission check, an **Admin** legitimately holds `MEMBERS_INVITE`, so they could still mint an Owner and acquire the billing, deletion and transfer rights the Owner/Admin split exists to withhold.

**Fixed.** The function now takes the inviter's `Membership` — which _is_ the proof that this person belongs to this workspace in this role, so the facts cannot disagree — calls `require(MEMBERS_INVITE)`, and refuses to grant a role above the inviter's own. Three tests cover it.

### 5. Total production outage from the platform role 🟠 HIGH

`db/session.py` claimed the platform engine "connects as the owner and therefore bypasses RLS". **`FORCE ROW LEVEL SECURITY` revokes exactly that** — FORCE exists to subject the owner to policies. Only superuser or `BYPASSRLS` skips them.

It worked locally purely by accident: Docker runs PostgreSQL as the bootstrap superuser. **Cloud SQL never grants superuser.** On the first production deploy every platform read would have returned zero rows — nobody could log in, every invitation would report "not found", and signup's duplicate check would silently pass and surface as a raw `IntegrityError`.

Silent, total, and untestable locally, because the fixtures point at the same superuser.

**Fixed.** Migration `e4f82b6d1a93` grants `BYPASSRLS` explicitly (not superuser). `db/preflight.py` asserts both roles have their required attributes at startup and refuses to boot otherwise — so a misconfigured URL fails loudly instead of silently disabling isolation or login.

### 6. CI never ran the integration suite 🟠 HIGH

**Found by inspection, then quantified: 59 of 150 tests silently skipped in CI**, including all 13 tenant-isolation tests, all schema tests, and all migration tests. There was no PostgreSQL service, so `_database_available()` returned false and everything marked `integration` skipped. Every run was green.

The conftest comment asserting _"CI always has a database, so coverage is never silently lost"_ was the load-bearing false assumption.

**Fixed.** CI now runs `pgvector/pgvector:pg16` and creates both test databases. More importantly, **conftest now fails hard when `CI` is set and the database is unreachable** — so this cannot silently regress.

### 7. Timing oracle for OAuth-only accounts 🟡 MEDIUM

`authenticate` deliberately burns an Argon2 hash on the unknown-email path to equalise response time — but returned immediately when a user existed with no password credential. An attacker timing the endpoint could distinguish "exists, uses OAuth" (instant) from "does not exist" (~50–100ms), reinstating the enumeration oracle the surrounding code works to close.

**Fixed.** Both branches now hash before raising.

### 8. CI gate treated skipped jobs as success 🟡 MEDIUM

`ci-passed` grepped for `"failure"` and `"cancelled"`. A **skipped** job passed the gate — so a `paths` filter or disabled action could turn off the secret scan while branch protection still reported green. **Fixed** to require `success` on every job. Also added a top-level `permissions: contents: read`, since jobs running `pnpm install` and `uv sync` execute arbitrary dependency scripts with whatever token scope the org defaults to.

### 9. Tests that passed for the wrong reason 🟡 MEDIUM

- `test_unscoped_session_sees_nothing` asserted three zero counts — which pass when RLS works **and** when the fixture wrote nothing at all. Now asserts the data exists via the platform session first, so the zeros mean something.
- `test_force_row_level_security_is_enabled` hardcoded three table names, so it could not see `invitations` (added later, tenant-scoped). Now **derives** the table list from any table carrying a `tenant_id`, so a future table without a policy fails the build.
- The generated-TypeScript drift test skipped silently because `pnpm` was not on PATH in the Python CI job — nothing detected Python-to-TypeScript drift. Now `pnpm` is installed there and the test **fails** rather than skips in CI.
- The invitation hash test asserted only `hash != token`, which `token[::-1]` would satisfy. Now compares against the actual digest.

---

## Open — recorded deliberately, not overlooked

These are real findings not fixed in this pass. Each is scheduled rather than forgotten.

| #   | Finding                                                                                                                                                                                                                                                     | Severity | Plan                                                                                                                                                                      |
| --- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| O1  | **No email verification anywhere.** Anyone can pre-register `victim@company.com`, and an invitation link plus the (usually known) target address lets a stranger self-register and join. The email check on acceptance is weaker than its docstring claims. | 🟠 HIGH  | Needs a real design — verification tokens, `email_verified_at`, and a decision on whether invitations are bearer tokens or identity-bound. **Before any real user data.** |
| O2  | **No rate limiting, and Argon2 runs on the event loop.** 64 MiB × 4 per attempt, unbounded, in a sync call inside `async def`. ~20 concurrent logins reserve ~1.3 GB and block every other request on the instance.                                         | 🟠 HIGH  | `asyncio.to_thread` plus per-IP and per-account limits, with the API layer (Step 9).                                                                                      |
| O3  | **Sessions can only be revoked by presenting the token.** No `revoke_all_for_user`, no revocation on password change, no idle timeout. A stolen token is valid for 30 days and the victim cannot evict it.                                                  | 🟠 HIGH  | Add with the API layer.                                                                                                                                                   |
| O4  | **Permission model is fully tested and never called.** `require()` now guards invitations; nothing else consults it.                                                                                                                                        | 🟠 HIGH  | Wire at every mutating endpoint in Step 9, with enforcement tests at the call sites.                                                                                      |
| O5  | **Config defaults silently fall back to localhost.** A missing `CAIRN_DATABASE_URL` in production boots successfully against whatever answers locally. `is_production` is defined and never used.                                                           | 🟡 MED   | Validator rejecting default/localhost/dev-password values outside local, plus forcing `database_echo=False`.                                                              |
| O6  | **`theme.css` duplicates the design tokens by hand.** Contrast tests read the TypeScript; components render the CSS. Editing the CSS alone breaks WCAG AA with CI green.                                                                                    | 🟡 MED   | Generate `theme.css` from tokens, same pattern as `make schema`.                                                                                                          |
| O7  | **Races in `sign_up` and `accept_invitation`.** Check-then-insert with no locking; concurrent redemption raises `IntegrityError` rather than the documented domain error.                                                                                   | 🟡 MED   | `SELECT … FOR UPDATE` on the invitation; translate `IntegrityError` into domain errors.                                                                                   |
| O8  | **An expired invitation permanently blocks re-inviting.** The partial unique index keys on `accepted_at IS NULL`; expiry sets nothing, so the stale row blocks forever.                                                                                     | 🟡 MED   | Supersede any pending row when issuing a new invitation.                                                                                                                  |
| O9  | **Email lookups cannot use the index.** The only index is `lower(email)`; queries use `email = :v`, so every login sequentially scans `users`.                                                                                                              | 🟡 MED   | Query `func.lower(User.email)`, or switch to `citext`.                                                                                                                    |
| O10 | **Tenant context is lost if a handler commits mid-block.** `SET LOCAL` dies with the transaction; subsequent statements run unscoped.                                                                                                                       | 🟡 MED   | Re-apply context via an `after_begin` session event listener.                                                                                                             |
| O11 | **Fixture teardown truncates whole tables** rather than deleting what it created. Safe today only because other fixtures never commit.                                                                                                                      | 🟢 LOW   | Scope deletes to created IDs.                                                                                                                                             |
| O12 | **Coverage thresholds configured in three places, enforced in none.** No `--cov` in `addopts`; CI never runs `test:coverage`.                                                                                                                               | 🟢 LOW   | Wire into CI.                                                                                                                                                             |
| O13 | Assorted: `attempt` never incremented, `certaintyTreatment` dead and would fail AA if used, `spaceToPx` never called, duplicate `Certainty` exports shadowing generated types, stale seed comment.                                                          | 🟢 LOW   | Housekeeping pass.                                                                                                                                                        |

---

## What this audit says about the process

Five of the nine fixed findings were **tests or controls that appeared to work and did not**: RLS policies neutered by an OR'd permissive policy, auth tables outside RLS entirely, a CI suite skipping its own safety net, a positive-control-free isolation test, a drift check that never ran.

That is the recurring shape of risk in this codebase, and it is worth naming: **the dangerous failures here do not announce themselves.** `pg_policies` was populated, `relforcerowsecurity` was true, CI was green, and none of it was doing anything.

The habit that caught them — asking _why_ something passes rather than accepting that it does — is the one to keep through Stage B.
