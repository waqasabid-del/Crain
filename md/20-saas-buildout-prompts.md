# CAIRN — SaaS Build-Out Prompt Pack

**Purpose.** Take CAIRN from "a strong backend with an incomplete front door" to a two-sided, professional-grade SaaS: a **platform side** (CAIRN staff, `apps/internal`) and a **customer side** (tenant Owners, Admins, Members, Viewers in `apps/web`), with enterprise-grade auth and a design standard that does not drop at any step.

**How to use this pack**

1. Copy **Part 0 — The Standing Brief** into `CLAUDE.md` at the repo root (append it, don't replace what's there). Claude Code reads that file automatically on every session, so these rules apply to every step without you re-pasting them.
2. Then work through **Part 1 — The Steps** in order. Paste one step prompt per session. Do not skip ahead: each step assumes the previous one landed.
3. After each step, run the **Design Gate** and **Safety Gate** in Part 2 before you commit. If either fails, paste the failure back and say "fix this, do not proceed to the next step."

**Sequencing rationale.** Design foundation first (steps 1–2), because every screen after it inherits that system. Then the customer side's broken front door (3–8) — today an Owner literally cannot invite an employee from the UI, so nothing else matters. Then your platform side (9–14). Then proof (15–16).

---

# Part 0 — The Standing Brief

> Append everything between the rules below into `CLAUDE.md` at the repo root.

---

## CAIRN — Standing Engineering & Design Brief

You are working on CAIRN, a multi-tenant AI-native team operating system. This brief applies to **every** task in this repository. It is not advisory.

### The product has two sides. Never blur them.

- **Platform side (`apps/internal`)** — CAIRN's own staff. Roles: `SUPPORT`, `BILLING`, `ENGINEERING`, `SECURITY` (`db/staff_models.py`). Separate Next.js app, separate domain, separate session cookie, separate deploy.
- **Customer side (`apps/web`)** — a tenant company's people. Roles: `OWNER`, `ADMIN`, `MEMBER`, `VIEWER` (`db/models.py::TenantRole`). Exactly four; a test asserts there are never five.

Staff code and customer code must never share a route tree, a session cookie, or a bundle. A non-staff user hitting a staff API gets **404, never 403** — the back-office's existence must not be confirmable from a customer session.

### Hard product boundaries — not negotiable, not for any customer

CAIRN will never **allocate work, evaluate performance, score or rank an individual, or inform an employment decision.** These four properties keep the product outside EU AI Act high-risk classification and are the core of its trust proposition.

Concretely, this means you must never build:

- any numeric score, rating, grade, percentile, streak, leaderboard, or ranking of a person;
- any "productivity", "velocity per person", "activity level", or "last active" column on a member list;
- any admin view that shows more about an employee than that employee sees about themselves;
- any progress bar, badge, trophy, or gamification element attached to a human being.

`auth/permissions.py::can_view_person_record()` returns `True` unconditionally by design and must never consult its arguments. A test in `tests/test_permissions.py::TestSymmetryInvariants` fails the build if any permission name contains `view_details`, `view_member`, `inspect`, `monitor`, `evaluate`, `score`, `rank`, or `performance`. Do not weaken that test. If a feature you are asked to build appears to require any of the above, **stop and say so** rather than building it.

Admin power in this product governs **configuration**, never **surveillance depth**.

### Confidence is categorical, never numeric

Never render a confidence percentage anywhere in any UI. The only permitted vocabulary is the three certainty tiers — **Verified / Observed / Suggested** — expressed through language and visual weight, using the existing `CertaintyBadge` component. A "73% confident" badge is worse than useless.

### Design standard — every step, no exceptions

The design bar does not drop because a screen is "internal" or "just admin". Staff screens and customer screens are both held to the same standard.

**Design system.** Tailwind CSS + shadcn/ui components, re-skinned onto CAIRN's existing design tokens in `packages/ui` (color, layout, typography). Tokens are the source of truth for color and spacing — shadcn components must consume CSS variables derived from the tokens, never hardcoded hex values or Tailwind's stock palette. Both apps import the same `packages/ui` so the two sides read as one company's product.

**Every screen you build must ship all five states.** A screen is not done with only the happy path:

1. **Loading** — skeleton components matching the final layout's shape, never a bare spinner on a blank page.
2. **Empty** — a real empty state with an explanation and the single next action, never a blank area or the word "No data".
3. **Error** — a specific, human-readable message and a retry or recovery path. Never a raw status code or stack trace.
4. **Populated** — the normal case.
5. **Partial / degraded** — where data can be incomplete (an unconnected integration, an unverified member), say what is missing and why, rather than silently rendering less.

**Non-negotiable UI properties on every screen:**

- **WCAG 2.1 AA.** 4.5:1 contrast for body text, 3:1 for large text and UI boundaries, in **both** light and dark theme. `packages/ui`'s contrast-checking module must cover any new token pair you introduce. The European Accessibility Act has been in force since June 2025 — this is a legal requirement, not polish.
- **Full keyboard operation.** Every interactive element reachable by Tab in a sensible order, visible focus ring on all of them, Escape closes overlays, Enter/Space activate. Focus is trapped inside modals and returned to the trigger on close.
- **Semantic HTML and correct ARIA.** Real `<button>`, `<label>` bound to inputs, `<table>` with `<th scope>`, live regions for async status. Icon-only buttons carry an accessible name.
- **Responsive** at 360px, 768px, 1024px, 1440px. Data tables become readable cards on small screens, not horizontal scroll bars.
- **Dark and light theme**, both fully designed. Dark mode is not an inverted stylesheet.
- **Motion respects `prefers-reduced-motion`.**
- **Forms:** inline field-level validation on blur, errors described by `aria-describedby`, submit disabled with a reason while pending, success confirmed explicitly. Destructive actions require typed confirmation of the resource name, never a bare "Are you sure?".
- **Copy:** plain English, no jargon, sentence case for headings and buttons. Say what happens next. Never blame the user.

