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

## Round two — the first fixes were incomplete

A second pass audited **the fixes themselves**, plus the frontend and tooling, which the first round had not covered. It found real problems in my own work.

### 10. Three more isolation gaps (CRITICAL)

Closing the `invitations` hole left the identical pattern on `tenants` and `users`, and left a third path open through `memberships`. All reproduced:

- **Membership grafting.** A scoped session could insert a membership for any `user_id`, including one it could not see — foreign-key checks run as the constraint owner and are exempt from RLS. A session scoped to Tenant A grafted a Tenant B user in, then read their email. The victim also silently became a member of the attacker's workspace.
- **Rogue tenants and users**, which also handed back the account-enumeration oracle `authenticate` works to deny.

**Fixed** in `f1c93a70b5d2`: creating an identity, workspace or membership is platform-only, so the `WITH CHECK (true)` escape hatches are gone entirely.

### 11. Destruction was still open (HIGH)

The fix above applied the principle to `INSERT` and stopped. Reproduced: a scoped session ran `DELETE FROM tenants` and destroyed its own workspace — **no role check anywhere**, so a Viewer could do it. Deleting a shared user also cascaded into their other workspaces' memberships, sessions and credentials.

**Fixed** in `a9d24e60c3f1`.

### 12. My environment guard was bypassable (CRITICAL)

The password fix read `os.environ` directly, but `config.py` declares `env_file=".env"` — the documented way this project supplies configuration. A deployment setting `CAIRN_ENVIRONMENT=production` there leaves `os.environ` empty, so the guard would not fire and the published development password would be used anyway. **The fix for finding 3 did not actually close finding 3.**

**Fixed:** migrations now read the environment through `get_settings()`, so they cannot disagree with the application about which environment they are in.

### 13. The password fix did not repair an existing role (HIGH)

`CREATE ROLE ... IF NOT EXISTS` short-circuits. Roles are cluster-level and survive `DROP DATABASE`, so any cluster that ran the earlier migration kept the published password **forever** — changing where the password comes from does not help if the role already exists. The migration's own docstring named this property and the code preserved it.

**Fixed:** the migration now `ALTER`s an existing role rather than skipping it.

### 14. preflight.py was never called or tested (HIGH)

I wrote a startup safety check, described it in this document as protection that "refuses to boot", and wired it to nothing. Worse, the tests I added for it asserted on `pg_roles` columns **without ever calling the functions** — deleting the entire body of `check_application_role` would have left them green.

That is precisely the false-confidence pattern this audit exists to catch, reproduced inside the fix for it.

**Fixed:** the checks accept an engine, and the failure tests now create a real `NOSUPERUSER BYPASSRLS` role, connect as it, and assert the check raises. It is still not called at startup — there is no application to call it from until Step 9 — and this document no longer claims otherwise.

### 15. Frontend and tooling (MEDIUM)

- **`asTenantId` had drifted between languages.** Python rejected whitespace; TypeScript accepted `"   "` as a valid tenant ID.
- **`disabled ?? loading` was a real bug.** Nullish coalescing only falls through on null/undefined, so `<Button loading disabled={false}>` rendered a fully clickable button that announced itself as busy.
- **`aria-label` on a bare `<span>`** is prohibited by ARIA on `role="generic"` and dropped by several screen readers — so `CertaintyBadge`'s whole accessibility story could silently evaporate. Now `role="img"`.
- **No `.env.example`** existed, despite `.gitignore` anticipating one and two new required variables depending on it.
- **`pnpm check` claimed both languages and skipped mypy**, so a contributor could get a green local check and a red CI.
- **README setup was broken for a fresh clone** — Docker and Make absent from requirements, no step creating the database the tests need.
- **`make db-up` could hang forever** if port 5432 was already in use.

---

## Round three — closing the open findings

The previous round documented eleven findings rather than fixing them. That is a legitimate
call when a finding needs infrastructure that does not exist yet, and an evasion when it does
not. Everything below fell into the second category and has now been fixed and verified.

### 16. Argon2 blocked the event loop (O2, partial) 🟠 HIGH

`hash_password` and `verify_password` are CPU-bound C calls. They were invoked directly inside
`async def authenticate`, so every login froze the entire worker for 50–100 ms — not just that
request. Under concurrent logins the instance stops serving anything at all, which presents as
a site-wide outage caused by people signing in.

**Fixed:** `hash_password_async` / `verify_password_async` wrap the calls in `asyncio.to_thread`,
and the service uses those exclusively. The timing-equalisation paths (unknown account,
OAuth-only account) were switched too, so the anti-enumeration property survives.

Also closed here: passwords were unbounded, and Argon2 cost scales with input length. A few
megabytes of "password" turned one unauthenticated request into seconds of CPU across 64 MiB.
Now capped at 1024 bytes — far above any real passphrase.

