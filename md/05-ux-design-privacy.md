# Pillar 5 — Design, Trust & Compliance

**Status:** ✅ LOCKED — governing document. Regulatory findings in §B.2.1, §B.3.1, §A.6
**Depends on:** [00-overview.md](00-overview.md), [08-roles-and-industries.md](08-roles-and-industries.md), [09-understanding-layer.md](09-understanding-layer.md)
**Governs:** All pillars. Where any file conflicts with this one, this file controls.

**Founder's stated goal:** CAIRN must be easy enough for everyone to use and understand — minimalist, professional design — and must respect each company's and each country's privacy and legal requirements individually, not with one blanket policy.

Two parts: **(A)** how the product behaves for a human being, **(B)** how it handles data lawfully. Both are first-class requirements — for CAIRN, ease of use and trust _are_ the competitive advantage, not packaging around the AI.

---

# Part A — Design & Ease of Use

## A.1 Design principles

| Principle                                        | In practice                                                                                                                                                                               |
| ------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Prose over dashboards**                        | Plain-English narrative is the primary output. This is also the core differentiation against engineering-intelligence competitors (file 01 §1.1), whose output requires metrics literacy. |
| **One primary view per role**                    | Each role in file 08 lands on a single screen answering their main question. Depth on demand, never required.                                                                             |
| **No jargon by default**                         | No "sprint," "epic," "velocity," or "burndown" unless the team already uses those words.                                                                                                  |
| **Fast to first value**                          | Signup to first useful output under 30 minutes. Every setup step is a design cost, not just an engineering one.                                                                           |
| **One visual system across all pillars**         | Code, chat, meeting, and documentation activity render through shared components — one system, not four connected tools.                                                                  |
| **No gamification, scoring, or ranking visuals** | No leaderboards, points, or comparative charts. A design rule, not only a policy one: visual scoring undermines the trust posture even absent a formal ranking feature.                   |

## A.2 Designing for uncertainty — the defining UX problem

CAIRN is a probabilistic product presenting claims about people's work. This is genuinely harder than conventional software design, and current practice identifies the reason precisely:

> **The issue isn't just inaccuracy — it's confidence.** AI doesn't signal uncertainty the way humans do. It presents outputs as complete and coherent, which makes them easy to trust without sufficient validation.

CAIRN's sources vary enormously in reliability: a GitHub pull request assignment is unambiguous; a commitment inferred from a meeting transcript carries **~30% speaker misattribution risk** (file 03 §2). Presenting both with identical authority is the fastest way to lose trust permanently.

### A.2.1 Never show percentages

A critical design finding, and one that is easy to get wrong: uncertainty is communicated through **visual cues — subtle color variation, lighter text weight, and explicit labels such as "AI suggestion" versus "AI verified" — rather than asking users to interpret accuracy percentages.**

A "73% confident" badge is worse than useless: it looks rigorous, means nothing to a non-technical user (file 08 §A.5), and invites false precision. **CAIRN displays certainty categorically, never numerically**, in the user interface. Numeric confidence exists internally for evaluation and thresholds (file 10) — it never surfaces to users.

### A.2.2 Three certainty tiers

| Tier          | Source examples                                                       | Treatment                                                             |
| ------------- | --------------------------------------------------------------------- | --------------------------------------------------------------------- |
| **Verified**  | GitHub PR assignment, merged commit, explicit chat command            | Stated plainly as fact                                                |
| **Observed**  | Decision extracted from clear discussion; corroborated across sources | Stated with light hedging; provenance one click away                  |
| **Suggested** | Meeting-derived commitment, single-source inference                   | Explicitly hedged language, visually distinct, verification prominent |

**Language carries the tier, not just styling.** _"It sounded like Ali agreed to take the auth work"_ invites correction; _"Ali is assigned the auth work"_ asserts what the system may not be entitled to assert. Enforced in the prompt layer, tested in evaluation (file 10 §1).

## A.3 Human oversight matched to risk

Current practice is explicit that human-in-the-loop design means **matching the interaction pattern to the level of risk** — simple accept/reject for low-risk suggestions, preview-and-approval as stakes rise. Further, **threshold-based automation** (the confidence level above which the system acts without interruption, below which it surfaces for review) **should differ across output types within the same product.**

CAIRN's map:

| Output                                     | Risk     | Pattern                                                                |
| ------------------------------------------ | -------- | ---------------------------------------------------------------------- |
| Team Feed entry                            | Low      | Auto-surface; correctable                                              |
| Founder Brief                              | Medium   | Auto-generate; prominent correction affordance                         |
| Claim about a specific person's commitment | **High** | Hedged by default; correction one tap away (file 03 §6.1)              |
| Generated documentation                    | **High** | Never autonomous — human approval required before merge (file 04 §4.1) |

**Correction must be effortless, not merely possible.** File 03's error rates guarantee corrections will be frequent, and every correction is both a trust moment and evaluation signal (file 09 §7, file 10 §2.1). A correction buried in a settings page is a correction that never happens — and an error that silently persists.

## A.4 Visual direction

Clean typography, generous whitespace, restrained palette, minimal iconography — closer to Linear or Notion than Jira or Monday.com. Deliberate signalling: a calm interface reinforces _this tool observes and informs; it does not judge or rank._ Given this product's surveillance adjacency, visual restraint does real positioning work.

## A.5 Five roles, one data model

Per file 08, five roles need different primary views over identical underlying data:

- **Founder / Owner** — one daily narrative brief across the team.
- **Developer** — their own record, derived automatically, zero manual entry.
- **Product Manager** — cross-source view tying activity to initiatives.
- **Designer** — reviews, iteration, and decisions weighted equally with commits, so design contribution is never invisible.
- **Marketing / Sales / Ops** — plain-English summary, zero technical fluency required.

**Review gate:** before any feature ships — _does this output make sense to all five roles, or does it silently assume a technical reader?_

## A.6 Accessibility — **[DECIDED: WCAG 2.1 AA from v1]**

**Founder decision: WCAG 2.1 Level AA is a baseline from the first release, built into the design system in Phase 0.** Not a retrofit.

**This was a compliance gap in the plan as previously written, and the requirement is already in force.**

The **European Accessibility Act (EAA)** enforcement deadline was **June 28, 2025** — it has passed. Critically:

- **It applies to any organization selling to EU customers regardless of where the organization is based.** A company with no EU presence must still comply if it serves EU customers digitally.
- **SaaS is explicitly among the most-affected sectors.**
- It applies to **B2B software where employees are end users** — precisely CAIRN's model.
- The technical standard is **EN 301 549, which incorporates WCAG 2.1 Level AA.** (WCAG 2.2 exists but is not yet in the harmonized standard; **2.1 AA is the operative benchmark.**)
- Penalties include enforcement notices, financial penalties, and **restricted market access.**

**Requirement:** WCAG 2.1 Level AA is a design and engineering baseline from the first release, not a retrofit. Retrofitting accessibility into a mature interface is substantially more expensive than building to it — and CAIRN's EU ambitions (file 06 §4) make this non-optional rather than aspirational.

This also aligns with the product's own thesis: a tool claiming _"easy for everyone to use"_ while being unusable with a screen reader is not delivering on its stated premise.

## A.7 Tone as a design requirement

CAIRN's AI writes about people's work, so tone is a trust surface. All generated text is factual, neutral, and non-presumptive — describing what happened without praising, criticizing, editorializing, or inferring motive. Enforced in the prompt layer, tested as rigorously as factual accuracy (file 10 §1).

---

# Part B — Privacy, Trust & Compliance

## B.1 Why this is a product feature

A system reading code, conversation, and meetings to describe what people are doing sits close to the line between coordination software and workplace monitoring. Which side it lands on determines whether teams adopt it willingly — and, per §B.3, whether it attracts a classification that would materially change the business.

## B.2 Core trust commitments — non-negotiable