**Bundle budget.** `apps/web` deploys to Cloudflare Workers via OpenNext and CI enforces a 3 MiB worker bundle. Import shadcn components individually; never barrel-import an entire library. If a step pushes the bundle near the limit, say so rather than quietly raising the ceiling.

### Engineering rules

- **Trunk-based, Conventional Commits** (commitlint enforces the format).
- **Tenant isolation is the first thing you break and the last thing you notice.** Every DB read/write on customer data goes through an RLS-bound session (`db/tenancy.py::tenant_session`). Every background job carries `tenantid` in its envelope. `db/preflight.py` refuses to start if the app role has `BYPASSRLS` — never work around it.
- **Coverage is a floor (80%), never a target.** A PR at 85% coverage with no error-path test fails review. A PR at 75% with real behavioural tests passes. Always test the failure paths, not just the happy path.
- **Write the failing test first, watch it fail, then fix it.** Do not record something as done until you have seen its check fail for the right reason.
- **The single most important review question in this codebase: "what calls this in production?"** This repo has a documented, repeated history of correct, well-tested code with zero production callers — a neutered RLS policy, an evaluation gate that scored 100% over zero claims, an entire understanding pipeline nothing invoked, and three fully-typed invitation API methods no screen has ever called. Before you report any step complete, grep for the call sites of everything you wrote and state them explicitly. "It has tests" is not evidence that it runs.
- **Comment budget:** ≤15% of non-blank lines in logic files, ≤35% in declaration/schema files (`pnpm comments` / `scripts/comment_ratio.py` measures it). Comments explain _why_, never _what_.
- **Audit logging:** every staff action against a tenant writes to the hash-chained `internal_audit_log` via the `audited(action)` dependency, with a required human-written reason. The chain is append-only at the DB grant level — never add UPDATE or DELETE.
- **Secrets** never in code, never in migrations. `scripts/check-secrets.sh` runs pre-commit and gitleaks runs in CI; both have missed a hardcoded password before, so read your own diff.

### Definition of done for every step

Blocking — the step is not done without all of these:

1. Tests written covering happy path **and** failure paths; suite green.
2. Every new function/endpoint/component has a stated production call site.
3. Tenant isolation verified where customer data is touched.
4. **AI boundary check:** the feature cannot score, rank, evaluate, or allocate a person.
5. **Symmetry check:** no tenant role can see more about an individual than that individual sees about themselves.
6. **Design gate:** all five screen states built; keyboard-only pass; contrast pass in both themes; responsive at all four breakpoints.
7. No secrets; CI green.

If you cannot meet a rule, **say which one and why** in your summary. Do not silently skip it, and do not weaken a test or a threshold to make something turn green.

---

_(end of standing brief)_

---

# Part 1 — The Steps

Each step below is a self-contained prompt. Paste the fenced block into Claude Code as your message for that session.

---

## Phase A — Design Foundation

_Everything after this inherits whatever you build here. Do not rush these two steps._

### Step 1 — Install the design system

```
Set up Tailwind CSS + shadcn/ui in this monorepo, driven by CAIRN's existing design
tokens, so that both apps/web and the future apps/internal render from one system.

Read first: packages/ui in full (tokens, Button, CertaintyBadge, the contrast-checking
module and its tests, and the preview app), plus apps/web/src/app and a few existing
CSS Module components so you understand the current styling approach.

Build:
1. Tailwind configured in packages/ui and consumed by apps/web. Map every existing
   design token to a CSS custom property, and generate the Tailwind theme from those
   properties. Tailwind's stock palette must be unavailable — a developer typing
   `bg-blue-500` should get nothing. Only CAIRN token colours resolve.
2. shadcn/ui installed into packages/ui (not into the apps), configured to emit
   components that consume our CSS variables. Add this component set now:
   Input, Label, Textarea, Select, Checkbox, RadioGroup, Switch, Button variants,
   Dialog, AlertDialog, Sheet, DropdownMenu, Popover, Tooltip, Tabs, Card, Table,
   Badge, Avatar, Skeleton, Alert, Separator, ScrollArea, Toast (sonner), Command.
   Re-skin each one to the tokens. Keep our existing Button and CertaintyBadge as the
   canonical versions — do not let shadcn's Button replace ours; reconcile them.
3. Light and dark theme as fully designed palettes, not an inversion. A theme provider
   with system-preference default and a persisted user override.
4. Three CAIRN-specific primitives that do not exist in shadcn and that we will reuse
   on every screen: EmptyState (icon, headline, explanation, one primary action),
   PageHeader (title, description, actions slot, breadcrumb slot), and DataTable
   (sortable, keyboard-navigable, with built-in loading/empty/error states, and a
   card layout below 768px).
5. Extend the contrast-checking module so it fails the test suite on any token pair
   in either theme that drops below WCAG AA. Every new component must be covered.

Constraints:
- CSS Modules currently exist in apps/web. Plan the coexistence explicitly: Tailwind
  and CSS Modules must both work during migration. Do not rewrite existing screens in
  this step — that happens as each screen is touched in later steps.
- apps/web has a 3 MiB Cloudflare Worker bundle limit enforced in CI. Measure the
  bundle before and after and report both numbers. Import components individually.
- Note that the repo's audit history found CSS Modules stubbed to always-truthy in
  tests, so style assertions were meaningless. Make sure the new setup produces tests
  that would actually catch a broken style.

Done when: the suite is green including new contrast tests, the worker bundle is
measured and under budget, and every component above renders in the preview app.
```