**Still open:** rate limiting. It belongs at the API layer, which does not exist until Step 9.

### 17. Sessions could only be revoked by presenting the token (O3) 🟠 HIGH

The only revocation path required the session token — which is exactly what the person
reporting a compromise does not have, and what the attacker does. The honest answer to
"someone else is logged into my account" was that we could not help.

**Fixed:** `revoke_all_sessions_for_user(user_id, except_session_id=None)`, plus a 14-day idle
timeout inside the 30-day absolute lifetime. Sessions never used fall back to `created_at`, so
an issued-then-abandoned session still ages out. Four tests, including one asserting the idle
session dies while `expires_at` is still in the future.

### 18. Races and a permanent invitation deadlock (O7, O8) 🟡 MED

Three separate defects in the same area:

- `sign_up` and `accept_invitation` were check-then-act with no locking. A concurrent duplicate
  reached the unique index and surfaced as a raw `IntegrityError` — a 500 naming a database
  constraint, and worse, an aborted transaction the caller could not recover from.
- Redeeming one invitation twice (a double-click sufficed) inserted two memberships.
- An invitation that expired unaccepted still satisfied `accepted_at IS NULL`, so it held the
  one pending slot for that address **forever**. Every re-invitation failed on the constraint.
  The workspace was permanently unable to invite that person.

**Fixed:** savepoints translate `IntegrityError` into the documented domain errors without
poisoning the transaction; `SELECT … FOR UPDATE` on both the invitation lookup and the
supersession read; and a new `superseded_at` column (migration `b6e30f14a7c9`) separates
"finished" from "accepted". Issuing a new invitation stamps the old one, which also gives
"resend invitation" its correct meaning — the previous link stops working rather than both
remaining redeemable.

### 19. Every login sequentially scanned `users` (O9) 🟡 MED

The only index is on the expression `lower(email)`; the query filtered on `email = :value`.
PostgreSQL uses an expression index only when the query repeats the expression, so the plan was
a sequential scan. Correct results, wrong plan — invisible until the table is large, and then
indistinguishable from a sudden outage.

**Fixed:** the lookup filters on `func.lower(User.email)`.

### 20. The design tokens existed twice, and the tests read the wrong copy (O6, O14) 🟡 MED

`theme.css` hand-mirrored `src/tokens/*.ts`. The contrast tests read the TypeScript; components
render the CSS. Nothing connected them — so changing `--fg-muted` in the CSS to a colour failing
4.5:1 left every accessibility test passing. A design system whose WCAG guarantee can be true of
the tokens and false of the shipped product is not providing a guarantee.

**Fixed:** `src/styles/generate.ts` renders the stylesheet from the tokens, and
`generate.test.ts` fails if the committed file has drifted. Verified by editing `--fg-muted`
by hand and watching CI go red. Three supporting assertions: every semantic role reaches the
CSS, both themes define the same roles (a role present in light and missing in dark is the
classic defect, because most developers work in one theme), and no raw hex appears outside the
theme blocks.

**Still open:** `certaintyTreatment` specifies an opacity the component never applies, while
three documents tell readers opacity is how tiers differ. That is a docs-vs-code disagreement,
tracked as O13.

### 21. Tooling that reported success without doing anything (O16, O17, O18) 🟢 LOW

Three instances of the same pattern the earlier rounds kept finding:

- **`turbo run build` executed nothing.** The task was defined and four tasks depended on
  `^build`, but no package has a build script. A dependency edge that resolves to a no-op is
  worse than no edge: it reads as a guarantee that artefacts are current. Removed until
  something builds.
- **CSS Modules were stubbed in tests.** Every property of a `styles` object resolved to a
  truthy string, so `styles.thisClassWasDeleted` was defined and any assertion that a component
  applied a class could not fail. Fixed with `test.css.include`, and the assertions rewritten
  to compare against the imported module.

  Worth recording how this nearly went wrong: setting `classNameStrategy: "non-scoped"` — the
  option that appears to be the fix, and the one this document originally prescribed — tells
  Vitest to **skip** processing and keep returning the proxy. The suite stayed green. It was
  caught only by deleting a class and checking the tests failed, and the first attempt at
  _that_ was also wrong: renaming `.ghost` left `.ghost:hover` defining the key, so the check
  passed for the wrong reason. Verifying a fix is as easy to fake as the fix itself.

- **Half the TypeScript was unlinted.** Package scripts covered `src` only. Widening to `.`
  immediately failed on files outside any tsconfig, which is why the narrow glob existed —
  build tooling is not shipped, so it appears in no project graph, and the type-aware parser
  errors rather than linting it. Build tooling now gets the syntactic rules with type-aware
  rules disabled, which is what actually goes wrong in build scripts.

