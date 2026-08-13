# Build Steps — Implementation Plan

**Status:** Active
**Purpose:** Small, verifiable steps from empty repo to working product. Each step has a clear "done" condition.

**Governing principle:** every step ends in something that runs and is tested. No step leaves the repo in a broken state, and no step is so large that a problem inside it is hard to locate.

**UI/UX is the top priority** (memory: `cairn-design-principles`). Black and white palette, minimalist, WCAG 2.1 AA. Every screen is checked against all five user roles before it is considered done.

---

## Stage A — Foundation (Steps 1–8)

_Everything expensive to reverse. No user-visible features yet — this is the load-bearing layer._

| #     | Step                                                                                                                                                     | Done when                                                                                                      |
| ----- | -------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| **1** | **Monorepo scaffolding** — workspace layout, TypeScript + Python tooling, linting, formatting, pre-commit hooks, CI skeleton                             | `pnpm install` and `uv sync` succeed; lint and format run clean in CI                                          |
| **2** | **Design system foundation** — black/white token set, typography scale, spacing, WCAG AA contrast verified, base components (button, input, card, badge) | Storybook renders all base components; automated contrast check passes                                         |
| **3** | **Database foundation** — Postgres via Docker, migration tooling, base schema (tenants, users, memberships, roles)                                       | Migrations run up and down cleanly; seed script creates two test tenants                                       |
| **4** | **Tenant isolation** — RLS policies on every table, session context helper, fail-closed behavior                                                         | Cross-tenant access tests **fail correctly**; a query without tenant context raises rather than returning rows |
| **5** | **Background-job tenant wrapper** — job envelope requiring `tenantid`, single wrapper setting context, fail-closed                                       | A job without tenant ID refuses to run; cross-tenant leakage test passes in CI                                 |
| **6** | **`ActivityEvent` schema** — CloudEvents envelope, CAIRN payload, JSON Schema validation, versioned types                                                | Valid events accepted, invalid rejected with useful errors; TS and Python types generated from one source      |
| **7** | **Auth** — signup, login (email + Google + GitHub), sessions, workspace creation, invitations                                                            | A user can sign up, create a workspace, invite a second user who joins the _existing_ tenant                   |
| **8** | **Roles & permissions** — Owner/Admin/Member/Viewer, permission checks, the "admins see settings not people" constraint                                  | Permission matrix tested; an Admin cannot retrieve deeper individual data than the individual sees             |

**Stage A gate:** two tenants exist, are provably isolated, users can authenticate with correct roles, and events validate. No feature work begins before this passes.

---

## Stage B — Ingestion (Steps 9–13)

| #      | Step                                                                                                               | Done when                                                                                                                                      |
| ------ | ------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| **9**  | **API layer** — FastAPI app, OpenAPI generation, TypeScript client codegen wired into CI                           | Frontend imports a generated typed client; a breaking backend change fails the frontend build                                                  |
| **10** | **Queue infrastructure** — Pub/Sub (emulated locally), worker harness, DLQ, retry with backoff                     | A failing job retries then lands in DLQ; queue depth is observable                                                                             |
| **11** | **GitHub App + webhooks** — app registration, signature verification, verify→enqueue→ack, idempotent consumption   | Real webhook delivered, verified, enqueued, acknowledged under 10s; duplicate delivery upserts rather than duplicating                         |
| **12** | **Attribution correctness** — co-author parsing, bot registry and filtering, identity resolution                   | Squash merge with co-authors credits everyone; Dependabot excluded from human attribution; one person's three identities resolve to one record |
| **13** | **Backfill** — GraphQL bulk pull, 90-day window, **lower priority than live events**, global concurrency scheduler | 90 days imported without breaching secondary rate limits; live events continue processing during backfill                                      |

**Stage B gate:** real GitHub activity flows into the database as validated, correctly-attributed `ActivityEvent` records.

---

## Stage C — Understanding (Steps 14–18)

| #      | Step                                                                                                                                  | Done when                                                                                                    |
| ------ | ------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| **14** | **Evaluation harness first** — golden dataset structure, runner, metrics, CI integration                                              | Harness runs against a seed dataset and reports groundedness and attribution accuracy                        |
| **15** | **Stage 1–2: classify + extract** — cheap-model classification, schema-constrained extraction, provenance and certainty on every fact | Events classify correctly; extracted facts validate against schema and carry source references               |
| **16** | **Stage 3: resolve** — deterministic identity resolution, cross-source dedup, temporal validity and supersession                      | A decision appearing in two sources resolves to one fact; a superseded fact is marked, not deleted           |
| **17** | **Temporal graph + retrieval** — pgvector entry points, graph traversal, temporal filtering                                           | A multi-hop question retrieves the correct chain; superseded facts are excluded                              |
| **18** | **Stage 4: synthesize** — premium-model narrative, mandatory citation, span verification, hedged language by certainty tier           | Brief generated with every claim cited; unsupported claims suppressed; meeting-derived claims read as hedged |

