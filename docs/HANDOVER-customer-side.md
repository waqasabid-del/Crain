# Handover: product gaps found by the AI/infrastructure track

> **Coordination rule, effective 2026-08-19.** The AI track is backend-only
> from here; everything under `apps/web` and `packages/ui` is yours. Two things
> before you start: **rebase on main once PR #2 merges** - the People page,
> My Week, the Trust Center copy and the `/verify` screen all changed underneath
> you while you were away - and **read this document first**: it lists exactly
> where the AI track touched your territory, including the People page's
> vocabulary-guard test, which rejects ranking words even in negation ("no
> scores" fails it) and will bite your copy the way it bit ours (item 6).

2026-08-19. Facts and evidence pointers, not instructions — the customer-side
pack has the instructions. Each item was _found_ by this track's live proofs,
which is why the evidence is a test, a log line, or a session artefact rather
than an opinion.

## 1. No invite form exists in the web app

Nothing in `apps/web` renders a control that sends an invitation.
`POST /v1/workspaces/{id}/invitations` works, sends real mail, and the link
resolves — but only the API can originate one.

- **Evidence:** `apps/web/e2e/email.e2e.ts`, the invitation journey — it sends
  the invite over raw HTTP with an in-test comment stating why: "there is no
  invite form in the web app yet, so the browser cannot originate this one."
  Found when the mail journey tried to click a button that does not exist
  (`getByRole("button", { name: /invite/i })` timed out on `/settings`).

## 2. The notification gate stamps only through `/welcome`

`Membership.notified_at` is written in exactly one place: the GET handler in
`apps/api/src/cairn_api/api/routers/me.py` (~line 407), whose docstring calls
the write "the receipt for the read". A member who signs in and never lands on
that screen is never recorded as notified, and `trust.py` counts them
(`Membership.notified_at.is_(None)`) indefinitely.

- **Evidence:** the three `notified_at` call sites — `me.py` writes, `admin.py`
  and `trust.py` only read. The seed deliberately ships `sam@freelance` as
  "both workspaces, not yet notified" (`db/seed.py`), which is the state that
  never resolves without the `/welcome` visit.

## 3. The record-correction e2e asserts on seed ordering

`apps/web/e2e/record-correction.e2e.ts` opens the brief and asserts a citation
_link_ on whichever claim happens to be first. URL-less citations deliberately
render unlinked ("no link available for this source" —
`apps/web/src/components/ClaimList.tsx`, `Citation`), so the test passes or
fails on which fact the brief leads with — it went red against a database
carrying live GitHub and meeting facts on top of the seed, for no product
reason.

- **Evidence:** the 18/19 e2e scorecard (harness session): every failure but
  this one was harness or product and got fixed; this one is data-dependence.
  Trace retained under `apps/web/test-results/record-correction*`.

## 4. The brief screen should render the sectioned shape the API now feeds it

Synthesis now writes to the three-tier structure of md/05 A.2.2 — verified /
observed / suggested, budgeted so every tier with facts is covered — and every
claim carries its certainty. The screen (`apps/web/src/routes/BriefPage.tsx` +
`ClaimList`) still renders one undifferentiated list with a per-claim badge:
the tiers exist as metadata, not as the Shipped / In motion / Worth a look
sections the design describes.

- **Evidence:** `pipeline/synthesize.py` (the sectioned instruction and
  `claim_target`), and a live three-source generation where suggested-tier
  meeting claims ("It sounded like the staging deploy is blocked…") sit
  interleaved with verified GitHub claims in one flat list.

## 5. Already fixed, for review rather than action: `/verify`

Every verification email ever sent linked to `{app}/verify?token=…` and no
such route existed — 404 in every inbox, invisible to both test suites because
each side passed alone. This track built the page
(`apps/web/src/app/verify/page.tsx`, `routes/VerifyPage.tsx`) to unblock the
mail proof; the copy and design were written by this track and deserve a
customer-side pass. Evidence: `apps/web/src/routes/verify.test.tsx`, whose
module docstring carries the full account.

## 6. Team page and person record now carry two new surfaces (2026-08-19)

The AI track shipped the related-work finder (Team page, below the members
list) and self-declared capacity (chip on the members table; control on the
person's own record; explained in the Trust Center's "What CAIRN reads"). If
your pack's steps touch `PeoplePage.tsx`, `MyWeekPage.tsx` or `TrustPage.tsx`,
these landed first - the page's own no-ranking-vocabulary guard test rejected
even a negated "no scores" in the finder's copy, which is worth knowing before
editing wording there. Evidence: `people.test.tsx` (the finder suite),
`test_related_work.py` (symmetry, opt-out inheritance, never-computed).