### 22. Config accepted development defaults in production (O5) 🟡 MED

A missing `CAIRN_DATABASE_URL` in production booted successfully against whatever answered on
localhost. `is_production` was defined and never consulted.

**Fixed:** a model validator rejects localhost, `127.0.0.1`, and the published development
password whenever `CAIRN_ENVIRONMENT` is not `local`, and refuses `database_echo` outside local
development — SQL echo writes customer data into log storage.

### 23. Tenant context was lost on a mid-block commit (O10) 🟡 MED

`SET LOCAL` dies with its transaction. A handler that committed mid-block left every subsequent
statement running with no tenant scope — RLS present, policies intact, and nothing enforced.

**Fixed:** an `after_begin` listener re-applies the setting on each new transaction, with a test
that commits inside the block and asserts isolation still holds.

---

### 24. Coverage thresholds nobody consulted (O12) 🟢 LOW

`fail_under = 80` in `pyproject.toml` and matching thresholds in two Vitest configs — and no
CI job ran a command that reads any of them. A floor nothing stands on is not a floor; it reads
in review as though coverage is enforced.

**Fixed:** CI runs `pnpm test:coverage` and `pytest --cov`. Turning it on immediately proved the
point — `@cairn/types` reported 19%, because coverage was measuring `eslint.config.js` and the
codegen script rather than the package. Coverage is now scoped to `src/**`, with generated code
excluded on the same grounds ESLint ignores it: its correctness belongs to the generator and is
checked by the schema-drift test, not by hand-written tests asserting that a generator emitted
what it emitted.

`--cov` is in the CI invocation rather than `addopts`, deliberately. In `addopts` it slows every
local run and fails thresholds on a partial test selection, which trains people to pass
`--no-cov` — a floor that gets routinely bypassed is worse than no floor, because it still reads
as enforcement.

Python now sits at 90%. The gap that mattered was `config.py` at 54%: the production guard
added in §22 was a boot-time control with almost no test behind it, which is precisely the
shape of finding this audit keeps turning up. It now has sixteen, including a positive control
— without one, a validator that rejected every configuration would have passed the whole class.

---

### 25. Rate limiting and route-level authorisation (O2b, O4) 🟠 HIGH

Both were deferred with the same justification — they need the API layer — and both landed with
it in Step 9.

**O2b.** Login and signup now consume two budgets before any Argon2 work: per email address, and
per client address. Both, because either alone is evaded — a per-account limit does nothing
against an attacker spreading a leaked list, and a per-address limit does nothing about one
account being hammered from a botnet. Counting is not keyed on success: counting only failures
lets an attacker with one valid credential reset their budget at will, and the CPU cost is paid
either way.

The client address is taken from the **rightmost** `X-Forwarded-For` entry, which is the one the
infrastructure appended. Taking the leftmost — the common mistake — hands an attacker a fresh
bucket per request by setting one header.

The backend is in-process, so on Cloud Run the effective limit is N times the configured one and
resets on instance recycle. Stated in the module docstring rather than a ticket: an in-memory
limiter that reads as authoritative is precisely the pattern this audit keeps finding. Redis
lands with Step 10.

**O4.** `require()` now runs as a route dependency — `requires(Permission.MEMBERS_INVITE)` — so
the requirement is visible in the signature rather than buried in a handler. Seven HTTP tests
assert it, including the two escalation paths: a Member cannot invite at all, and an Admin
cannot mint an Owner.

### 26. A type annotation that was a lie 🟡 MED

Found while writing the first HTTP test that touched an invitation.

`Membership.role` was the PostgreSQL `tenant_role` enum; `Invitation.role` was `VARCHAR(16)`.
Both are annotated `Mapped[TenantRole]`. SQLAlchemy coerces an `Enum` column back to the enum on
load and leaves a `String` column as `str`, so the same logical value arrived as a different
Python type depending on which model had read it.

What makes this worth recording is why it stayed hidden. `TenantRole` is a `StrEnum`, so
comparisons, dict lookups, `_RANK[role]` and every permission check kept working against the
plain string. Nothing failed until something reached for actual enum behaviour — `.value` — at
which point it was an `AttributeError` inside a request handler that no type checker had flagged,
because the annotation claimed otherwise.

**Fixed:** migration `c4a71b8e35d6` gives both columns the same type. The database gains a real
constraint too — `VARCHAR(16)` accepted `'superuser'` quite happily.

### 27. The API's own tests could not boot the API 🟡 MED

The production guard added in §22 refuses localhost outside `local`. The API test fixtures build
settings with `environment="test"`, so the guard refused to start — correctly, by its own rules,
and wrongly in intent.

