# Decision Register

**Status:** ✅ COMPLETE — all sections resolved. Live document; reopen any item by saying so.
**Purpose:** Every open decision across all 13 specification files, in one place, ordered by consequence rather than by file.

**How to use this:** work top to bottom. Section A contains genuine forks with no obvious right answer — these need your judgment. Section B contains high-stakes items where the recommendation is clear but the consequence is large enough to warrant explicit sign-off. Section C can be batch-approved unless something looks wrong.

**Current state: Sections A and B are complete.** All genuine forks and all high-stakes decisions are resolved (Rounds 1–3). Only Section C routine confirmations remain, plus one deferred item (pricing) and one low-stakes open item (A7).

---

# ✅ Resolved — Round 1

### A1. Chat sequencing — **DECIDED: both, phased, native chat as the destination**

**File:** 02 §6
Build both. Slack/Google Chat tracking first for zero-friction adoption; native CAIRN chat as the **planned end state**, with teams migrating voluntarily over time as tracking quality and structured features make it worth moving. Phase 1 earns the right to build Phase 2.
**Added constraint:** Slack tracking is never deliberately degraded to force migration (§6 Phase 3) — that would betray the trust positioning.
**Roadmap impact:** file 13 stands as written.

### A2. Native chat foundation — **DECIDED: commercial chat platform, not Matrix** _(revised recommendation)_

**File:** 02 §4.1
**I reversed my earlier Matrix recommendation after further research.** The decision rule in the field is explicit: _if chat is a feature, ship on a commercial platform; if chat is the product, build custom._ For CAIRN, chat is a feature — the Understanding layer is the product.
Matrix's production sweet spot is sovereignty and federation, which is why its adoption concentrates in **35+ national governments, the UN, NATO, and the Bundeswehr** — with published guidance stating that running a homeserver at scale suits defence and public sector better than SaaS chat. A 10-person team should not operate messaging infrastructure.
**Chosen:** commercial chat infrastructure, **Stream** as leading candidate (best DX and pricing at this stage), Sendbird as alternative if moderation or compliance tooling becomes decisive.
**Two things to manage:** subprocessor exposure (EU residency verified before selection, vendor named in the DPA and Trust Center) and MAU pricing checked against unit economics.
**Revisit only if:** a sovereignty-sensitive customer requires no third party in the trust path, or real cross-organization federation demand appears.

### B1. Four AI Act design properties — **DECIDED: permanent hard boundary**

**File:** 05 §B.3.3
CAIRN never allocates work, evaluates performance, scores or ranks individuals, or informs employment decisions. **Not tradeable, including for a paying customer.**
**Reasoning:** the downside is disproportionate (one feature could reclassify the whole product, imposing conformity assessment and bias testing across everything); the feature contradicts the product's own thesis (Goodhart's Law, file 01 §2); and the refusal is a marketable asset competitors structurally cannot copy — which only works if it is unconditional.
**Enforcement:** terms of service, Trust & Privacy Center, and a zero-tolerance release gate in the evaluation harness (file 10 §5). Tooling, not good intentions.

### B2. Accessibility — **DECIDED: WCAG 2.1 AA from v1**

**File:** 05 §A.6
Built into the design system in Phase 0, not retrofitted. Closes live legal exposure under the European Accessibility Act, in force since June 2025.

---

# ✅ Resolved — Round 2

### A3. RPO / RTO targets — **DECIDED: standard tier**

**File:** 06 §8.1
Activity data: **15 min RPO / 4 hr RTO.** Configuration and auth: **5 min / 1 hr.** Generated docs: 24 hr / 24 hr.
**Implementation consequence:** requires continuous WAL archiving, not daily backups alone. Chat data especially — Slack's history limits make it genuinely unrecoverable rather than merely slow to restore.

### A4. EU cost treatment — **RESOLVED by market sequence**

**Files:** 06 §6, 08 §D.6
**Founder decision on go-to-market:** **US first → Tier 1 English-speaking (UK, Canada, Australia, Singapore) → Tier 2.**
This dissolves the question rather than answering it: **EU entry is deliberately deferred**, so the ~10% regional-endpoint premium is never incurred until a funded market-entry decision. When EU entry happens, residency sits on **Business tier and above**, where margin absorbs it.
**Nuance added to the spec:** self-serve signup does not respect go-to-market plans. An EU team signing up triggers GDPR, AI Act, and EAA obligations regardless of intent — so **signups are geo-gated to supported markets initially** (file 06 §6.2), converting EU compliance from an ambient risk into a deliberate choice.
**Not deferred:** WCAG 2.1 AA remains v1. US ADA-based web accessibility litigation is common, so the standard is justified by the US market alone.