### Step 2 — Prove the design system

```
Rebuild packages/ui's preview app into a real, reviewable design reference, so that
from this point on "does this look professional" is a question with an objective answer.

Build a preview site that renders, for every component in packages/ui:
- every variant and size
- every interaction state: default, hover, focus-visible, active, disabled, loading,
  error, read-only
- both light and dark theme, toggleable, side by side where useful
- at 360px, 768px, 1024px and 1440px

Add pages that demonstrate the composed patterns every later step will copy:
- a full page layout with PageHeader + content + sidebar
- a form with inline validation, a pending submit, a field-level error, and a success
- a DataTable in all four states (loading / empty / error / populated)
- a destructive-confirmation AlertDialog with typed confirmation
- a toast for success, error, and an undoable action
- an EmptyState for: nothing yet, nothing matched a filter, and blocked-by-setup

Write a short design reference at packages/ui/DESIGN.md covering: the token scale and
what each token is for, when to use which component, the five required screen states,
the copy rules (sentence case, plain English, say what happens next), and the
accessibility checklist every screen must pass. Keep it under 300 lines and make it
useful to somebody building screen 40, not a manifesto.

Also add an automated accessibility check (axe or equivalent) over the preview pages
in CI, so an inaccessible component fails the build rather than a review.

Done when: I can open the preview, tab through every component with a visible focus
ring, toggle both themes with no contrast failure, and the axe check is green in CI.
```

---

## Phase B — The Customer Side

_Today an Owner cannot invite a single employee from the product. These steps fix the front door, then make it enterprise-grade._

### Step 3 — Complete the authentication surface

```
Build out the customer-side authentication screens and the backend endpoints they
need, to a professional SaaS standard. Right now login/signup/invite-accept exist but
verification and password recovery are unreachable or absent.

Read first: apps/api/src/cairn_api/auth/service.py, auth/tokens.py,
api/routers/auth.py, db/auth_models.py, the email package in full, and
apps/web/src/routes/{LoginPage,InvitePage}.tsx plus onboarding/SignupPage.tsx.

Backend:
1. Password reset. New hashed, single-use, short-lived (1 hour) reset token, following
   exactly the security properties the invitation token already has: 256-bit CSPRNG,
   only the SHA-256 hash stored, single use, bound to the address, superseded when a
   new one is issued. Endpoints to request and to complete a reset. Requesting a reset
   for an address that does not exist must return the same response and take the same
   time as one that does — no user enumeration. Rate-limit per address and per client
   address. Completing a reset revokes every existing session for that user.
2. Wire the existing verify-email and resend-verification endpoints into
   packages/api-client — they exist and are tested on the API but the generated client
   has no method for them, so nothing can call them.
3. Confirm every one of these sends real mail through the existing SMTP sender and
   that the send is actually invoked from the endpoint. State the call sites.

Frontend — build these screens to the Step 1/2 design system, all five states each:
- /login — redesigned. Email + password, inline validation, a clear error that does
  not reveal whether the account exists, "Forgot password?" link, and a link to signup.
- /signup — redesigned.
- /verify — NEW. Currently verification emails link to a route that does not exist,
  which is why anyone who signed up before being invited is permanently locked out.
  Handle: valid token, expired token (with resend), already-verified, missing token.
- /forgot-password — NEW. Always shows the same confirmation regardless of whether the
  address exists.
- /reset-password — NEW. Token validation, password strength feedback, confirm field,
  clear success that leads to login.
- /invite — redesigned to the new system, keeping every existing security property
  (address-bound token, no session issued on redeem, unverified-account refusal) and
  making each of those refusals a clear, human explanation rather than a generic 409.

Do not weaken any existing security property to simplify a screen. If a security rule
makes a flow awkward, design around it and tell me what you did.

Done when: a person can sign up, verify their email, forget their password, reset it,
and log in — entirely through the UI, with no database access at any point.
```

### Step 4 — Member and invitation management