`test` names two different things: the automated test run against a throwaway container, and a
deployed test environment. The guard assumed the second; the fixtures meant the first.

**Fixed:** `local` and `test` are the non-deployed environments, named in one place
(`NON_DEPLOYED_ENVIRONMENTS`) and consulted by every rule. `test` is documented as the automated
run, with pre-production being `staging` — guarded exactly like production. The alternative, and
the tempting one, was to weaken the validator for everyone.

---

### 28. The rate limiter was per-instance (O2b, fully closed) 🟠 HIGH

Step 9 closed half of O2 by moving Argon2 off the event loop and added an in-process limiter for
the other half, with the limitation stated in the module rather than hidden: on Cloud Run with N
instances the effective limit is N times the configured one, resetting whenever an instance is
recycled. Honest, and still a real weakening — an attacker benefits from it without needing to
know it exists.

**Fixed:** a token bucket in PostgreSQL, shared by every instance. The interesting part is what
was _not_ chosen. Redis is the reflexive answer and would be faster; it is also infrastructure to
provision, secure, monitor and pay for, whose sole consumer would be one table. Postgres is
already here and already in the same failure domain as the thing being protected. The cost is one
indexed upsert per login attempt.

Refill, test and deduction happen in one statement, so the row lock serialises concurrent
callers — asserted with 25 concurrent checks against a limit of 5, and with two limiter instances
sharing one budget, which is the defect this replaces.

Stale buckets are swept hourly by the worker rather than opportunistically during a check, so no
login pays for someone else's cleanup. Deliberately _not_ a queued job: job handlers receive a
tenant-scoped session by design, and `rate_limit_buckets` is not tenant-scoped because rate limits
apply before authentication. Routing it through the job runner would have meant giving every
handler a platform session — dissolving the isolation guarantee for the sake of one cleanup task.

### 29. A new table quietly widened the application role's grants 🟡 MED

Adding `rate_limit_buckets` broke `test_application_role_grants_are_an_explicit_allow_list`,
which pins every privilege the application role holds.

That is the guard working exactly as intended. The test exists because a default-privileges rule
once granted the application role full DML on every table created afterwards, making "reachable
by every tenant" the default posture for anything new while row-level security stayed opt-in —
which is how the auth tables ended up exposed in round one.

**Resolved by stating the case in the allow-list**, not by widening it silently: this table is
deliberately outside row-level security, it holds no customer data, and a caller who could read
it learns only how much allowance a key has left. The point is that the decision is now written
down next to the grant rather than implied by a migration.

---

### 30. `create_app(settings)` was decorative 🟠 HIGH

The app factory takes a `Settings` instance. It used it for startup — CORS origins, middleware,
the rate-limiter backend, the queue — and every request handler then called `get_settings()`,
which is `lru_cache`d and reads the process environment. Two different objects, one of them
ignored.

Invisible in every deployment, because there the environment _is_ the source of truth and the two
always agree. It surfaced only when a test constructed an app with a webhook secret and the
endpoint reported having none configured — eleven tests failing on a control that was reading past
its own configuration.

Worth recording because of what it would have cost later: any per-environment behaviour added to a
handler would have silently ignored the factory argument, and the first place that matters is
exactly here — an unauthenticated endpoint whose security depends on a configured secret.

**Fixed:** the settings dependency reads `request.app.state.settings`. The factory argument now
means what it says.

### 31. A timing-dependent test 🟢 LOW

A depth-reporting test slept 70 ms and asserted three calls at a 20 ms interval. It passed in
isolation and failed in the full suite: a loaded event loop does not schedule a timer as often as
the arithmetic suggests.

Fixed rather than retried, because a test that fails for reasons unrelated to the code is worse
than no test — it trains people to re-run CI instead of reading it. Rewritten to wait on a
condition, with the timeout as a deadlock guard rather than the thing being measured. Verified
across two consecutive full-suite runs.

---

### 32. Bot co-author trailers entered human attribution 🟠 HIGH

GitHub App actors commit under addresses like
`49699333+dependabot[bot]@users.noreply.github.com`. The pattern recovering a login from a
noreply address allowed only GitHub handle characters, so it matched nothing for those addresses
and returned `login=None`.

The bot filter keys on the login. With none, Dependabot's `Co-authored-by` trailer passed straight
through into human attribution — so a workspace using squash merges would have credited a bot as a
contributor alongside its people, and the more automation a team ran, the worse the record looked.

This is exactly the interaction md/01 §5.2 warns about: naive co-author parsing does not merely
fail to exclude bots, it _actively imports_ them. What is worth recording is that the cause was a
character class, not a missing feature — the filtering code was present, correct and unreachable.

