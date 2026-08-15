# Engineering Standards — How We Build

**Status:** v2 — critiqued and revised. §12 records what was wrong with v1 and why it changed.
**Purpose:** How CAIRN is built, so that quality is a property of the process rather than of any individual's discipline on a given day.

**Who this is for:** the current team of one, and every engineer who joins later. Written so that the standard survives growth without being rewritten.

---

## 1. Git workflow — trunk-based development

**Trunk-based development is the standard for high-performing engineering teams.** Developers commit small changes to `main` frequently, through short-lived branches.

| Rule                            | Detail                                                                                 |
| ------------------------------- | -------------------------------------------------------------------------------------- |
| **Branch lifetime**             | **Maximum 2 days.** A branch older than that is a signal the work was scoped too large |
| **Branch naming**               | `type/short-description` — e.g. `feat/tenant-isolation`, `fix/webhook-dedup`           |
| **Merge to `main`**             | Via pull request only. No direct pushes, including by the repo owner                   |
| **`main` is always deployable** | If `main` is broken, fixing it takes priority over all other work                      |

**Why not GitFlow:** long-lived branches produce large merges, painful conflicts, and slow feedback. Trunk-based reduces merge conflicts, forces smaller changes, and enables genuine continuous integration.

### 1.1 Adopted progressively, not declared

Trunk-based development **depends on reliable CI**. Committing to `main` several times a day without a trustworthy test suite is not discipline — it is recklessness with extra steps.

Until the Stage A gate (file 16) is passed and CI is genuinely reliable, branches may live slightly longer and merges are more deliberate. **The practice is earned by the pipeline, not asserted by the document.**

---

## 2. Commit standards — Conventional Commits

Every commit follows `type(scope): description`.

| Type       | Use                              |
| ---------- | -------------------------------- |
| `feat`     | New capability                   |
| `fix`      | Bug fix                          |
| `refactor` | Behaviour-preserving restructure |
| `test`     | Test additions or changes        |
| `docs`     | Documentation                    |
| `chore`    | Tooling, dependencies, config    |
| `perf`     | Performance improvement          |

**Example:** `feat(ingestion): add co-author parsing for squash merges`

**Why it matters:** enables automated changelogs, makes history searchable, and forces a moment of thought about what a change actually is. Enforced by commit-lint in CI, not by memory.

---

## 3. Pull requests

| Standard              | Rule                                                                                                      |
| --------------------- | --------------------------------------------------------------------------------------------------------- |
| **Size**              | Target under 400 lines changed. Large PRs receive shallow reviews — this is well documented and universal |
| **Description**       | What changed, why, how it was tested, and what to watch after deploy                                      |
| **Linked spec**       | Reference the relevant `md/` file section, so the reasoning is one click away                             |
| **Self-review first** | Read your own diff before requesting review. Catches most trivial issues                                  |
| **CI green**          | Review does not begin until CI passes                                                                     |

### 3.1 Review standards

Reviews check, in priority order: **correctness → security → tenant isolation → tests → readability → performance.**

Tenant isolation sits third deliberately — it is CAIRN's sharpest risk (file 06 §4.3), and a reviewer who does not actively look for it will not notice its absence.

**Reviewers block on:** missing tests for new logic, any cross-tenant risk, unhandled errors, hardcoded secrets, and accessibility regressions in UI code.

### 3.2 Reviewing while the team is one person

A PR you approve yourself is theatre, and pretending otherwise builds a habit of going through motions instead of thinking. So the honest standard while solo:

- **PRs are still used** — they run CI, create reviewable history, and build the habit for when the team grows.
- **Self-review is done against the §3.1 checklist in writing**, in the PR description, and labelled as self-review rather than approval.
- **Some work requires a second pair of eyes regardless**: authentication, tenant isolation, and anything touching customer data. For these, the PR states that outside review is needed and is not merged until someone reviews it — including an AI reviewer with the spec files in context, which is materially better than nothing.

This is a temporary accommodation, not a permanent standard. It ends when the second engineer joins.

---

## 4. Testing strategy

The pyramid still holds, with concrete targets:

| Layer           | Target     | Purpose                                                |
| --------------- | ---------- | ------------------------------------------------------ |
| **Unit**        | ~500 by v1 | Fast, isolated logic. The base of the pyramid          |
| **Integration** | ~100       | Database, queue, and external API boundaries           |
| **End-to-end**  | ~20        | Only the journeys that would be catastrophic if broken |

### 4.1 Coverage is a floor, never a target

**80% on business logic** — excluding generated code, config, and trivial accessors.

But coverage measures _lines executed_, not _correctness_. Chasing the number produces tests asserting that getters return values. The real standard:

> **Every branch of business logic and every failure path has a test that would genuinely fail if the behaviour broke.**

A PR at 85% coverage with no test for the error path **fails review**. A PR at 75% with thorough behavioural tests **passes**. The number is a smoke alarm, not a goal.

### 4.2 The E2E discipline

**50–100 E2E tests is the practical ceiling** before maintenance burden outweighs value. Teams that over-invest at the top get long feedback loops and flaky suites that get ignored.

**Timing matters as much as count:** E2E tests are written **after a screen's design has stabilised**, not alongside first implementation. Tests written against a UI that changes daily are the most expensive tests to maintain and the first to become flaky. The ~20 target applies at v1 launch, not throughout the build.

CAIRN's E2E set covers only: signup → workspace → GitHub connect → first brief; worker notification → own record → correction; and admin member management.

### 4.3 Non-negotiable tests

Three areas where a bug is silent rather than loud, and therefore must be tested explicitly:

1. **Cross-tenant isolation** — tests that _attempt_ cross-tenant access and must fail.
2. **Background-job tenant context** — a job without tenant ID must refuse to run.
3. **Attribution correctness** — co-authors credited, bots excluded, identities resolved.

---

## 5. Definition of Done

Split deliberately into **blocking** and **expected**. A fifteen-item checklist gets skipped under deadline pressure, and a partially-followed standard is worse than a short one that is actually followed — it teaches that the list is optional.

### 5.1 Blocking — cannot be waived by anyone

- [ ] Tests written for new logic, covering failure paths (§4.1)
- [ ] CI green
- [ ] No secrets in code; no new security warnings
- [ ] **Tenant isolation verified** for anything touching data
- [ ] **AI boundary check** — the feature cannot score, rank, or allocate (file 05 §B.3.3)

These five are non-negotiable because each protects against a failure that is either silent, legally consequential, or unrecoverable.

### 5.2 Expected — deferrable only with a tracked follow-up

- [ ] Lint and format clean
- [ ] Integration tests for boundary-crossing code
- [ ] Reviewed (per §3.2 while solo)
- [ ] Documentation updated where behaviour changed
- [ ] Accessibility audit passes (UI work)
- [ ] Observability — logs and traces on new paths
- [ ] Spec file updated if implementation revealed the spec was wrong

**Deferral requires an issue with a date.** Silent deferral is how standards decay.

### 5.3 Additional criteria for AI features

Shipping AI functionality means **"done" must cover the safety, reliability, and operational readiness of AI behaviour** — not only code and tests:

- [ ] Evaluation harness cases added (file 10) — _blocking_
- [ ] Grounding verified — claims carry provenance — _blocking_
- [ ] Cost per operation measured and tagged — _expected_
- [ ] Failure behaviour tested — insufficient or contradictory data — _blocking_

---

## 6. Repository structure

```
cairn/
├── apps/
│   ├── web/              # Next.js frontend (Cloudflare Workers)
│   └── api/              # FastAPI backend
├── packages/
│   ├── ui/               # Design system — tokens, components
│   ├── types/            # Generated OpenAPI TypeScript types
│   └── config/           # Shared lint, tsconfig, prettier
├── services/             # See §6.2 — separate from apps/api by design
│   ├── ingestion/        # Webhook receivers and normalizers
│   └── pipeline/         # Understanding layer stages
├── infra/                # Terraform
├── md/                   # Specifications
└── .github/workflows/    # CI
```

### 6.2 Why `services/` is separate from `apps/api/`

A reasonable engineer will ask why ingestion and pipeline are not simply modules inside the API application. They are separate because **they scale independently and have opposite concurrency profiles** (file 06 §3.2): API services are user-facing, low-CPU, and take high concurrency; pipeline workers are LLM-bound, memory-heavy, and need low concurrency.

Deploying them together would force one scaling policy onto two very different workloads — meaning either the API scales wastefully or the workers starve. The separation exists to keep those policies independent.

### 6.3 Tooling

| Concern            | Choice                                        | Rationale                                                       |
| ------------------ | --------------------------------------------- | --------------------------------------------------------------- |
| JS package manager | **pnpm workspaces** with catalogs             | The 2026 default for this team size                             |
| Task orchestration | **Turborepo**                                 | Caching and affected-project detection                          |
| Python             | **uv workspaces**                             | Fast, and the emerging standard for Python monorepos            |
| Versioning         | **changesets**                                | Standard for coordinated releases                               |
| JS lint/format     | ESLint + Prettier                             | Conventional                                                    |
| Python lint/format | **Ruff**                                      | Replaces flake8, isort, and more, in one fast tool              |
| Type checking      | TypeScript strict; **mypy strict** for Python | Strict from day one — relaxing later is easy, tightening is not |

