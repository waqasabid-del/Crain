# Roadmap & Build Sequencing

**Status:** ✅ LOCKED — decisions resolved, ready for implementation
**Depends on:** Every file — this consolidates sequencing decisions distributed across them
**Purpose:** One view of what gets built when, what blocks what, and what must be right the first time

---

## 1. The three categories of work

Not all decisions carry equal reversal cost. Sequencing should follow that, not feature appeal.

| Category                 | Characteristic                                              | Examples                                                                                                                                        |
| ------------------------ | ----------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| **Expensive to reverse** | Retrofitting means data migration under compliance pressure | Per-tenant region assignment (06 §6), tenant isolation (06 §4.3), `ActivityEvent` schema (12), SOC 2 controls (06 §10), accessibility (05 §A.6) |
| **Expensive to skip**    | Cheap to build now, very costly to add after scale          | Evaluation harness (10), cost attribution (09 §7.3), attribution correctness (01 §5)                                                            |
| **Freely deferrable**    | Add anytime without penalty                                 | Native chat (02), MCP (07), meetings (03), ADR generation (04)                                                                                  |

**Sequencing rule:** category 1 in month one, category 2 alongside the first feature, category 3 when justified by evidence.

---

## 2. Dependency graph

```
FOUNDATION (must precede everything)
  05 Design & compliance principles ──┐
  06 Infrastructure decisions ────────┤
  12 ActivityEvent schema ────────────┤
                                      ▼
CRITICAL PATH
  01 GitHub capture ──▶ 09 Understanding layer ──▶ Founder Brief
                              ▲
  10 Evaluation harness ──────┘  (parallel from day one, never after)

SECOND WAVE (each gated)
  02 Chat integration ──────▶ richer brief
  04 Docs Phase 1 ──────────▶ (needs only 01)
  11 Onboarding ────────────▶ (needs 01 + 09 producing real output)

THIRD WAVE (gated on accuracy, not calendar)
  03 Meetings ──────────────▶ needs 09 validated on cleaner sources
  04 Docs Phase 2 (ADRs) ───▶ needs 02 + 03 accurate
  07 MCP ───────────────────▶ needs 01 stable
  02 Native chat (Matrix) ──▶ needs core value proven
```

---

## 3. Phased plan

The original proposal's nine-month structure holds. This adds the technical dependencies discovered during specification.

### Phase 0 — Foundation (Months 1–2)

**Non-negotiable, because retrofitting is expensive:**

- [ ] Cloudflare Workers + OpenNext frontend shell (06 §2.1)
- [ ] GCP: Cloud Run, Cloud SQL, Pub/Sub, Secret Manager
- [ ] **Per-tenant region assignment**, even with one live region (06 §6)
- [ ] **RLS tenant isolation + background-job context wrapper, fail-closed** (06 §4.3)
- [ ] **`ActivityEvent` schema and validation** (12)
- [ ] SOC 2 control baseline: SSO, centralized logging, backups with tested restore (06 §10)
- [ ] Accessibility baseline in the design system — WCAG 2.1 AA (05 §A.6)
- [ ] OpenTelemetry instrumentation scaffolding (10 §7)

**In parallel, non-engineering:**

- [ ] 25–30 customer discovery interviews
- [ ] **5–10 signed LOIs — the gate on Phase 1** (original proposal)
- [ ] Legal: Delaware entity, LIA drafting for EU (05 §B.2.1)

> **Gate:** fewer than 5 LOIs by end of Month 3 → pause and reassess. Carried from the original proposal's tranche structure.

### Phase 1 — Critical path (Months 3–4)

- [ ] GitHub App, webhooks with verify→enqueue→ack (01 §4.1)
- [ ] **Attribution correctness: co-authors, bot filtering, identity resolution** (01 §5) — MVP scope, not polish
- [ ] 90-day backfill (01 §7)
- [ ] Understanding layer Stages 1–4 (09 §2)
- [ ] Temporal graph with validity intervals (09 §3)
- [ ] Grounding: mandatory citation + span verification (09 §5)
- [ ] **Evaluation harness — built alongside, never after** (10)
- [ ] Cost attribution per feature/tenant/model (09 §7.3)
- [ ] **Founder Brief v1**
- [ ] Dogfooding from the first working brief (10 §2.1)

> **Gate:** the brief must be genuinely useful on the team's own data before proceeding. If it is not, no amount of additional sources fixes it.

### Phase 2 — Team activation (Months 5–6)

- [ ] Slack + Google Chat integration (02 §6 Phase 1)
- [ ] Classification stage, conservative threshold (02 §7.1)
- [ ] **Worker notification flow** (11 §4.1) — the highest-leverage design work in the product
- [ ] My Week and Team Feed
- [ ] Per-person correction, one tap (05 §A.3)
- [ ] Trust & Privacy Center (05 §B.6)
- [ ] Onboarding flow (11 §3–4)
- [ ] Docs Phase 1: README, PR summaries, staleness detection (04 §7)
- [ ] Closed alpha, 5–10 design partners