```
Build the invitation and member-management UI. This is the single highest-priority gap
in the product: apps/web has NO invite UI at all, while packages/api-client already
exports fully-typed invite(), listInvitations() and withdrawInvitation() methods with
ZERO call sites. PeoplePage.tsx even tells the Owner "Roles and invitations are changed
in Workspace settings, by an admin" — and when they go there, it isn't.

Read first: apps/web/src/routes/AdminPage.tsx and PeoplePage.tsx in full,
apps/api/src/cairn_api/api/routers/workspaces.py, auth/service.py::invite_to_workspace,
and packages/api-client/src/index.ts around the invitation methods.

Build in apps/web — a proper Members area under workspace settings:
1. Member list (DataTable): name, email, role, joined date, notification status.
   NOTHING ELSE. No "last active", no activity counts, no per-person metrics — the
   symmetry rule forbids it and a test enforces it.
2. Invite flow: a dialog taking one or more email addresses and a role, with the role
   selector showing plain-English descriptions of what each role can do. An Admin must
   not be offered the Owner role (the backend rank check already refuses it — the UI
   must not present an option that will fail).
3. Pending invitations: a list with invited address, role, who invited them, when it
   expires, and actions to resend and to revoke. Resend needs a new backend endpoint —
   today the only recovery from a failed send is revoke-and-reinvite, which is hostile.
4. Role change with an explicit confirmation explaining what changes.
5. Remove member, with typed-name confirmation, and a clear refusal when it would
   leave the workspace without an Owner.
6. Transfer ownership, with strong confirmation.
7. Fix the misleading copy on PeoplePage so it points at the place this now exists.

Backend additions: a resend-invitation endpoint (reusing the existing token, or minting
a fresh one and superseding — decide and justify), and expose enough invitation state
for the UI without ever returning the plaintext token in an API response.

Every mutation writes to the tenant's own audit trail, and the customer can see it.

Done when: an Owner can invite three colleagues, see them pending, resend one, revoke
one, change a role, and remove a member — all from the UI, with no curl and no
OpenAPI docs page.
```

### Step 5 — Fix the silent attribution failure

```
Fix a bug that will silently destroy the product's core value for real customers.

The problem: membership.notified_at is stamped in exactly one place — inside
GET /v1/workspaces/{id}/me/sources (api/routers/me.py) — and that endpoint is called
from exactly one screen, WelcomePage.tsx at /welcome. But /welcome is NOT in the app
navigation (see AppShell.tsx), and the only route to it is the ?next=/welcome redirect
from the invite page. Meanwhile pipeline/store.py refuses to link any fact to a person
whose notified_at is NULL.

So: any member who arrives by bookmark, a second browser, or because their Owner added
them via the API and just told them to log in, has every fact about them silently
dropped by the pipeline, forever. Nothing surfaces this to anybody.

Read first: api/routers/me.py (especially _record_notification), pipeline/store.py
(_unnotified_people and its call sites), apps/web/src/routes/WelcomePage.tsx, and
apps/web/src/components/AppShell.tsx.

Fix it properly:
1. Make notification an explicit, unmissable gate rather than a side effect of one GET.
   Any authenticated member whose notified_at is NULL is routed to the notice before
   they can reach any other screen, on every login, until they have seen it. This is a
   legal notification obligation, so it must not be skippable — but per the product's
   own principle it must read as an invitation carrying a trust promise, not a
   compliance notice. Their own record shows first, and correcting it is the first
   available action.
2. Stop stamping state inside a GET. Notification is acknowledged by an explicit
   action; make it a POST and say so in the endpoint's docstring.
3. Make the failure visible when it happens: the pipeline currently drops attributions
   silently. Emit a structured log and a counter, and surface un-notified members to
   the workspace Owner in the Members list from Step 4 with a way to nudge them.
4. Add the regression test that would have caught this: a member who logs in without
   ever visiting /welcome must not silently lose attribution.

Also redesign the notice screen itself to the new design system. This screen is,
per the product docs, "the highest-leverage design work in the product" — it is the
moment every employee forms their opinion of CAIRN, and it arrives before their
founder can frame it. Treat it accordingly.

Done when: it is impossible for a member to be active in the product with notified_at
still NULL, and a test proves it.
```

### Step 6 — Single sign-on (Google + GitHub)

```
Add real SSO for customer users. The OAuthIdentity and OAuthProvider models already
exist in db/auth_models.py and are referenced by NOTHING in the entire codebase —
no router, no service, no test. Note carefully: the GitHub/Slack/Google OAuth already
in this repo is workspace-CONNECTOR OAuth (connecting data sources), which is a
completely different concern from user sign-in. Do not entangle the two.

Build:
1. Google and GitHub sign-in with proper OAuth 2.0: state parameter, PKCE, nonce
   validation, strict redirect-URI allowlisting. Never derive a redirect from a Host
   header — the codebase already correctly builds links from configured public_app_url.
2. Account linking rules, and be extremely careful here because this is where SSO
   becomes account takeover:
   - Sign-in with a provider whose email matches an existing VERIFIED local account:
     link, after the user confirms with their password. Never link silently.
   - Provider email unverified at the provider: refuse. Do not trust it.
   - No existing account: create the user, mark the email verified (the provider
     verified it), no password credential.
   - Existing account, provider email differs: separate identity, do not merge.
3. Invitation acceptance via SSO: an invited person must be able to redeem their
   invitation by signing in with Google/GitHub instead of setting a password. Keep the
   existing rule that the invitation is bound to a specific address — the provider
   email must match the invited address or the redemption is refused.
4. Users with no password credential must not be shown "forgot password". Users with
   both must be able to manage each independently in account settings.
5. Unlinking a provider: refuse if it would leave the account with no way to sign in.
6. A "Connected sign-in methods" section in account settings showing what is linked,
   when it was last used, and how to remove it.

UI: sign-in buttons on /login, /signup and /invite, built to the design system, with
correct provider branding, keyboard accessible, and a clear error path when a provider
is unreachable or the user cancels.

Test the attack paths, not just the happy path: unverified provider email, mismatched
invite address, replayed state, CSRF on the callback, and linking to an account the
user does not control.

Done when: an employee can accept an invitation and sign in with Google, and a
security-minded reviewer cannot get into somebody else's account through any of the
paths above.
```