### A5. Seat model — **DEFERRED by founder, provisional placeholder recorded**

**File:** 08 Part E
Recorded as **PROVISIONAL** so dependent files have something concrete to reference. Working assumption: **flat team pricing** (~$99/month up to 15 people) rather than per-seat.
**The tension worth resolving before beta:** CAIRN has no single-player mode, so **per-user pricing creates a financial disincentive to connect the whole team** — working directly against the activation requirement. A founder weighing "$12 × 15" has real reason to connect only engineers, which is precisely how activation fails.
**Scheduled:** revisit before beta launch.

### A6. Figma timing — **DECIDED: Year 2, with v1 mitigations**

**File:** 08 §A.4
Three mitigations ship in v1 instead: design contribution surfaced from chat and meetings, the designer's own view weighting non-code work equally with commits, and explicit contribution-type coverage in My Week.
**Reasoning:** the adoption risk is _feeling unseen_, not _lacking Figma_. Most design judgment appears in discussion before it appears in a file — so chat and meeting capture addresses the real cause more completely than a file-edit connector would. Revisit when a customer asks by name.

---

# Section A — Remaining forks

### A7. First MCP-connected source after GitHub

**File:** 07 §7
**Candidates:** Notion, Linear. **Recommendation:** let early customer signal decide rather than pre-committing. Low stakes — can be deferred until the question is real.

---

# ✅ Resolved — Round 3 (Section B complete)

### B8. Worker notification — **DECIDED: product-led invitation, own record first**

**File:** 11 §4.1 — _the highest-leverage design decision in the product_
CAIRN emails each person directly with the value proposition and the promise: what it sees, what it will never do, and that they control it. **The first screen is their own contribution record; the first available action is correcting it.** Opt-out is offered inline, never buried in settings.
**Why this framing wins:** it delivers the trust story from the product itself, at the exact moment every future user is deciding what CAIRN is — before anyone else's interpretation can frame it.

### B12. Confidence display — **DECIDED: always show honest certainty**

**Files:** 05 §A.2.2, 03 §6, 09 §8
Three visual tiers everywhere — **Verified / Observed / Suggested** — with hedged wording on anything uncertain, and no numeric percentages.
**Accepted trade knowingly:** demos will look less magical than competitors showing unqualified confidence. Given ~30% meeting misattribution, their confidence is a delayed trust failure, not an advantage. **This decision must be defended when demo pressure arrives** — the temptation to turn the dial toward confidence is the predictable failure mode here.

### B13. SOC 2 — **DECIDED: controls from month 1, formal audit kickoff month 7**

**File:** 06 §10
Infrastructure controls (SSO, centralized logging, backups with tested restore, change management) are configured in Phase 0 regardless — they generate audit evidence automatically as a by-product. The formal 14–22 week Type I process begins month 7, completing shortly after beta. Matches the original plan and the $25–45K budget.

### B5. Evaluation harness — **DECIDED: Phase 1, alongside the AI pipeline**

**File:** 10
Built in months 3–4 with the Understanding layer itself, not retrofitted.
**Why this matters beyond quality:** the golden dataset built from real user corrections becomes a genuinely proprietary asset (file 10 §9) — competitors cannot access CAIRN's specific pattern of failures and fixes. The investment that looks like engineering discipline is also the moat.

---

## ✅ Auto-confirmed — no defensible alternative

These were listed as Section B confirmations, but on review each has only one responsible answer. Recorded as decided; raise any objection and they reopen.

