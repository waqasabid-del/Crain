# Audit — Stage D (Steps 19–26)

**Date:** 15 August 2026
**Scope:** Steps 19–26 — app shell, onboarding, brief, My Week, worker notification, feed, tenant admin, role views.
**Method:** code review of the Stage D surface, static checks, the full test suite, and a live run of the product against a seeded database.
**Verdict:** the product is sound. **Nobody outside this repository could run it**, which is a different and more urgent problem than any defect in it.

---

## 1. Executive summary

Stage D built what it said it built. The screens work, the API is coherent, tenant isolation holds, and three commitments that were policy sentences at the start of the stage are now enforced code with tests behind them.

The audit found **four defects that made the product unusable outside the test suite** and **three correctness bugs**. All seven are fixed.

Two findings are not code defects and matter more than the ones that are. There is **no email delivery**, so a second team member cannot be invited without database access — the difference between "a team can be onboarded" and "a team can be onboarded by the person who bought it". And **two stage gates were never passed**: the product has never seen a real GitHub repository or a real model, which is the question the roadmap says everything else depends on.

| Severity      | Found | Fixed | Open |
| ------------- | ----- | ----- | ---- |
| P1 — blocking | 6     | 5     | 1    |
| P2 — quality  | 6     | 5     | 1    |
| P3 — hygiene  | 4     | 3     | 1    |

---

## 2. P1 — blocking

### P1-1 Seeded accounts could not sign in ✅ fixed

`db/seed.py` created accounts on `@acme.test`. `EmailStr` rejects `.test` as a special-use name, so the login endpoint refused every seeded account. The accounts existed and were unusable.

This is the direct answer to "I still cannot see the updated frontend": the only accounts in the database could not be signed in to, and the only alternative was signing up fresh — which produces an empty workspace, so every screen correctly showed its empty state.

**Fix:** addresses moved to `example.com`, which validates. Passwords added — the seed previously created no credentials at all, so even a valid address had nothing to authenticate with.

### P1-2 No runnable path on Windows ✅ fixed

Every documented command went through `make`. `make` is not installed on this machine and is not standard on Windows, so `make db-up`, `make migrate`, `make seed` and `make serve` were all unavailable. The README's setup section could not be followed to completion.

**Fix:** portable `pnpm` scripts — `db:up`, `migrate`, `seed`, `setup`, `dev:api`, `dev:web` — and a README section that names the two commands to run and the account to sign in with. The `make` targets remain and are equivalent.

### P1-3 A local environment produced an empty product ✅ fixed

Without `CAIRN_GCP_PROJECT_ID`, `build_providers()` returns a model that answers `{}`. That refusal is correct — md/09 §8 requires the visible failure to be incompleteness rather than confident wrongness — but its consequence was that a developer with no GCP project saw a product that extracted nothing and wrote empty briefs, with no supported way to see it work.

`jobs.py` already named the fix and deferred it: _"The follow-up is a `CAIRN_MODEL_BACKEND` setting, noted in the report rather than smuggled in."_

**Fix:** the setting now exists. `auto` (default, unchanged behaviour), `vertex`, `offline`, and `scripted` — the deterministic provider the evaluation harness grades against. `config.py` refuses `scripted` in any environment that can hold customer data, so the local convenience cannot become a customer-facing lie.

### P1-4 The seed produced no activity ✅ fixed

The seed created tenants, users and memberships, and nothing else — no integration, no evidence, no facts. Every content screen was empty by construction.

**Fix:** the seed now writes GitHub deliveries and runs the **production understanding handler** over them, so facts, embeddings and graph edges come from the code that runs in production rather than from hand-written rows. It adds five attributed facts through the real storage and identity-resolution path so the screens about a person have a person in them. Verified live: 9 facts, 3 people, 2 projects, working search and filters.

### P1-5 There is no email delivery ✅ fixed

Three `TODO(step-20)` markers remain, and nothing in the codebase sends mail. Consequences:

- **An invitation cannot reach the person invited.** The token is written to the database and returned to nobody. An Owner inviting a colleague must read it out of PostgreSQL.
- **Email verification cannot be completed** by the person who signed up.