**Fixed** by admitting `[` and `]` to the login pattern. Verified by reverting the regex and
watching `test_a_bot_co_author_trailer_is_filtered` fail with Dependabot's address in the people
list.

### 33. Merging two people destroyed their identities 🟠 HIGH

`merge()` reassigned each identity's `person_id` column and then deleted the absorbed person.
`Person.identities` cascades `delete-orphan`, and the ORM still held those rows in the absorbed
person's collection — so the delete cascaded to them.

The merge silently destroyed the identities it existed to preserve. Worse, this is a _correction_
path: someone would notice their record was split, ask for a merge, and end up with less than
before. The failure would look like the product losing data in response to being told it was wrong.

**Fixed** by moving identities through the relationship rather than the foreign key, with both
collections loaded explicitly first — an unloaded relationship raises `MissingGreenlet` under
asyncio rather than silently doing IO, which is how the second half of this was found.

---

### 34. A backfill held its lease while yielding the worker 🟡 MED

`process_batch` deliberately stops after a bounded number of pages so the run releases its worker
slot and fair scheduling can let live events through. It did not release the _lease_.

The consequence: a run that yielded stayed unclaimable for the remainder of its five-minute lease.
Only the worker that happened to process the last batch could resume it sooner, so a customer's
ninety-day import proceeded in five-minute steps regardless of how much capacity was free — minutes
of onboarding spent waiting on a timer.

Not a correctness bug, which is why it survived the tests: every assertion about resumption passed,
because the same worker was doing the resuming. It surfaced when a demonstration used a different
worker name per batch, the way a real worker pool does.

**Fixed:** the lease releases on every exit path from `process_batch` — completion, throttling,
failure and ordinary yielding. The lease protects work _in flight_, not the gaps between batches.
A test now asserts a different worker can claim the run immediately after a yield.

Worth recording as a category: this is the second finding in two steps that only appeared when the
code was _run_ rather than tested. Tests assert the properties someone thought to state; a
demonstration exercises the sequence a real system performs.

---

---

## Round four — Steps 9 to 14, and a pattern worth naming

Seven findings. **Five were code that existed, was correct, was tested, and was never
reached.** Not a condition inverted or a boundary off by one — a job type with no
handler, a status value never written, an endpoint that could not be created, a gate
reading a ratio over zero.

That is a different failure class from the previous three rounds, and unit tests cannot
catch it by construction: a correct function tested in isolation passes whether or not
anything calls it. What found these was asking, of every public function, _who calls
this in production_ — and getting the answer "nothing" seventeen times.

### 35. The evaluation gate passed a pipeline that asserted nothing 🔴 CRITICAL

The worst of the seven, because it is in the instrument built to catch everything else.

Every metric is a ratio, and a ratio over zero is 1.0. A pipeline that abstained on
every case produced no claims — so groundedness and attribution accuracy were both
computed as **100% over nothing**, and the release gate passed it. It generated a
missed-signal finding on all fourteen cases while doing so.

`report.py` already carried the comment: _a "100%" with nothing behind it has misled
more dashboards than any wrong number._ The renderer showed the denominator. The gate
ignored it. The hazard was identified, written down, and then not guarded against —
which is worse than not having noticed.

**Fixed:** a coverage check that runs _before_ any ratio is trusted. Non-abstention
cases must produce claims, or the gate blocks with "metrics computed over too few claims
to mean anything". Coverage is now rendered next to the metrics rather than buried,
because every other number is meaningless when it is low.

### 36. Per-address rate limiting was one global bucket 🔴 CRITICAL

`client_address` read the **rightmost** `X-Forwarded-For` entry, with a docstring
confidently explaining that everything to its left is client-supplied and forgeable.
That reasoning is correct in general and wrong for this deployment.

The header grows left to right: each proxy appends the address it received _from_. The
rightmost entry is therefore written by the platform's own front end — on Cloud Run,
Google's infrastructure, identical for effectively all traffic.

So every caller in the world shared one bucket. `LOGIN_PER_ADDRESS` (50 per 15 minutes)
was a **global** limit: fifty failed logins anywhere would lock out every customer.
`SIGNUP_PER_ADDRESS` (5 per hour) meant the entire product could accept five signups an
hour.

The limiter was correct. The shared store — the fix from round three — was correct. The
key was wrong, so none of it did anything. Both naive readings fail in opposite
directions: leftmost trusts a client-supplied value and hands an attacker a fresh bucket
per request.

**Fixed:** count back a configured number of trusted hops, because the count is a
property of the deployment rather than of the code (`trusted_proxy_hops`, default 1).
Five tests cover one hop, two hops, forged leading entries, a short chain, and no header.

### 37. Backfill had no ignition 🟠 HIGH

`BACKFILL_JOB` was defined. `create_run`, `claim` and `process_batch` were written,
documented and tested. **Nothing registered a handler and nothing published the job.**