1. **Symmetrical visibility** — everyone sees the same categories of information, including about leadership. No hidden management-only view.
2. **No numeric scoring or ranking** — narrative only, never comparative measurement between people (grounded in Goodhart's Law; file 01 §2).
3. **Employee-owned records** — every person can view, correct, and annotate what CAIRN records about them.
4. **Non-code contribution surfaced deliberately** — reviews, mentoring, facilitation, documentation appear alongside commits.
5. **Granular opt-in** — per source, per person, per channel or repository. Nothing on by default.
6. **No customer data in training** — contractually and technically enforced (file 09 §8). Note that this is an active allegation against a category competitor (file 03 §1.2).

### B.2.1 Correction: consent is not the EU lawful basis

The initial draft framed opt-in consent as CAIRN's legal foundation in the EU. **This is incorrect and must not reach a customer contract.**

Under GDPR, **consent is generally not a valid lawful basis in employment contexts**, because the employer–employee power imbalance means consent cannot be freely given. The correct basis is **legitimate interest with a documented Legitimate Interest Assessment (LIA).**

> CAIRN's EU lawful basis is **legitimate interest with documented assessment**. The granular opt-in controls in B.2(5) keep that interest proportionate, demonstrable, and defensible — they are not themselves the legal basis.

Product design does not change; legal documentation does. **Required before any EU customer onboards:** a completed LIA and contract language reflecting legitimate interest. Surfaced independently in file 02 §8.1 and file 03 §3.3.

## B.3 EU AI Act — status and classification strategy

### B.3.1 The deadline moved

High-risk Annex III obligations were scheduled for **August 2, 2026**. Following political agreement on the Commission's simplification package, this is **extended to December 2, 2027**.

**Breathing room, not reprieve.** The Commission has published draft guidelines on high-risk AI in employment, and enterprise buyers increasingly require AI governance documentation regardless of enforcement dates.

### B.3.2 The uncomfortable proximity, stated honestly

Annex III's employment category covers recruitment and candidate evaluation — but also **allocation of tasks based on individual behaviour or personal traits, and monitoring and evaluating the performance and behaviour of workers.**

**CAIRN operates adjacent to that language.** A system reading employee activity and summarizing individual contribution is close enough to "monitoring performance and behaviour" that the distinction must be deliberate and defensible, not assumed.

### B.3.3 Why CAIRN falls outside high-risk classification — **[DECIDED: permanent hard boundary]**

**Decision: the four properties below are permanent product constraints, not values subject to revision.** If a paying customer requests individual scoring, ranking, or performance evaluation, the answer is no.

**Reasoning behind the decision.** Three factors make flexibility here a bad trade:

1. **The downside is disproportionate.** Adding one scoring feature could reclassify the entire product as high-risk, triggering conformity assessment, bias testing, technical documentation, human-oversight audit, and continuous monitoring across _everything_ — not just the new feature. A single customer's request would impose obligations on the whole business.
2. **The feature contradicts the product's own thesis.** File 01 §2 documents that productivity metrics degrade the behavior they measure (Goodhart's Law). A scoring feature would make CAIRN worse at its actual job, not just riskier.
3. **The refusal is a marketable asset.** _"The tool that refuses to be used against you"_ is a position competitors selling management dashboards structurally cannot occupy (file 08 §C.2). Ambiguity here forfeits that advantage — a boundary only functions as a trust signal if it is unconditional.

**Practical consequence:** this belongs in terms of service (§B.3.4), in the Trust & Privacy Center (§B.6), and as a zero-tolerance release gate in the evaluation harness (file 10 §5). It is enforced by tooling, not by good intentions.

| Annex III trigger                           | CAIRN's position                                                                                                                                 |
| ------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Allocating tasks** by behaviour or traits | CAIRN never allocates. Humans assign; CAIRN _observes assignments already made._ No feature proposes, ranks, or routes work to people.           |
| **Evaluating performance**                  | No scoring, ranking, or comparative measurement anywhere (B.2.2, file 01 §2). Narrative description of activity, not assessment of a person.     |
| **Monitoring behaviour**                    | Symmetrical visibility, granular opt-in, employee-owned records — team coordination visible to the team, not covert observation reported upward. |
| **Informing employment decisions**          | Informational only. No automation or recommendation of promotion, pay, disciplinary, or termination decisions.                                   |

**These four properties are load-bearing regulatory architecture, not ethical preferences.** Any future feature scoring individuals, ranking contribution, or recommending personnel action would not merely violate B.2 — it could reclassify the product as high-risk, triggering conformity assessment, bias testing, technical documentation, and continuous monitoring obligations. **This is a hard product boundary with financial consequences.**

### B.3.4 Provider versus deployer — must be contractual

A _customer_ could misuse CAIRN's output — using contribution summaries to justify termination. Under the AI Act that customer acts as a **deployer**, carrying its own obligations.

CAIRN cannot fully prevent misuse, but must:

- **Prohibit it contractually** — terms of service explicitly forbid using CAIRN output as a basis for employment, disciplinary, or compensation decisions.
- **State it in-product** — the Trust & Privacy Center says so plainly, so employees know the commitment exists and can hold their employer to it.
- **Avoid enabling it** — no export, report, or view designed to support individual performance comparison.

This converts liability into a trust asset: **CAIRN is the tool that refuses to be used against you.**

### B.3.5 Worker notification

Where high-risk AI is deployed at work, employers must inform workers and representatives _before_ deployment. CAIRN adopts this regardless of classification: **no person's activity is captured until they have been notified**, enforced at the data layer rather than left to customer diligence.

## B.4 Per-company configuration

Each tenant configures its own profile at setup, revisable anytime: sources connected; retention period (default 12 months); whether chat is summarized or excluded (file 02 §8); and who views which categories — subject to B.2(1), visibility may be widened, never narrowed below the floor that every person sees their own record.

## B.5 Per-country defaults

Applied automatically from registered address at signup, with admin review and override.

| Region             | Defaults                                                                                                                                                                         |
| ------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **European Union** | Legitimate-interest basis with LIA (B.2.1); GDPR Articles 15 and 17; EU data residency; B.3.3 constraints enforced; worker notification; **EAA/WCAG 2.1 AA accessibility (A.6)** |
| **Germany**        | Works-council co-determination awareness (§87(1) no. 6 BetrVG) — rollout flags where engagement is likely required                                                               |
| **United States**  | State privacy law awareness (CCPA/CPRA, BIPA). **Meeting recording follows all-party consent universally** (file 03 §3.4)                                                        |
| **All regions**    | Worker notification before first capture. No exceptions.                                                                                                                         |

## B.6 The Trust & Privacy Center

A permanent, visible in-product page — not a policy PDF — showing any team member in plain language: what is tracked, why, who can see it, how to disable it, and **what CAIRN contractually refuses to do with it** (B.3.4).

Two audiences, identical content: employees deciding whether to trust it daily, and buyers evaluating it. This is also the primary artifact in enterprise AI-governance review, which increasingly gates B2B purchases regardless of regulatory deadlines.

## B.7 Cross-pillar compliance checklist

Every pillar satisfies this before shipping:

- [ ] Off by default; granular opt-in required.
- [ ] Individual can view and correct their own record, with correction effortless (A.3).
- [ ] No comparative score or ranking between people.
- [ ] Region defaults applied at the data layer, not per-feature judgment.
- [ ] Worker notification before first capture.
- [ ] Certainty tier and provenance present on uncertain claims (A.2).
- [ ] No feature allocates work, evaluates performance, or informs employment decisions (B.3.3).
- [ ] **WCAG 2.1 AA conformance verified (A.6).**

---

## Decisions requested from founder

1. **Accessibility as a v1 requirement (§A.6) — new and time-sensitive.** The EAA has been in force since June 2025, applies to non-EU companies serving EU customers, names SaaS explicitly, and carries market-access restriction as a penalty. Confirm WCAG 2.1 AA as a baseline from first release rather than a later retrofit. _Recommendation: confirm — this is currently an unaddressed legal exposure._
2. **The four design properties in B.3.3 as a hard boundary** — confirm these are permanent constraints with regulatory and financial consequences, not values tradeable later for a customer requesting individual scoring. _The most consequential confirmation in this document._
3. **Categorical, never numeric certainty (§A.2.1)** — confirm the interface never displays confidence percentages, using visual and linguistic tiers instead.
4. **Regulatory corrections (§B.2.1, §B.3.1)** — acknowledge legitimate interest as the EU basis, and the AI Act deadline moving to December 2027.
5. **Contractual prohibition on employment-decision use (§B.3.4)** — confirm this enters terms of service and is stated publicly in-product.
6. **Region defaults** — automatic from company address with admin override. _Recommendation: automatic with override._
7. **Trust & Privacy Center scope** — in-product only, or also published as sales and governance material. _Recommendation: both, identical content._
8. **Retention default** — confirm 12 months raw activity, adjustable per tenant.

---

_Once confirmed, this file moves to Locked and governs the folder; every pillar is verified against B.7 before finalization. Legal counsel review is required on Part B and on §A.6 before the first EU customer onboards — this document is a well-researched product position, not a legal opinion._