This makes one claim in the Stage D gate wrong, and it is worth stating plainly rather than leaving in a build log: **a team cannot be onboarded end to end today**. One person can sign up and use the product alone. Adding the second person requires database access.

**Fix:** a `cairn_api.email` package — `Message`, an `EmailSender` protocol, `ConsoleSender` for local development and `SmtpSender` over the standard library (no new dependency). Signup, resend-verification and invitations all send. A deployed environment refuses to start on the console backend, so invitations cannot silently go nowhere. Sends are best-effort at the boundary: an SMTP outage cannot roll back a signup. 17 tests.

**Still open within it:** no outbox and no retry, so a failed send loses the link until someone resends, and there is no operator-facing resend for an invitation — only revoke and re-invite. That is the next increment, not a defect in this one.

### P1-6 Two stage gates were never passed ⚠️ open — process

The build log records exactly two gate results: **Stage A — PASSED**, and **Stage D — PASSED**. There is no Stage B result and no Stage C result. Both stages were built through and left behind.

That matters because of what those gates say:

- **Stage B:** _real GitHub activity flows into the database as validated, correctly-attributed records._ No live GitHub App has ever been installed. Every event the pipeline has processed was constructed by a test or a seed.
- **Stage C:** _a genuinely useful Founder Brief generated from the team's own real GitHub activity._ No Vertex project has ever run. Every brief has been written by a scripted provider answering from a rule table.

md/13 §6 frames the whole plan as evidence-gathering and puts this first: _"Can we produce a genuinely useful brief from real activity? **If Phase 1's question fails, nothing downstream matters.**"_ The roadmap explicitly makes the second wave "gated rather than parallel" for that reason.

Eight steps of product surface were then built on top of that unanswered question. Nothing built is wasted — the screens, the admin, the consent model and the feed are all needed whatever the answer — but the sequencing discipline the plan set for itself was not followed, and it was not a decision anybody made. It was momentum.

**Recommendation:** answer Stage B and Stage C before Stage E. Concretely: install the GitHub App on one real repository, point a Vertex project at it, and read the resulting brief. That is a day of work and it is the only evidence that matters. If the brief is not useful, the next thing to build is not the back-office.

---

## 3. P2 — correctness and product risk

### P2-1 Search reported truncation on a complete result set ✅ fixed

`truncated=len(hits) == limit` claimed the search had stopped short whenever the corpus held exactly `limit` matches. A reader shown "these are the strongest matches, not all of them" narrows a search that had already returned everything.

**Fix:** request one more than asked for and report from the surplus, the same technique the paginated list uses. Two regression tests: a full page that is complete, and a page that genuinely stopped short.

### P2-2 Date filters ignored the reader's timezone ✅ fixed

The feed built `since`/`until` as `${date}T00:00:00Z`, treating a calendar date chosen in local time as a UTC instant. In UTC+13 a reader filtering "today" received a window that started mid-morning: their own morning's work missing, the previous evening's included, and nothing on screen to explain either.

**Fix:** both ends resolved against local time. The test that encoded the old behaviour was rewritten to assert the intent rather than one zone's answer.

### P2-3 A UUID typed as `object` ✅ fixed

`trust._connected_sources(db, tenant_id: object)` — a placeholder that passed mypy and documented nothing.

### P2-4 The brief's rate limit will be hit by normal use ✅ fixed

A finished period is stored; the **current** period is regenerated on every request and limited to 12 per hour per workspace. Five people opening the brief twice each in a morning exhaust it, and the eleventh reader gets a 429 on the product's main screen.

**Fix:** a five-minute per-workspace cache for the current period, held in process rather than in a table — deliberately, so current-period prose has no second persisted home that could be mistaken for the archive. Cached reads do not consume rate-limit budget, and the window is arithmetic rather than taste: one generation per five minutes is exactly the 12/hour limit, so reading alone can no longer exhaust it however many people read. A correction drops the cached brief immediately, because every correction closes a fact's validity window and the cache keys on that. 9 tests.

### P2-5 Semantic search never runs locally ⚠️ open

`semantic` is gated on `providers.live`, which is false for the scripted backend. That is right — hashed vectors are noise — but it means the vector half of search is exercised only by unit tests and never by anyone using the product locally.