| #       | Decision                                                                                                                                                        | Why there is no real alternative                                                                                                                                     |
| ------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **B3**  | **Background-job tenant isolation controls** (06 §4.3) — tenant ID mandatory on every queued message, single job wrapper, fail-closed, cross-tenant tests in CI | A job that loses tenant context **silently reads across tenants**. For a trust product this is the worst possible failure, and it fails invisibly rather than loudly |
| **B4**  | **Prompt injection invariant** (09 §6) — no pipeline stage touching untrusted content may hold the capability to act                                            | CAIRN ingests attacker-influenceable content by design. The invariant costs nothing now and is expensive to introduce later                                          |
| **B6**  | **Attribution correctness in MVP** (01 §5) — co-author parsing, bot filtering, identity resolution                                                              | Misattributed work destroys trust irrecoverably. A later fix does not restore a founder's confidence once they've seen the product credit the wrong person           |
| **B7**  | **Per-tenant region assignment from day one** (06 §6.3)                                                                                                         | Retrofitting is data migration under compliance pressure. Deferring EU _entry_ does not justify deferring the _capability_                                           |
| **B9**  | **Team-level activation as primary metric** (08 §B, 11 §2)                                                                                                      | CAIRN has no single-player mode. Optimizing individual activation means the dashboard reports success while customers churn                                          |
| **B10** | **Regulatory corrections acknowledged** (05 §B.2.1, §B.3.1) — EU basis is legitimate interest, not consent; AI Act deadline moved to Dec 2027                   | These are facts about the regulatory landscape, not choices                                                                                                          |
| **B11** | **Universal all-party meeting consent** (03 §3.4)                                                                                                               | Thirteen US states require it, strictest law governs distributed teams, and errors carry criminal exposure. Jurisdiction-detection logic is fragile                  |

---

# Section B — _(complete)_

All Section B items resolved. Retained below for reference.

### B1. The four regulatory design properties as a permanent boundary 🔴

**File:** 05 §B.3.3 — _the single most consequential confirmation in the folder_
CAIRN must **never** allocate work, evaluate performance, score/rank individuals, or inform employment decisions. These are not values — they are what keeps the product outside EU AI Act high-risk classification. Reclassification triggers conformity assessment, bias testing, and continuous monitoring obligations.
**Confirm:** these are permanent constraints with financial consequences, not tradeable later for a customer requesting individual scoring.

### B2. Accessibility (WCAG 2.1 AA) as a v1 requirement 🔴 **TIME-SENSITIVE**

**File:** 05 §A.6
The European Accessibility Act has been **in force since June 2025**. It applies to non-EU companies serving EU customers, names SaaS explicitly, covers B2B software where employees are end users, and carries market-access restriction as a penalty. **This is currently unaddressed legal exposure.**
**Confirm:** WCAG 2.1 AA baseline from first release, built into the design system in Phase 0.

### B3. Background-job tenant isolation controls 🔴

**File:** 06 §4.3 — _the sharpest technical risk in the architecture_
CAIRN is almost entirely background jobs, and a job that loses tenant context **silently reads across tenants** rather than failing loudly.
**Confirm:** tenant ID mandatory on every queued message, a single job wrapper setting context, fail-closed behavior, and cross-tenant leakage tests in CI.

### B4. Prompt injection threat model

**File:** 09 §6, 07 §4.4
CAIRN ingests attacker-influenceable content by design. The architectural invariant: **no pipeline stage that touches untrusted content may hold the capability to act.**
**Confirm:** this constrains all future design — any proposal to give the pipeline action capability must be evaluated against it.

### B5. Evaluation harness built in Phase 1, not later

**Files:** 10 (intro), 13 §3
Without it, every quality regression looks identical — model change, prompt tweak, and data drift are indistinguishable. Most commonly skipped investment in AI products.
**Confirm:** built alongside the Understanding layer.

### B6. Attribution correctness is MVP scope, not polish

**Files:** 01 §5, §8; 13 §5
Squash-merge co-author parsing, bot filtering, identity resolution. Misattributed work destroys trust irrecoverably — a later fix does not restore it.
**Confirm:** ships with the first release.

### B7. Per-tenant region assignment from day one

**File:** 06 §6
Retrofitting after tenants exist is data migration under compliance pressure.
**Confirm:** built in Phase 0 despite only one live region.

### B8. Worker notification framed as an invitation, not a compliance notice

**File:** 11 §4.1 — _highest-leverage design decision in the product_
It is legally required, reaches every future user, and arrives before anyone has formed an opinion. Handled well it is the best marketing CAIRN will ever do; handled poorly it is where trials quietly die.
**Confirm:** designed as an invitation carrying the trust promise, with inline per-source opt-out and the person's own record shown first.

### B9. Team-level activation as the primary metric