**Note on Nx:** Nx has stronger polyglot support and would handle the TypeScript + Python split more natively than Turborepo. Turborepo is chosen for lower complexity at current team size, with Nx as a documented escalation path if cross-language task orchestration becomes painful.

---

## 7. CI/CD

**CI runs on every commit.** Fast feedback is the point.

| Stage                      | Runs on            | Target time |
| -------------------------- | ------------------ | ----------- |
| Lint + format + type check | Every push         | < 2 min     |
| Unit tests                 | Every push         | < 3 min     |
| Integration tests          | Every PR           | < 8 min     |
| E2E                        | Every PR to `main` | < 15 min    |
| Deploy to staging          | Merge to `main`    | Automatic   |
| Deploy to production       | Manual promotion   | Gated       |

### 7.1 Speed is a feature

**Build and test times must be optimized, with caching wherever possible.** Turborepo's affected-project detection means a frontend-only change does not run the Python test suite.

**Hard rule: if CI exceeds 10 minutes for a typical PR, fixing it becomes the priority.** Slow CI causes engineers to batch changes, which defeats trunk-based development entirely.

---

## 8. Code quality principles

1. **Explicit over clever.** Code is read far more than written.
2. **Fail loudly.** Silent failures are the enemy — especially in tenant isolation and background jobs.
3. **Types are documentation.** Strict typing on both sides.
4. **No secrets in code, ever.** Secret Manager only; scanning in CI.
5. **Errors carry context.** An error that does not say which tenant, which event, and which stage is a wasted hour.
6. **Delete freely.** Dead code is a liability; version control remembers.

### 8.1 Comment budget

Comments explain **why**, and only where the reason is not recoverable from the
code. Restating what a line does, arguing a decision at length, or describing a
rejected alternative in full belongs in a commit message or in `md/`, not beside
the code someone is trying to read.

| Scope              | Budget                                                  |
| ------------------ | ------------------------------------------------------- |
| Module docstring   | ≤ 10 lines — what this file is for, and its one rule    |
| Function docstring | ≤ 5 lines — behaviour, arguments that are not obvious   |
| Inline comment     | ≤ 2 lines — the reason a reader would otherwise ask for |
| Whole file         | **≤ 15%** of non-blank lines                            |

Measured, not asserted: `pnpm comments` reports the ratio per file.

**Why a budget.** An audit in August 2026 measured a 37% median across the
Stage D files. Volume that high has a specific cost beyond taste — the reasoning
that genuinely matters becomes indistinguishable from the reasoning that does
not, so reviewers skim all of it, and comments drift out of date because nobody
reads them closely enough to notice.

The exceptions, deliberately narrow: a security or privacy invariant that a
future change could silently break, and a decision whose obvious alternative is
wrong in a way that is expensive to discover. Both stay short.

---

## 9. Security practices

- Dependency scanning in CI; automated update PRs.
- Secret scanning on every commit.
- Every customer-data access logged with actor identity (file 15 §5).
- Security review required for: authentication, tenant isolation, external integrations, anything touching customer data.

### 9.1 No production data outside production — with a mechanism

Stating the rule is not enough; rules without mechanisms decay. Enforcement:

- **Non-production environments are seeded from synthetic generators only.** The seed script is the _only_ sanctioned path to populate them.
- **Production database credentials are not available to any non-production configuration** — not in env files, not in CI secrets for non-prod jobs, not in developer machines' default config.
- A developer who needs realistic data uses the generator and improves it, rather than copying a production table.

---

## 10. Documentation

| Type                       | Where                  | When                                             |
| -------------------------- | ---------------------- | ------------------------------------------------ |
| **Specs**                  | `md/`                  | Updated when implementation contradicts the spec |
| **Architecture decisions** | `md/` + ADRs in-repo   | For any significant technical choice             |
| **API**                    | Generated from OpenAPI | Automatic                                        |
| **Code comments**          | Inline                 | Only for _why_, never _what_                     |
| **Runbooks**               | `docs/runbooks/`       | Before anything reaches production               |

---

## 11. Culture over tooling

Research is unambiguous on this: **the most important factor is not tooling but culture — clear code ownership, conventional commits, shared configuration, and continuously measured CI pipelines.**

Concretely:

- **Ownership is explicit**, via CODEOWNERS.
- **Standards are enforced by tooling**, not by remembering. Anything relying on memory will eventually be forgotten.
- **CI health is measured**, not assumed.
- **The spec is the source of truth.** If code and `md/` disagree, one of them is wrong and it gets resolved, not ignored.