**Recommendation:** accept for now; revisit when a Vertex project exists. Documented so it is not rediscovered as a bug.

### P2-6 Sample content mode has no people ✅ fixed

`sampleSource.getFacets` returned an empty `people` list, so in `CONTENT_SOURCE=sample` the person filter silently never appeared.

**Fix:** the people facet is derived from the mentions on the sample facts, the same way projects and sources already were.

---

## 4. P3 — hygiene

### P3-1 Comment density is roughly triple a professional norm ✅ fixed — and the measurement was wrong

Measured across 138 non-test source files: **median 41%**, with 130 files over a 15% budget. Industry practice is 10–15%.

The cost is not aesthetic. At that volume, the reasoning that genuinely matters — a security invariant, a decision whose obvious alternative is wrong — is indistinguishable from reasoning that does not, so reviewers skim all of it, and comments drift out of date because nobody reads them closely enough to notice.

**Done:** a budget in md/17 §8.1 and a sweep across the backend and shared packages. True median is now **14%**, with 15 of 186 files over budget and none above 25%. Roughly 1,900 lines of prose removed.

**The first measurement tool was broken, and it matters more than the ratio.** `scripts/comment-ratio.mjs` matched triple quotes line by line, so a module-level constant like `SAMPLE = """\` desynchronised it: the string's _closing_ delimiter was read as an opener and the rest of the file counted as prose. `pipeline/live_check.py` reported 70% and is actually 13%. A second defect made the declaration-file budget dead code — it was defined and never called.

Two consequences worth recording, because both are the failure mode a metric is supposed to prevent:

- Work was done to satisfy a number rather than a reader. One file had a docstring added specifically to close the phantom fence.
- Numbers from it were reported as fact, by me, before anyone checked the tool.

It has been replaced with `scripts/comment_ratio.py`, which measures Python with `tokenize` — so a docstring counts as documentation and a string bound to a name counts as data, which is the distinction the old tool could not make. Files under 60 lines are measured but never failed: below that, a module docstring alone exceeds any percentage.

**One judgement to revisit:** `pipeline/synthesize.py` came back at 5%, which is under-commented relative to its neighbours for a file that decides what a customer is told. Worth a reviewer restoring some of it.

### P3-2 One timing-sensitive web test ✅ fixed

`feed.test.tsx › groups what happened by the kind of thing it is` failed twice under full-suite load, at ~1.4 s against Testing Library's 1 s default, and passed in isolation both times. A slow-render flake rather than a logic fault, and it would have recurred in CI as a missing-element error that says nothing about slowness.

**Fix:** `asyncUtilTimeout` raised to 5 s for the suite. The screens here render a provider tree and several async reads; 1 s was never the right budget for them.

### P3-3 Embeddings do not distinguish documents from queries ⚠️ open — new

Found during the comment sweep. `VertexEmbeddingProvider._embed_batch` never sets Vertex's `task_type`, so a stored fact and a search query are embedded identically when `RETRIEVAL_DOCUMENT` and `RETRIEVAL_QUERY` are the documented settings for each. The effect is silently degraded retrieval — nothing fails, results are simply worse — and it will only be visible once a real model runs, which makes it a Stage C item.

A comment above the code described exactly this asymmetry while the code did not implement it, which is the specific hazard the comment budget exists to reduce.

### P3-4 GitHub installation id readable by every member ✅ accepted

`GET /integrations` returns the installation id to any member, because the disconnect route needs it. It is not a credential — it appears in the app's own install URL — and disconnecting still requires permission. Recorded as a considered decision rather than an oversight.

---

## 5. What the audit confirmed

Verified by reading the code and by running the product:

- **Tenant isolation holds** across every Stage D surface. Cross-workspace reads return 404 with a positive control proving the data is visible to its owner.
- **The symmetry commitment is enforced, not asserted.** Two work roles fetching the same list receive byte-identical responses; the members list carries no activity column; the notification screen names who has been notified and counts who has opted out.
- **Provenance is unbroken.** Every fact reaching a screen carries at least one source, and search returns stored statements rather than generated prose — asserted by tests on the response shape, not only its content.
- **Three commitments became code during Stage D**: corrections supersede facts and reach the evaluation dataset; opt-out is retroactive and blocks attribution where it is made; worker notification gates attribution rather than describing an intention. Each was a comment describing behaviour that did not exist at the start of the stage.

---

## 6. SDLC status

| Phase           | Status | Assessment                                                                                                                                                           |
| --------------- | ------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Planning**    | ✅     | 18 specification documents, locked decisions, a sequenced roadmap with exit criteria per step.                                                                       |
| **Design**      | ✅     | Data model, permission model and UX principles decided before implementation and enforced by tests.                                                                  |
| **Coding**      | ✅     | Every layer has a production caller. 26 of 30 steps complete. The unreachable-code finding from the earlier audit stays closed.                                      |
| **Testing**     | ✅     | 845 Python + 160 web tests. Integration-first: tenant isolation, migration round-trips, WCAG audits, schema drift, Worker build. **No browser-level E2E** — the gap. |
| **Deployment**  | ⚠️     | Container and CI build only. No IaC, no environments, nothing deployed. Unchanged since the last assessment.                                                         |
| **Maintenance** | ⚠️     | Structured logs, spend accounting, an operations doc. No metrics, no alerting, no dashboards, no on-call path.                                                       |

The two ⚠️ rows are Stage E, which is exactly where the roadmap puts them. They are not surprises; they are the next four steps.

**Where a browser-level E2E belongs:** the four P1 defects above would all have been caught by one Playwright test that seeds, signs in, and asserts the brief renders. Every one of them lived in the gap between "the API works" and "a person can use it", and that gap is precisely what the unit and integration suites cannot see. This is the highest-value test in the project and it does not exist.

---

## 7. Is this the product that was specified?

Checked against md/00 §2, which states the promise as: _what your team actually did, with the evidence attached, written up without anybody filling in a status report._

| Promise                                    | Built | Note                                                                                               |
| ------------------------------------------ | ----- | -------------------------------------------------------------------------------------------------- |
| Activity captured without manual reporting | ✅    | GitHub webhook → understanding → facts, end to end, with a production caller at every layer.       |
| Understanding rather than aggregation      | ✅    | Classification, extraction, resolution, a temporal graph, retrieval and synthesis — all real.      |
| Every claim links to its source            | ✅    | Enforced structurally: a fact cannot exist without provenance.                                     |
| Written up in plain language               | ⚠️    | The synthesis path is complete and ungraded against a real model — no Vertex project has ever run. |
| Not surveillance                           | ✅    | Symmetry, no scoring, retroactive opt-out, notification gating attribution. The strongest area.    |
| Corrections that improve the system        | ✅    | Correction → supersession → golden dataset, closed loop.                                           |
| A team can adopt it                        | ⚠️    | Blocked on P1-5. One person can; a team cannot, until invitations can be delivered.                |

**The honest summary.** What was specified is what was built, with two qualifications that matter and should not be smoothed over:

1. **The AI has never met a real model.** Every pipeline stage is implemented, tested and graded against a scripted provider. Quality against Gemini is unknown — not poor, unknown. Until a Vertex project runs the evaluation harness, "writes a genuinely useful brief" is an untested claim, and it is the central claim of the product.
2. **It has never been deployed or used by anybody.** Two ⚠️ rows above are the same fact seen twice.

Neither is a wrong turn. Both are exactly where a 26-of-30-step project should be — but "we have not tested the core claim yet" is a different statement from "the core claim works", and this project has been careful enough elsewhere that the distinction should be kept.

---

## 8. Recommended order

1. **Email delivery** (P1-5) — half a day. Nothing involving a second person works without it.
2. **One Playwright E2E** — seed, sign in, read the brief, correct a fact. Half a day, and it closes the class of defect this audit found.
3. **A Vertex project and one evaluation run** — the only way to learn whether the product's central claim holds.
4. **Brief caching** (P2-4) — before anybody demonstrates it to a room.
5. **The comment pass** (P3-1) — a day, in one sweep.
6. **Stage E as planned** — back-office, deployment, monitoring, launch checklist.