**File:** 08 §B.3–B.4, 11 §2
CAIRN has no single-player mode. A founder who activates alone and never brings the team churns while the dashboard reports success.
**Confirm:** team activation is primary; file 00 §3 metrics update accordingly.

### B10. Regulatory corrections acknowledged

**Files:** 05 §B.2.1, §B.3.1
EU lawful basis is **legitimate interest with documented assessment**, not consent (consent is invalid in employment contexts). AI Act high-risk deadline moved to **December 2, 2027**.
**Confirm:** product design unchanged; legal documentation and timeline assumptions change.

### B11. Universal all-party consent for meetings

**File:** 03 §8.1
Thirteen US states require it, strictest law governs distributed teams, and errors carry criminal exposure. Jurisdiction-detecting logic is fragile.
**Confirm:** strictest standard universally.

### B12. Failure behavior — admitting uncertainty over confident completion

**Files:** 09 §8, 03 §8.4
This makes demos less impressive than competitors showing unqualified confidence.
**Confirm:** accepted knowingly. Given 30% meeting misattribution rates, competitors' confidence is a delayed trust failure, not an advantage.

### B13. SOC 2 controls configured from day one

**File:** 06 §10
64+ control points requiring sustained evidence. Configured early, evidence generates itself; retrofitted, the $25–45K budget balloons.
**Confirm:** control baseline in Phase 0, plus early adoption of a compliance automation platform.

---

# ✅ Section C — Approved (Round 4)

**All 64 routine confirmations approved as written.** These were recommendations with no expected disagreement; each is now the working decision. Any single item can be reopened by saying so.

**Two items were not decisions and remain as action items — see the Action Items section below.**

Recorded below for reference, grouped by file.

**File 00 — Overview**

- C1. Purpose and problem statement as written
- C2. Target user table and v1 customer profile
- C3. The out-of-scope list

**File 01 — GitHub**

- C4. GitHub-only for v1 (no GitLab/Bitbucket)
- C5. Per-repository opt-out for contributors
- C6. 90-day default backfill
- C7. Full diff content only on explicit request
- C8. Restrained AI-attribution posture — capture reliable signals, no probabilistic human-vs-AI scoring

**File 02 — Chat**

- C9. Apply to Slack Marketplace early
- C10. Value delivered from real-time capture alone; backfill is enhancement
- C11. Private channels and DMs excluded by default
- C12. DLP/eDiscovery as Year 2+, architecture must not foreclose

**File 03 — Meetings**

- C13. No meeting bot in v1 (artifact ingestion only)
- C14. Positioned as _where meeting outcomes connect to real work_, not a notetaker competitor
- C15. Meeting-derived claims visibly marked lower-certainty
- C16. Google Workspace tier as an onboarding qualifying question
- C17. Prompt teams to enable transcription, never enable silently

**File 04 — Documentation**

- C18. Positioned on staleness and the _why_, not generation quality
- C19. ADR generation treated as a headline differentiator
- C20. Staleness detection ships in Phase 1
- C21. Delivery as pull request, not hosted docs site
- C22. Never autonomous — no configuration permits publishing without approval
- C23. ADR generation gated on files 02/03 accuracy
- C24. Internal documentation only for v1

**File 05 — Design & Compliance**

- C25. Categorical certainty tiers, never numeric percentages
- C26. Contractual prohibition on employment-decision use
- C27. Region defaults automatic from address, with admin override
- C28. Trust & Privacy Center serves both in-product and sales
- C29. 12-month default retention, per-tenant configurable

**File 06 — Infrastructure**

- C30. Cloudflare **Workers + OpenNext**, not Pages _(correction to earlier plan)_
- C31. Vertex AI as the Claude path, with provider abstraction built day one
- C32. Cloud Run over GKE for 12 months
- C33. `us-central1` first; EU region triggered by first EU customer
- C34. Confirm whether GCP/Cloudflare accounts exist or need creating

**File 07 — MCP**

- C35. MCP as the **breadth** mechanism, not a webhook replacement _(architectural correction)_
- C36. Full security control set including tool-definition hash pinning
- C37. Vetting: registry listing + vendor preference + security review + version pinning
- C38. Skip deprecated Roots/Sampling/Logging
- C39. Fast-follow launch timing

**File 08 — Users & Market**