A run would be created and sit in `PENDING` forever. There were not even dead letters to
notice, because nothing was ever enqueued — the queue's own safety net, which catches a
job type with no handler, requires the job to be published first.

Step 13 passed twenty-seven tests and could not run.

**Fixed:** `github/jobs.py` registers the handler and publishes at `BULK` priority,
re-enqueuing between batches rather than looping — looping would undo the worker release
`process_batch` returns for. A regression test asserts every job-type constant resolves
to a registered handler.

### 38. Nothing could connect a GitHub installation 🟠 HIGH

Only a test fixture ever created a `GitHubInstallation`. The webhook resolved them,
backfill required them, and no production path created one — so Steps 11, 12 and 13 were
unreachable end to end. Every test passed because every test built the row itself.

The tempting fix is to let `installation.created` create the mapping, and it is wrong:
whoever installed the app would have their activity bound to a workspace nobody chose.
That is why the webhook deliberately ignores it, and that reasoning still stands.

**Fixed:** `POST /v1/workspaces/{id}/integrations/github`, behind a session, a membership
and `INTEGRATIONS_CONNECT` — the point at which we know who asked. It binds the
installation, revives a previously uninstalled row rather than duplicating it, and starts
backfill runs at BULK priority. A test asserts the webhook module still cannot construct
one.

### 39. Two delivery statuses were defined and never written 🟡 MED

`DeliveryStatus.FAILED` was never set, so a delivery that exhausted its retries stayed
`ACCEPTED` forever — "queued" and "permanently failed" were the same value, and the
column could not answer the single question it exists for.

`DeliveryStatus.UNCLAIMED` was never set either, while its own docstring said such
deliveries were "recorded rather than dropped so 'we are getting nothing from GitHub' has
an answer". The handler logged and returned.

**Fixed:** the worker records the error on every attempt and marks `FAILED` at the final
one; the webhook records unclaimed deliveries when there is a tenant to attribute them
to, and says so when there is not. A test asserts every enum value is reachable from
production code.

### 40. Duplicate job-type constant 🟢 LOW

`GITHUB_DELIVERY_JOB` was defined in two modules — two sources of truth for a string that
must match across a queue boundary. They agreed, which is exactly why nobody noticed.
**Fixed**, with a test that fails if it is defined twice again.

### 41. Dead code 🟢 LOW

`emulator_host()` had no caller anywhere, not even in tests. Small, and they accumulate:
each one is something a reader must decide is irrelevant. **Removed**, with the name
listed in a test so re-adding it silently is not possible.

---

### What round four says about the process

The previous rounds found controls that appeared to work. This one found **code that was
never reached at all** — which no amount of unit testing detects, because the unit passes.

The question that found them is worth keeping: _for every public function, who calls this
in production?_ Seventeen answered "nothing". Most were legitimately test-only or awaiting
a later step; five were defects.

The demonstration habit from Steps 10 and 13 found two of these independently. Running the
thing exercises the sequence a real system performs; tests exercise the sequence someone
thought to write down.

---

## Round four, part two — the carried-over findings

The four items that had been open across every previous round. Two were real, one was
stale, and one was partly stale — recorded that way rather than quietly ticked off.

### 42. Email verification, and the pre-registration hijack (O1) 🟠 HIGH

Open since round one and marked "before any real user data". The attack, in order:

1. Anyone registers `victim@company.com`. Signup requires no proof of address control.
2. They wait.
3. A colleague later invites that address to a real workspace.
4. The squatter's account accepts, and the real person is locked out of an invitation
   sent to their own inbox.

The address check on acceptance always passed, because the address does match. What it
never established was that the _account holder_ controls it.

**The shape of the fix matters more than the fact of it.** The obvious version —
require verification before anything — is wrong twice over. It puts an email round trip
in front of a new workspace owner, which is friction on the screen where abandonment
costs most, and it adds the same friction to invitation acceptance, the product's most
important conversion point.

So the gate is narrow and aimed at the actual attacker:

- **Signup stays open.** A squatter who owns only their own empty workspace has gained
  nothing.
- **Redeeming an invitation _is_ proof of address control**, because the token was
  delivered by email and nowhere else. A first-time invitee is verified by the act of
  arriving, not sent a second email to prove what they have already proven.
- **Only an existing _unverified_ account is blocked** from claiming an invitation. That
  is precisely the squatter, and nobody else.

Three further properties, each closing a smaller door: tokens are stored as SHA-256 like
sessions and invitations; issuing a new one consumes any outstanding one, so an
intercepted older email stops working the moment someone asks for a fresh link; and a
token records the address it was issued for, so changing address while a token is
outstanding cannot verify the _new_ address on the strength of mail sent to the old one.