### Step 7 — Multi-factor authentication and session management

```
Add TOTP-based MFA and real session management to the customer side.

Build:
1. TOTP enrolment: QR code plus manual secret entry, verification of a code before
   enrolment completes, and ten single-use recovery codes shown once with a copy and
   a download action and an explicit "I have saved these" confirmation. Store recovery
   codes hashed, never plaintext. Regeneration invalidates all previous codes.
2. MFA challenge at login, with a clear path to use a recovery code, and rate limiting
   that resists brute force without locking a legitimate user out permanently.
3. Workspace-level enforcement: an Owner or Admin can require MFA for the workspace.
   Enforcement must not lock out existing members abruptly — give a grace period with
   clear in-app warnings, and never let an Owner lock themselves out. Members who have
   not enrolled are routed to enrolment on next login once the grace period ends.
4. Step-up re-authentication before genuinely sensitive actions, regardless of session
   age: approving a CAIRN support session, changing another member's role, removing a
   member, transferring ownership, deleting the workspace, disabling MFA, and changing
   or unlinking a sign-in method.
5. Session management UI in account settings: every active session with device,
   approximate location, sign-in method, created and last-used time, the current one
   marked, individual revoke, and "sign out everywhere". Note that logout_everywhere
   already exists in auth/service.py — wire the UI to it rather than reimplementing.
6. Security notification emails for: new sign-in method linked, MFA enabled or
   disabled, password changed, recovery codes regenerated.

Constraint: the tenant role matrix has exactly four roles and a test asserts it. MFA
enforcement is a workspace setting under the existing WORKSPACE_SETTINGS permission —
do not introduce a fifth role or a new permission tier for it.

Test: enrolment, challenge, recovery-code single use, clock skew tolerance, replay of
a used code, enforcement grace period, and the owner-lockout guard.

Done when: a workspace can require MFA, every member can enrol without support, and
nobody can lock themselves out of their own workspace.
```

### Step 8 — Customer account and trust surfaces

```
Finish the customer-side account and workspace surfaces so the product feels complete
rather than partially furnished, and redesign what already exists to the new system.

Build/redesign, all to the Step 1/2 design system with all five states:
1. Account settings: profile (name, avatar, work role), email address change with
   verification of the new address before it takes effect, password, sign-in methods
   (Step 6), MFA (Step 7), sessions (Step 7), and notification preferences.
2. Workspace settings shell with proper navigation: General, Members (Step 4),
   Integrations, Privacy & data sources, Security (MFA enforcement), Trust Center,
   Danger zone (transfer ownership, delete workspace with typed confirmation and a
   clear statement of what is destroyed and what is retained).
3. Trust Center redesign — this is a differentiating surface, not an afterthought.
   It must show: what CAIRN reads and what is switched off, per-source and per-person
   opt-out controls, the full support-session history (readable by EVERY member
   including Viewers, per the existing design), any active support session with a
   one-click "End access now", and the tenant's own audit trail.
4. Personal data controls: view my record, correct my record, export my data, and
   request deletion. The docs specify these and no screen implements them.
5. Empty-state onboarding checklist for a brand-new workspace: connect a source,
   invite your team, see your first brief. Honest about what is not yet connected.

Symmetry reminder while building all of this: the Owner's view of a colleague must be
identical to a Viewer's view of that colleague. Role changes what you can configure,
never how much you can see about a person.

Done when: every account and workspace action a customer would reasonably expect has a
screen, and no screen shows an admin something about a person that the person cannot
see about themselves.
```

---

## Phase C — The Platform Side (your back-office)

_This does not exist as a UI at all today. There is an API at `/v1/internal` with no interface, and no way to create your first staff account._

### Step 9 — Scaffold apps/internal

```
Create apps/internal — CAIRN's staff back-office — as a separate Next.js application
with its own domain, its own deploy, and its own session cookie. Your own architecture
docs (md/15, and Step 27 in md/16) already decided the staff UI belongs in a separate
app; this implements that decision.

Read first: apps/api/src/cairn_api/api/routers/internal.py in full (every route, the
current_staff gate, the audited() dependency, the role maps), db/staff_models.py,
internal/audit.py, and apps/web's app structure and build config as the template.

Build:
1. apps/internal as a Next.js app in the pnpm workspace, wired into Turborepo, sharing
   packages/ui and packages/api-client. It must NOT import anything from apps/web.
2. A staff-only session: a differently-named cookie, its own lifetime (shorter than the
   customer's 30 days — staff sessions should be hours, not weeks), and a separate
   origin. A customer session cookie must be useless against the internal app and vice
   versa. Explain in code comments why, so nobody "simplifies" it later.
3. A staff login screen, designed to the same standard as the customer side.
4. The staff guard: non-staff authenticated users get a 404 experience, not a 403 —
   the existence of the back-office must not be confirmable. Mirror the API's existing
   behaviour exactly.
5. The app shell: navigation reflecting the four staff roles, with sections hidden
   entirely (not disabled) when the role cannot use them. A persistent, unmissable
   indicator of which staff role the current session holds.
6. CI: lint, typecheck, test and build for the new app, added to the existing gate so a
   broken internal app fails the pipeline like anything else.
7. Deployment config separate from apps/web, with its own environment variables.

Do not build any tenant-facing back-office screens in this step. Scaffold, auth, shell,
CI, deploy. Get the boundary right before putting anything behind it.

Done when: a staff member can log into apps/internal, a customer cannot, a customer
session cannot be replayed against it, and CI builds both apps independently.
```