> **Gate:** team activation above 40%, opt-out below 10% (11 §7). These measure whether the trust positioning works. If opt-out is high, fix the framing before scaling.

### Phase 3 — Depth and readiness (Months 7–8)

- [ ] Meeting intelligence (03) — consent gating, artifact ingestion, confidence controls
- [ ] Docs Phase 2: ADR generation, once 02 and 03 accuracy is demonstrated (04 §7)
- [ ] SOC 2 Type I audit process (14–22 weeks from kickoff — start no later than Month 7)
- [ ] Penetration test
- [ ] Billing, admin controls, SSO for Business tier
- [ ] MCP client support (07), if customer demand justifies

### Phase 4 — Paid beta (Month 9)

- [ ] Open to 50–100 invited teams
- [ ] First paying customers

> **Continuation gate** (original proposal): 10+ paying teams, >70% retention at 30 days, evaluation score >85%, unit economics within 20% of target.

---

## 4. What is deliberately deferred

| Item                              | Deferred until                            | Rationale                                                                |
| --------------------------------- | ----------------------------------------- | ------------------------------------------------------------------------ |
| **Native chat on Matrix** (02 §6) | Post-validation, Year 1–2                 | Largest single engineering investment; needs the core value proven first |
| **Two-way bridging** (02 §2.4)    | With native chat                          | Shares the Matrix foundation                                             |
| Microsoft Teams (03 §8)           | A Microsoft-based customer segment exists | No demand yet                                                            |
| GitLab / Bitbucket (01)           | Customer demand                           | Splits effort before the core is proven                                  |
| Non-software verticals (08 §D)    | Year 2                                    | Market expansion, not a rebuild                                          |
| CAIRN's own MCP server (07 §7)    | Year 2                                    | Inverse capability, distinct work                                        |
| DLP / eDiscovery (02 §5)          | Year 2+                                   | Only possible with native chat; not needed by 5–20 person teams          |
| External-facing docs (04 §5.4)    | Not planned for v1                        | Higher accuracy bar; direct fight with Mintlify                          |

---

## 5. Sequencing risks

| Risk                                   | Consequence                                                | Control                          |
| -------------------------------------- | ---------------------------------------------------------- | -------------------------------- |
| **Evaluation harness deferred**        | Quality drifts silently; every regression looks identical  | Built in Phase 1, not after (10) |
| **Attribution treated as polish**      | Trust destroyed in pilot, unrecoverable by later fix       | MVP scope (01 §5, §8)            |
| **ADRs shipped before 02/03 accurate** | Authoritative documents asserting decisions never made     | Hard gate (04 §7)                |
| **Tenant isolation retrofitted**       | Cross-tenant leakage — worst possible failure              | Phase 0 (06 §4.3)                |
| **Regions retrofitted**                | Data migration under compliance pressure                   | Phase 0 (06 §6)                  |
| **Accessibility retrofitted**          | Legal exposure already live; expensive rework              | Phase 0 design system (05 §A.6)  |
| **Native chat pulled forward**         | Consumes the capacity belonging to the Understanding layer | Explicitly deferred (§4)         |

---

## 6. The three questions each phase answers

Framing the plan as evidence-gathering rather than feature delivery:

| Phase | Question                                                    | Evidence of success                                   |
| ----- | ----------------------------------------------------------- | ----------------------------------------------------- |
| **1** | Can we produce a genuinely useful brief from real activity? | The team's own founder reads it daily by choice       |
| **2** | Will a whole team accept being tracked this way?            | Team activation >40%, opt-out <10%                    |
| **3** | Will they pay, and does the economics work?                 | 10+ paying teams, unit economics within 20% of target |

**If Phase 1's question fails, nothing downstream matters.** This is why the critical path is narrow and the second wave is gated rather than parallel.

---

## Decisions requested from founder

1. **Category-based sequencing (§1)** — confirm expensive-to-reverse work is done in Phase 0 even though it produces nothing demonstrable, and that this is understood as the correct trade.
2. **Evaluation harness in Phase 1 (§3)** — confirm it is built alongside the Understanding layer, not deferred.
3. **Attribution correctness in MVP (§3)** — confirm co-author parsing, bot filtering, and identity resolution ship with the first release.
4. **Phase gates as real gates (§3)** — confirm each gate can genuinely pause the plan, particularly the Phase 2 gate on opt-out rate.
5. **Native chat deferred (§4)** — confirm, pending the file 02 §10 sequencing decision, which this plan currently assumes resolves to phased.
6. **Phase framing (§6)** — confirm phases are evidence-gathering rather than feature milestones, and that Phase 1 failure means stopping rather than adding sources.

---

_This roadmap assumes the file 02 chat sequencing decision resolves to the phased approach. If native chat is chosen for day one instead, Phases 1–3 change materially and this file requires rewriting — which is why that decision is the highest-priority item in [14-decision-register.md](14-decision-register.md)._