The application role holds **no privilege at all** on `email_verifications` — a scoped
session able to insert there could verify an address it does not control, which is the
same attack from inside the product. Two tests assert both the read and the write are
refused.

Fourteen tests, three of which reproduce the hijack end to end.

### 43. The certainty tooltip was pointer-only (O15) 🟡 MED

`CertaintyBadge` explained itself through `title`, which appears on hover and nothing
else. A screen reader user received the explanation through `aria-label`; a **sighted
keyboard user could not reach it at all** — WCAG 1.4.13, and the group least likely to
be represented in a manual test.

**Fixed:** the badge is focusable and the description is revealed on hover _and_ focus,
positioned above the badge because one opening downward covers the line the reader is
on. The visible copy is `aria-hidden`, or a screen reader announces the same sentence
twice.

This required overriding `jsx-a11y/no-noninteractive-tabindex`, which is a correct
default — a tab stop that does nothing is an obstacle. Disabled inline with the
reasoning rather than by loosening the rule's config, because an allowlist entry for
`img` would permit it on every image in the system, where it would be exactly the
obstacle the rule describes.

### 44. Two findings that were already stale 🟢 LOW

Recorded rather than silently dropped, because a register that only ever grows in one
direction stops being read.

**O11 — "fixture teardown truncates whole tables".** It does not, and no longer needs
to: the session-scoped `engine` fixture drops and recreates the schema before the suite
runs, so accumulation is bounded to a single session. The finding described an earlier
implementation.

**O13's `attempt` item — "never incremented".** `JobEnvelope.next_attempt()` is called
by the broker on every retry, and Step 10's tests assert the count advances. This was
true when the finding was written and stopped being true when the queue was built.

### 45. The rest of O13, which was real 🟢 LOW

**`certaintyTreatment` specified an opacity nothing applied**, while three documents told
readers opacity was how tiers differ. The component was right and the tokens were wrong:
dimming text to 75% multiplies its contrast by roughly the same factor, so `fg.muted` at
0.75 lands near 3:1 — below the 4.5:1 the design system asserts everywhere else, on the
tier a person is most being asked to check.

Nothing shipped broken, because the component ignored it. The risk was the reverse: a
future engineer making the code match the documentation would have introduced the
failure. Opacity is gone, replaced by an explicit border token, and a test asserts no
treatment carries an opacity again.

**`spaceToPx` had no caller.** Kept rather than deleted — it is the only way to assert
the 4px rhythm, and a step added with an off-rhythm rem value looks right in isolation
while breaking the alignment of everything beside it. It now has the test it was written
for.

**The open register is empty.** For the first time since round one, nothing is carried
forward.

## Open — recorded deliberately, not overlooked

**Nothing is open.** Every finding from rounds one to four is fixed and guarded by a test
that fails if it returns.

That is a milestone and not a resting state. The register was never empty before, and it
will not stay empty: the next audit will find things, because every previous one has —
including in code written immediately after the previous audit. What changed is that
there is no longer a backlog of known defects being carried past a gate.

Two habits produced most of the findings and are worth keeping:

- **Ask who calls this in production.** Round four's five unreachable-code findings all
  came from that one question, and no unit test can answer it — a correct function tested
  in isolation passes whether or not anything calls it.
- **Watch the check fail before recording a fix.** Every fix in rounds three and four was
  verified by breaking it on purpose first. Twice that revealed the "fix" did nothing.

---

## What this audit says about the process

Five of the nine fixed findings were **tests or controls that appeared to work and did not**: RLS policies neutered by an OR'd permissive policy, auth tables outside RLS entirely, a CI suite skipping its own safety net, a positive-control-free isolation test, a drift check that never ran.

That is the recurring shape of risk in this codebase, and it is worth naming: **the dangerous failures here do not announce themselves.** `pg_policies` was populated, `relforcerowsecurity` was true, CI was green, and none of it was doing anything.

The habit that caught them — asking _why_ something passes rather than accepting that it does — is the one to keep through Stage B.

Round three added a variation worth recording separately: **a fix can be as fake as the bug.**
Enabling CSS Module processing appeared to work, and did not — the option that looks like the
fix silently disables the behaviour it seems to enable. The first attempt to verify _that_ was
also wrong, because renaming one selector left another still defining the class. Two layers of
false confidence stacked on a low-severity finding nobody would have looked at twice.

The rule that survives all three rounds: **do not record something as fixed until you have
watched the check fail.** Every fix in round three was verified by breaking it on purpose first.

---

# Stage C Architecture & Delivery Audit

**Date:** 15 August 2026
**Scope:** Everything built in Steps 1–18, plus the architecture and the SDLC posture
**Method:** One question applied to every module — _who calls this in production?_ — followed by
targeted verification of each answer.