### Step 10 — Staff account bootstrap and management

```
Solve a real hole: NOTHING in this codebase creates the first staff account.
grant_staff in api/routers/internal.py requires an existing SECURITY-role staff member
to grant staff access — but no migration inserts one, db/seed.py seeds none, and the
tests insert StaffMember rows directly. Today the only bootstrap is manual SQL against
production, which is exactly the kind of access this product exists to make accountable.

Build:
1. A documented, auditable bootstrap path for the first SECURITY staff member. A CLI
   command that is safe to run once, refuses to run if any staff member already exists,
   requires explicit confirmation, and writes its own entry into the hash-chained
   internal audit log as the first link. Do not create a default account with a known
   password — the repo has already shipped a hardcoded credential in a migration once,
   and a whole audit round exists because of it.
2. Staff management screens in apps/internal (SECURITY role only): list staff with role
   and status, grant staff access, change role, revoke access. Every action audited
   with a required written reason.
3. Preserve and surface the existing guards in the UI: nobody can revoke their own
   staff access, and the last SECURITY account cannot be removed. Show these as clear
   explanations at the moment of the attempt, not as generic errors.
4. Staff sessions get MFA required — not optional. Anybody who can request access to
   customer data holds a second factor. Reuse the Step 7 TOTP implementation.
5. A staff activity view: what each staff member has done, readable by SECURITY.

Design to the same standard as the customer side. This is an internal tool that
handles customer trust; it does not get to look like an internal tool.

Done when: you can bootstrap the first security account safely, grant a colleague
support access, and see every one of those actions in a tamper-evident log.
```

### Step 11 — Tenant directory and consent-gated support access

```
Build the back-office screens for finding a customer workspace and — only with that
customer's approval — looking at it. The API for this is fully implemented and well
designed; it has no interface.

Read first: api/routers/internal.py (tenant list, tenant detail, the
active_configuration_session and active_content_session gates, the support-session
endpoints), internal/support.py in full, db/support_models.py, and
apps/web/src/routes/TrustPage.tsx (the customer's side of this flow, already built).

Build in apps/internal:
1. Tenant directory: search and list workspaces. Available to all four staff roles.
   These reads are deliberately not audited — keep it that way and note why in code.
   Show only what the list endpoint returns; do not invent columns.
2. Tenant detail, gated on an approved CONFIGURATION support session. When no approved
   session exists, the screen's default state is not an error — it is the request flow,
   explaining what will be visible, for how long, and that the customer will see the
   request and every access made under it.
3. Support session request: scope (configuration diagnostics vs activity content),
   requested duration, and a required written reason of 3-500 characters. Make the
   reason field feel consequential — the customer reads it. Show the maximum durations
   honestly (240 minutes configuration, 60 minutes content) and default to 60.
4. Session state UI: pending (waiting on the customer — show that clearly, with no way
   to bypass), approved with a live countdown to expiry, refused, revoked, expired.
   The customer can revoke mid-session; handle that arriving while a page is open.
5. An "activity content" view behind an approved CONTENT session only, remembering that
   BILLING role is structurally excluded from content and must never see the entry
   point at all.
6. Every read under a session calls record_access, which writes both a customer-visible
   event and an internal audit entry. Verify the call sites — do not assume.

Two constraints from the product's own operating rules:
- Operators may NEVER read customer message, channel or repo content to debug
  ingestion. Counts, states and categories only. Any screen that would show content
  needs an approved CONTENT session, and the runbooks say even then it is a last resort.
- Break-glass emergency access is deliberately NOT implemented, and the break_glass
  column is always false so the record can truthfully say so. Do not implement it.
  Do not add a UI for it.

Done when: a support engineer can find a workspace, request access with a reason, wait
for the customer to approve it in their Trust Center, work within the time box, and
every single thing they looked at appears in both the customer's log and the internal
chain.
```

### Step 12 — Operations dashboards

```
Build the operations surface in apps/internal for the ENGINEERING and SECURITY roles.
The data endpoints exist (/internal/operations/{pipeline,queue,spend,slo,evaluation,
connectors}); there is no interface, no dashboard, and no alerting anywhere in the
product. Per docs/OPERATIONS.md the system today "is observable and unmonitored, which
are different things."

Read first: api/routers/internal.py operations routes, ops/slo.py, ops/release_gates.py,
pipeline/spend.py, the jobs/queue subsystem, docs/OPERATIONS.md and docs/SLOS.md in
full. The thresholds in OPERATIONS.md are already specified precisely — use those exact
numbers, do not invent new ones.

Build:
1. An operations overview: queue depth and oldest-unprocessed age, pipeline throughput,
   dead-letter count, spend against ceiling, SLO status, connector health. Every metric
   shows its threshold and how close it is.
2. Honest SLO display. Three of five objectives are measurable today; two are not. The
   API deliberately returns met: null with a stated reason for the unmeasurable ones —
   the UI must render "not measurable yet, because X" and must never render null as
   either healthy or breached. This is the whole point of how that endpoint is built.
3. Queue and job inspection: per-tenant fairness, in-flight counts, leases, dead
   letters with their failure reason and correlation id, and a way to search by
   correlation id (per docs/CORRELATION.md this is the thread you pull when a brief
   is wrong).
4. Spend: current period against ceiling, warn at 80% and refuse at 100% as already
   specified, per-stage breakdown, and a clear flag when a backfill is running since
   the runbook says cost spikes are almost always a backfill.
5. Connector health across tenants: the runbooks say the state to never miss is
   connected + failing — authorised but nothing arriving, which looks fine on a naive
   dashboard. Make that state visually loud.
6. Release gates view: PASS / BLOCK / MANUAL per gate. MANUAL blocks a release exactly
   as hard as BLOCK — the UI must not style it as a softer warning.

For every chart in this step, read the dataviz skill before writing the first line of
chart code. Charts must use the design tokens, be readable in both themes, be
accessible (never colour alone to convey state), and degrade to a table on small
screens. No vanity metrics, no gauges that look impressive and say nothing.

Absolute constraint: these dashboards aggregate SYSTEM health. Nothing here may
display, rank, or compare individual people — not customers' employees, not staff.

Done when: an engineer on call could open this and know within thirty seconds whether
the system is healthy, and if not, which of the four documented failure classes it is.
```