---

## 12. Self-critique and revisions

_Written after v1, deliberately looking for what is wrong with the above._

### Critique 1 — This is written for a team that does not exist yet 🔴

**The problem:** §3 mandates pull request review. There is currently **one developer**. A PR you review yourself is theatre, and pretending otherwise builds a habit of going through motions rather than thinking.

**Revision:** while solo, PRs are still used — they run CI, create a reviewable history, and build the habit — but the standard is **self-review with a written checklist against §3.1**, honestly labelled as such. **Where an outside reviewer is genuinely needed** (auth, tenant isolation, anything touching customer data), that is stated in the PR and the work is not merged until reviewed by someone — including by an AI reviewer with the spec in context, which is meaningfully better than nothing.

### Critique 2 — 80% coverage is a vanity metric if applied naively 🔴

**The problem:** coverage measures lines executed, not correctness. Chasing 80% produces tests asserting that getters return values.

**Revision:** the floor stands, but with a stated principle: **coverage is a floor, never a target.** The real standard is that **every branch of business logic and every failure path has a test that would actually fail if the behaviour broke.** A PR at 85% coverage with no test for the error path fails review; one at 75% with thorough behavioural tests passes.

### Critique 3 — Trunk-based development has a prerequisite that does not exist yet 🟡

**The problem:** trunk-based development _depends_ on strong CI. Committing to `main` several times a day without a reliable test suite is not discipline, it is recklessness. §1 asserts the practice before §7 makes it safe.

**Revision:** trunk-based is the target, adopted **progressively**. Until the Stage A gate (file 16) is passed and CI is genuinely reliable, branches may live slightly longer and merges are more deliberate. **The practice is earned by the pipeline, not declared.**

### Critique 4 — The Definition of Done is too long to survive contact with a deadline 🟡

**The problem:** fifteen checkboxes will be skipped under pressure, and a partially-followed standard is worse than a short one that is actually followed, because it teaches that the list is optional.

**Revision:** split into **blocking** and **expected**. Blocking items cannot be waived by anyone: tests, CI green, no secrets, tenant-isolation check, AI boundary check. Expected items may be deferred with an explicit follow-up issue — never silently.

### Critique 5 — E2E test targets are premature 🟡

**The problem:** §4 specifies ~20 E2E tests, but E2E tests against an unstable UI are the most expensive tests to maintain and the first to become flaky. Writing them during Stage D while screens still change daily wastes effort.

**Revision:** E2E tests are written **after a screen's design has stabilised**, not alongside first implementation. The target of ~20 applies at v1 launch, not throughout the build.

### Critique 6 — Nothing addresses what happens when the standard is broken 🟡

**The problem:** the document says what good looks like but not what happens when reality intervenes — an urgent production fix at 2am does not get a leisurely review.

**Revision added as §13.**

### Critique 7 — "No production data in non-production" is stated but not enforced 🟡

**The problem:** §9 states the rule with no mechanism. Rules without mechanisms decay.

**Revision:** staging seeds from **synthetic generators only**, and the seed script is the _only_ sanctioned path to populate non-production environments. Production database credentials are not available to any non-production configuration.

### Critique 8 — The repository structure separates `services/` from `apps/api/` without justification 🟢

**The problem:** minor, but an engineer will ask why ingestion and pipeline are not simply modules inside the API application. Unexplained structure invites drift.

**Revision:** they are separate because they **scale independently and have different concurrency profiles** (file 06 §3.2 — API services take high concurrency, pipeline workers low). Deploying them together would force one scaling policy on two very different workloads. Noted inline in §6.

---

## 13. When the standard cannot be met

Standards that admit no exceptions get ignored entirely at the first genuine emergency. So the exception path is defined rather than improvised:

| Situation                                       | Path                                                                                                               |
| ----------------------------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| **Production incident**                         | Fix first, review after. The PR is merged with an `incident` label and **reviewed within 24 hours**, retroactively |
| **Blocking dependency on external approval**    | Merge behind a feature flag, disabled                                                                              |
| **A blocking DoD item genuinely cannot be met** | It is not waived — the work is not done. Split the change so the shippable part ships                              |
| **Deliberate shortcut for a deadline**          | Allowed, but recorded as a tracked issue with a date. Undocumented shortcuts are the ones that become permanent    |

**The principle:** exceptions are _visible and temporary_. A shortcut that is written down is a decision; one that is not is decay.

---

_This document is versioned with the code. When a standard proves wrong in practice, it is changed here deliberately — not quietly abandoned. §12 is retained rather than folded into the text above, because the reasoning behind a revision is often more valuable than the revision itself._