**Why this round is different from the four before it.** Rounds one to four found defects _inside_
working systems: a policy that was not enforcing, a regex that let a bot through, a lease that was
never released. This round found something categorically worse and much harder to see: **code that
is correct, tested, documented, and connected to nothing.**

---

## The headline finding — the Understanding layer had no callers 🔴 CRITICAL

`classify`, `extract`, `resolve`, `store.apply`, `graph.build`, `retrieve` and `synthesize` — roughly
2,500 lines at 90% coverage, four stages, a temporal graph and a synthesis pipeline — were imported
by **tests and the evaluation harness only**. The real ingestion path ran:

```
webhook → verify HMAC → queue → attribute() → log counts → done
```

No fact was ever written in production. Every unit test passed, because every unit was correct.

**This is the failure mode the previous audit named and did not fully close.** Round four found five
instances of unreachable code and recorded the lesson — _ask who calls this in production_ — and
then Steps 15–18 built four more layers the same way. Recording a lesson is not the same as changing
the habit that produces it.

**The habit that produces it, stated plainly:** building horizontally. A layer is finished, tested to
a high standard, and left for a later step to connect. Each step's exit criterion is met honestly, and
the system as a whole does nothing. **The counter-habit is a vertical slice: no layer is "done" until
something in production calls it.**

---

## Findings and resolutions

| #   | Finding                                                        | Severity | Resolution                                                                                                         |
| --- | -------------------------------------------------------------- | -------- | ------------------------------------------------------------------------------------------------------------------ |
| C1  | Understanding pipeline had zero production callers             | 🔴       | Job type, handler and publisher added; wired into the ingestion path after attribution                             |
| C2  | `apps/web` was an empty directory — no frontend existed        | 🔴       | Application shell built: routing, auth flow, design system, accessibility                                          |
| C3  | No API surface for facts or briefs                             | 🔴       | `GET /workspaces/{id}/facts` and `/brief`, paginated and tenant-scoped                                             |
| C4  | CI's evaluation gate graded the stand-in, never the product    | 🔴       | Runner grades the real pipeline; both runs in CI                                                                   |
| H1  | `graph.build` was O(n²) over the whole workspace, every run    | 🟠       | Incremental build with a candidate index; fan-out ceiling, logged when it trips                                    |
| H2  | `store.load_current` loaded every valid fact per batch         | 🟠       | Candidate query, proven a superset of what the full scan matched                                                   |
| H3  | Both Vertex adapters only raised — no client existed           | 🟠       | Implemented over the REST API, exercised by a stubbed transport; `live_check` for the one thing tests cannot cover |
| H5  | Token counts recorded, never aggregated or capped              | 🟠       | Per-tenant spend accounting as a provider decorator; typed error on ceiling                                        |
| H6  | Production imported `Certainty` from its own test harness      | 🟠       | Canonical definition in `domain.py`; `evaluation` re-exports; three private rank tables collapsed to one           |
| H7  | The embedding model name was a default argument in two modules | 🟠       | One `DEFAULT_EMBEDDING_MODEL`; a mismatch had failed silently by returning nothing                                 |
| M1  | `store.py` race paths untested                                 | 🟡       | Covered                                                                                                            |
| M2  | `attach_people` was N+1 per batch                              | 🟡       | Batched                                                                                                            |
| M3  | No test crossed more than two layers                           | 🟡       | Webhook → job → fact → API integration test                                                                        |
| M4  | No performance test anywhere                                   | 🟡       | Added, asserting on operation counts rather than wall-clock                                                        |
| M5  | `asgi-lifespan` was undeclared; a `uv sync` deleted it         | 🟡       | Declared; full dependency audit against every import                                                               |
| M6  | No container, no container build in CI                         | 🟡       | Multi-stage Dockerfile, non-root, CI build job                                                                     |

---

## What this audit says about the process

Two failures of _verification method_, both worth keeping:

**The evaluation gate was measuring itself.** CI ran the harness against `ReferencePipeline`, which
returns each case's own expectations. It printed `PASS`, and the number meant "the grader works".
Nobody reading the build output would have known the product had never been scored. A gate that
cannot fail for the reason it exists is decoration — and this one was _built_ to be honest, then
wired up in the one way that made it not.

**A stub can pass for an implementation indefinitely.** `VertexProvider` raised a well-written
exception explaining that credentials were missing. That honesty made it look finished — but "add
credentials and it works" was false, because no client had been written at all. **An adapter that
raises is not an adapter that is untested; it is an adapter that does not exist.**

The rule from earlier rounds still holds and gained a clause:

> Do not record something as fixed until you have watched the check fail —
> **and do not record something as built until something in production calls it.**