### Step 13 — Audit log and compliance surface

```
Build the audit surface in apps/internal, SECURITY role only.

Read first: internal/audit.py in full (compute_hash, the advisory lock, verify()),
db/staff_models.py::InternalAuditEntry, and the migration that grants cairn_app only
SELECT and INSERT on internal_audit_log.

Build:
1. Audit log viewer: filterable by staff member, tenant, action, and date range.
   Every entry shows who, what, which tenant, when, and the written reason. Paginated
   and fast — this table only grows.
2. Chain verification UI: run verify(), and on failure show exactly what the function
   reports — the first broken sequence number and whether it indicates an edited entry
   or a removed/reordered one. Do not summarise a chain failure as "invalid"; a
   security incident deserves the specific finding.
3. An honest statement, in the UI itself, of the current limitation: the chain is
   tamper-EVIDENT, not tamper-PROOF, until a separate append-only sink exists outside
   this database. Your own Step 28 notes warn that the "customer-verifiable audit"
   claim should not be made externally until then. Say it in the product rather than
   letting somebody discover it in a doc.
4. Export for compliance review, itself an audited action.

Design note: an audit log is one of the hardest things to make readable. Invest in the
information hierarchy — scanning a thousand entries for the one that matters is the
actual job this screen does.

Done when: a security reviewer can answer "who looked at this customer's data, when,
and why" in under a minute, and can prove the record has not been altered.
```

### Step 14 — Billing operations shell

```
Build the billing surface in apps/internal for the BILLING and SECURITY roles.

Important honesty constraint: billing is NOT implemented in this product. The
billing.manage permission exists, the subscription endpoint returns plan="unbilled"
and says so, and there are no seat or plan limits anywhere in apps/api. Do not build a
UI that implies a billing system exists. Build the shell that will hold one, and be
explicit about what is not wired.

Read first: api/routers/internal.py subscription and seats endpoints, and the pricing
discussion in md/14-decision-register.md — pricing was deliberately DEFERRED because
per-seat pricing creates a perverse incentive against connecting the whole team, which
the product needs in order to function at all. Do not build per-seat billing UI that
contradicts a decision the team made on purpose.

Build:
1. Workspace subscription view: current plan (honestly "unbilled"), seats in use
   counted from memberships, workspace age, connected sources.
2. A clearly-labelled placeholder for the parts that need a payment provider, listing
   what is missing rather than showing empty widgets.
3. Aggregate view across workspaces: how many exist, how many are active, seats in use
   in total. System-level only — no ranking of customers, no per-person anything.

Done when: a billing operator can see the real state of a customer account, and nobody
reading this screen could mistake CAIRN for having a working billing system.
```

---

## Phase D — Proof

### Step 15 — End-to-end journeys

```
Write real browser-level end-to-end tests for both applications. The Stage D audit
called browser E2E "the highest-value test in the project and it does not exist", and
existing e2e specs cover only fragments.

Build Playwright specs against a real Postgres, real cookies, and real cross-origin
calls — no mocked API layer. Chromium is already available in this environment; do not
try to download browsers.

Journey 1 — a company onboards, end to end:
  founder signs up -> verifies email -> lands in an empty workspace -> invites three
  colleagues with different roles -> each colleague receives the invite (assert against
  a captured mail sink, not a mock) -> one accepts with a password, one accepts with
  Google SSO, one is an existing verified user -> each sees the notification screen and
  acknowledges it -> assert notified_at is set for all three -> owner enforces MFA ->
  each member enrols -> owner changes one role, removes one member, and is refused when
  trying to remove the last owner.

Journey 2 — password recovery: member forgets password, requests reset, completes it,
old sessions are dead, new login works, and a reset request for an unknown address is
indistinguishable from a known one.

Journey 3 — support access, spanning both apps:
  staff logs into apps/internal with MFA -> requests a configuration session with a
  reason -> customer sees it in Trust Center -> customer approves -> staff reads tenant
  detail -> assert the access appears in the customer's log AND the internal chain ->
  customer revokes mid-session -> staff's next read is refused -> assert a content
  request requires its own separate approval -> assert a BILLING-role staff member
  cannot reach content at all.

Journey 4 — the symmetry invariant, tested from the browser: an Owner and a Viewer
both open a colleague's record and the rendered content is identical.

Journey 5 — accessibility: axe over every route in both apps, keyboard-only completion
of the invite-and-accept flow with no mouse events at all.

If a journey cannot pass because a feature is genuinely incomplete, leave the test
FAILING and say so — this repo already keeps a red evaluation gate and a red e2e job on
purpose, on the principle that honestly red beats falsely green. Do not weaken an
assertion to get a green run.

Done when: these five journeys run in CI, and each one either passes or fails for a
reason you can state in one sentence.
```