- C40. Protect the small buying committee; upmarket is a deliberate later choice
- C41. Agency vertical as named Year 2 target, with client-facing view as enabler
- C42. Competitive framing: integration-plus-trust, not category-by-category superiority

**File 09 — Understanding Layer**

- C43. Temporal knowledge graph over plain vector search
- C44. Grounding absolute — unsupported claims suppressed, not caveated
- C45. Staged model routing (cheap stages 1–2, premium stage 4)
- C46. Bounded retrieval over large-context stuffing
- C47. Batching for scheduled outputs, real-time for live queries
- C48. PostgreSQL + pgvector, not a dedicated graph database

**File 10 — Evaluation**

- C49. Zero-tolerance boundary gate — any scoring/ranking output blocks release
- C50. User corrections feed the golden dataset, disclosed transparently
- C51. 1% production sampling for human review — assign an owner
- C52. Dogfooding from month one

**File 11 — Onboarding**

- C53. Substance-gated first brief rather than schedule-based
- C54. Contextual guidance over tours (only 5% complete multi-step tours)
- C55. Honest disclosure of the Slack history limitation
- C56. Opt-out rate <10% as a tracked trust metric

**File 12 — Data Model**

- C57. CloudEvents envelope rather than a bespoke schema
- C58. `tenantid` structurally on the envelope
- C59. Two timestamps — `time` vs `ingestedat`
- C60. Facts superseded, never overwritten
- C61. Producer contract as the acceptance criterion for new sources

**File 13 — Roadmap**

- C62. Category-based sequencing (expensive-to-reverse work first)
- C63. Phase gates are real gates that can pause the plan
- C64. Phases framed as evidence-gathering, not feature milestones

---

## Status summary

| Section               | State                                                                    |
| --------------------- | ------------------------------------------------------------------------ |
| **A — Genuine forks** | ✅ Resolved (Rounds 1–2). One low-stakes item open: A7, first MCP source |
| **B — High-stakes**   | ✅ Resolved (Rounds 1, 3)                                                |
| **C — Routine**       | ✅ Approved (Round 4)                                                    |
| **Deferred**          | Pricing / seat model (file 08 Part E) — revisit before beta              |

**The specification is decided. All 15 files move from Draft to Locked.**

---

## Action items — not decisions, but needed before build starts

These surfaced during the process and require information or a named owner rather than a choice:

| #        | Item                                                                                                                        | Needed from                       |
| -------- | --------------------------------------------------------------------------------------------------------------------------- | --------------------------------- |
| **AI-1** | **Do GCP and Cloudflare organization accounts already exist, or be created fresh?** Blocks Phase 0 infrastructure setup     | Founder                           |
| **AI-2** | **Who owns the weekly 1% production output review?** (file 10 §4) A recurring commitment that needs a name, not a role      | Founder                           |
| **AI-3** | **Verify EU data residency support and MAU pricing** for the chosen chat platform (Stream) before committing (file 02 §4.2) | Engineering, before Phase 2       |
| **AI-4** | **Confirm embedding model dimensions against the 2,000-dim HNSW ceiling** before model selection (file 06 §4.4)             | Engineering, Phase 1              |
| **AI-5** | **Schedule the pricing revisit** before beta launch (file 08 Part E)                                                        | Founder                           |
| **AI-6** | **Legal counsel review** of file 05 Part B and the LIA, before any EU exposure                                              | Founder, when EU entry is planned |

---

## Deferred, with triggers

| Item                      | Revisit when                                                               |
| ------------------------- | -------------------------------------------------------------------------- |
| Pricing / seat model      | Before beta launch                                                         |
| Figma integration         | A customer asks by name                                                    |
| Two-way chat bridging     | Genuine cross-org federation demand appears                                |
| Matrix as chat foundation | A sovereignty-sensitive customer requires no third party in the trust path |
| EU market entry           | Deliberate, funded market-entry decision                                   |
| Microsoft Teams           | A Microsoft 365 customer segment exists                                    |
| GitLab / Bitbucket        | Customer demand                                                            |
| CAIRN's own MCP server    | Year 2                                                                     |
| DLP / eDiscovery          | Moving upmarket, Year 2+                                                   |

---

_This register was the gate between specification and implementation. That gate is now open — the decisions are made, the trade-offs are recorded with their reasoning, and the six action items above are the only things standing between here and writing code._