**Stage C gate:** a genuinely useful Founder Brief generated from the team's own real GitHub activity.

---

## Stage D — Product surfaces (Steps 19–26)

| #      | Step                                                                                             | Done when                                                                          |
| ------ | ------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------- |
| **19** | **App shell** — Next.js on Workers/OpenNext, layout, navigation, workspace switcher              | Deploys to Cloudflare; authenticated routing works; passes axe accessibility audit |
| **20** | **Onboarding flow** — signup → connect GitHub → progressive backfill rendering → first summary   | Under 10 minutes signup to first real output; **never shows an empty state**       |
| **21** | **Founder Brief view** — daily narrative, provenance links, certainty tiers, archive             | Every claim links to its source in one click                                       |
| **22** | **My Week + correction** — personal record, one-tap correction, correction feeds evaluation data | A correction supersedes the fact and appears in the golden dataset                 |
| **23** | **Worker notification flow** — invitation framing, own-record-first landing, inline opt-out      | A new team member's first screen is their own record; opt-out works per source     |
| **24** | **Team Feed** — searchable, filterable stream                                                    | Filter by person, project, source, date; search returns grounded results           |
| **25** | **Tenant admin** — members, roles, integrations, privacy settings, Trust & Privacy Center        | An Owner can manage the workspace without contacting support                       |
| **26** | **Role-specific views** — developer, designer, PM, non-technical first screens                   | Each of the five roles has a view that makes sense without explanation             |

**Stage D gate:** a real team can be onboarded end-to-end and use the product daily.

---

## Stage E — Operations (Steps 27–30)

| #      | Step                                                                                               | Done when                                                                                 |
| ------ | -------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------- |
| **27** | **Internal back-office** — tenant list, health, subscription inspector, **audit log from day one** | Every internal write is logged, tamper-evident                                            |
| **28** | **Support access model** — consent-gated, time-boxed, customer-visible sessions                    | A support session requires approval, expires, and appears in the customer's own audit log |
| **29** | **Observability** — OpenTelemetry across pipeline stages, cost attribution, evaluation dashboard   | Any bad output is traceable to the stage, context, model, and cost that produced it       |
| **30** | **Backpressure + fair scheduling** — queue-depth autoscaling, per-tenant partitioning, rate limits | One heavy tenant cannot starve others; backfill never delays live processing              |

---

## Sequencing rules

1. **Never skip a gate.** Gates exist because the cost of discovering a problem later is disproportionate.
2. **Tests ship with the step**, not after. Steps 4, 5, and 12 are meaningless without their tests.
3. **Evaluation before AI features** (step 14 before 15) — otherwise quality drifts invisibly.
4. **Accessibility per step**, not at the end. Every UI step includes its own audit.
5. **Design review per UI step** against all five roles.

---

## Current position

**✅ Step 1 — Monorepo scaffolding. Complete.** (commit `b155522`)

Delivered: pnpm workspaces with catalogs, Turborepo, uv workspace, Ruff + mypy strict, ESLint strict-type-checked with jsx-a11y as errors, Prettier, commitlint, lefthook git hooks, GitHub Actions CI with a single required status, and shared domain vocabulary mirrored across TypeScript and Python with a drift test.

Verified: `pnpm check` clean, 6 TS tests and 11 Python tests passing, all five pre-commit hooks passing, and the secret scanner proven to catch a planted key.

Three fixes made during the step, each because a hook caught a real problem:

- Root ESLint config was missing, so the pre-commit hook could not lint staged files. Resolved by exporting a root-ready config from `@cairn/config` rather than duplicating dependencies at the root.
- `vitest.config.ts` sat outside every tsconfig project, so type-aware linting failed on it. Config files are now included in each package's project.
- The secret scanner matched its own pattern definitions, blocking every commit that touched it. Moved into `scripts/check-secrets.sh` with patterns assembled from fragments so it cannot self-match, and with the script excluded from its own scan.

**→ Step 2: Design system foundation.** Black/white token set, typography scale, spacing, WCAG AA contrast verification, base components.