### Step 16 — Design and accessibility QA pass

```
Do a full design quality pass across both applications, and produce evidence rather
than an assurance.

1. Screenshot every route in apps/web and apps/internal, in light and dark theme, at
   360 / 768 / 1024 / 1440px, in every one of the five required states (loading, empty,
   error, populated, degraded) wherever the state is reachable. Save them to a
   reviewable directory and give me an index page.
2. Automated axe run over every route, both apps, both themes. Zero violations, or a
   written justification per exception.
3. Contrast audit of every token pair actually used in both themes. Report anything
   below 4.5:1 for body text or 3:1 for large text and UI boundaries.
4. Keyboard-only pass over every interactive flow: tab order sensible, focus always
   visible, focus trapped in modals and returned on close, Escape closes overlays, no
   keyboard trap anywhere.
5. Consistency audit across both apps: are the same concepts using the same component,
   spacing, and words everywhere? List every inconsistency you find — differing button
   placement, differing empty-state tone, differing date formats, differing error
   phrasing. Fix them.
6. Copy pass: sentence case everywhere, plain English, no jargon, every error says what
   happened and what to do next, no error blames the user, no dead-end states.
7. Bundle check: apps/web still under the 3 MiB Cloudflare Worker budget. Report the
   number.

Deliver a short report listing what you fixed and what you could not, with the
screenshot index. Do not tell me it looks professional — show me the screens.
```

---

# Part 2 — Gates to run after every step

Paste this as a follow-up message at the end of any step where you want a hard check.

```
Before we call this step done, run these gates and report each one as pass or fail
with evidence. Do not fix anything yet — report first.

SAFETY GATE
1. Boundary check: does anything I just built score, rank, evaluate, compare, or
   allocate a person? Quote the code if unsure.
2. Symmetry check: can any tenant role now see more about an individual than that
   individual sees about themselves? Check every new endpoint and screen.
3. Tenant isolation: does every new customer-data read/write go through an RLS-bound
   session? List them.
4. Call sites: for every function, endpoint, component and client method I added,
   state what calls it in production. Anything with zero production call sites is a
   defect in this codebase's specific history — flag it explicitly.
5. Audit: does every staff action against a tenant write an audited entry with a
   required reason?
6. Secrets: read the full diff for credentials, tokens, keys, or connection strings.

DESIGN GATE
7. Do all new screens implement loading, empty, error, populated and degraded states?
   Name the file for each state.
8. Contrast pass in both themes for every new token pair?
9. Keyboard-only: every new interaction reachable, focus visible, focus trapped and
   returned in modals, Escape closes overlays?
10. Responsive at 360 / 768 / 1024 / 1440?
11. Any numeric confidence, score, percentage, badge, streak or ranking attached to a
    person anywhere in the new UI? There must be none.
12. Bundle size for apps/web — report the number against the 3 MiB budget.

TEST GATE
13. Are failure paths tested, not just happy paths? Name the failure tests.
14. Did I watch each new test fail for the right reason before making it pass?
15. Suite green? Coverage floor met without weakening any threshold?

Then give me a one-paragraph honest summary: what is genuinely done, what is
half-done, and what I should not believe works yet.
```

---

# Part 3 — Notes on things you already have

Things the prompts above deliberately preserve rather than rebuild, because they are already correct and unusually well done:

- **Invitation token security** — 256-bit CSPRNG, hashed at rest, never returned in an API response, 7-day expiry, single use, superseded on re-invite, bound to the invited address, no session issued on redemption, rank-checked against the inviter's role, pre-registration hijack blocked. This is the strongest part of the auth system. Don't touch the properties; only add the UI around them.
- **Email delivery** — real SMTP with STARTTLS, correctly invoked, refuses to boot in a deployed environment on the console backend, covered by a release gate. Genuinely fixed.
- **Support access model** — request/approve separation, DB-level grant preventing the app role from minting its own request, scope never widened at approval, `FOR UPDATE` on the revoke race, response-model tests that fail if a content-shaped field appears on a configuration endpoint. Build the UI, keep the model.
- **Audit chain** — content plus previous-hash SHA-256, advisory-lock serialised, SELECT/INSERT-only grants, verify() naming the exact break. Solid.
- **Permission model** — explicit per-role frozensets rather than a hierarchy, with symmetry invariants enforced by tests. Extend carefully; the tests are load-bearing.

Two things that are missing and are not covered by any step above, because they need decisions from you rather than code:

1. **No infrastructure exists.** No Terraform, no deployed environment, no secrets manager, no log sink, no metrics backend, no alert destination, no on-call. Step 12 builds dashboards over data the API already computes, but nothing is watching anything, and adding a second deployed app in Step 9 makes this gap larger, not smaller.
2. **The core hypothesis is still unvalidated.** No live GitHub App and no live Vertex AI project has ever run — every brief to date came from a scripted stand-in. Your own Stage D audit flags this as the load-bearing open question and notes that eight steps of product surface got built on top of it anyway: "that was not a decision anybody made. It was momentum." Everything in this pack makes the product usable by real people; none of it answers whether the product works. Consider running that validation in parallel rather than after.
