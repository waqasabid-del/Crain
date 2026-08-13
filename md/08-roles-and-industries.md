# Users, Adoption & Competitive Landscape

**Status:** ✅ LOCKED — pricing (Part E) deferred, revisit before beta
**Depends on:** [00-overview.md](00-overview.md)
**Feeds into:** [05-ux-design-privacy.md](05-ux-design-privacy.md) §A.5 (role-based design), all pillar files (positioning)

**Purpose:** Who uses CAIRN, how it actually gets adopted, who competes, and which industries come next.

---

# Part A — Roles

Five roles use CAIRN, each with a different relationship to the same data. **Each also plays a different part in whether the product gets adopted at all** — which matters more than feature preference.

### A.1 Founder / Owner / Team Lead — the buyer

**Needs:** An honest plain-English picture — what shipped, what stalled, what needs their decision.
**Adoption role:** **Champion and decision-maker**, usually the same person at 5–20 people. This is unusually favorable: no separate approval chain.
**Risk:** Buys enthusiastically, then finds the team resents it. A founder-driven rollout the team dislikes fails quietly.

### A.2 Developer / Engineer — the potential blocker

**Needs:** No manual reporting; documentation without effort; no sense of being watched or scored.
**Adoption role:** **The most likely blocker in the entire product.** Engineers are well-practised at rejecting tools that feel like surveillance, and their objection carries weight with a technical founder.
**Why this matters:** file 05's symmetrical visibility and no-scoring commitments are **adoption engineering**, not only ethics. They are how the product survives the developer's first reaction.

### A.3 Product Manager — the most primed adopter

**Needs:** Cross-cutting visibility tying code, chat, and meetings to specific initiatives.
**Market readiness:** PM adoption of AI has nearly doubled since 2024 — **73% now use AI daily** for roadmap tracking, decision documentation, and reducing status-meeting overhead.
**Adoption role:** Strong internal champion where the role exists — though by definition many target teams have no PM, which is precisely why they need CAIRN.

### A.4 Designer — the invisible-work risk

**Needs:** Visibility for work that never appears in GitHub — Figma, whiteboards, reviews, conversation.
**Adoption role:** **Silent opponent if handled badly.** In a small mixed team, a designer who experiences CAIRN as making engineers visible and themselves invisible becomes a persistent internal critic. This is a real adoption risk, not just a fairness concern.

**Figma timing — [DECIDED: Year 2, with mitigation shipped in v1]**

Figma integration waits for Year 2 or genuine customer demand. The risk is addressed instead through three v1 requirements, which are cheaper and — importantly — solve the problem more completely than a Figma connector would:

1. **Design contribution surfaced from chat and meetings.** Most design work is _visible in discussion_ long before it appears in a file: critique, direction-setting, decisions about what to build. Files 02 and 03 already capture this. A Figma connector would show file edits; conversation shows judgment, which is the more valuable signal anyway.
2. **The designer's own first view weights non-code contribution equally with commits** (file 11 §6) — reviews, decisions, and discussion rendered with the same visual weight as a merged PR.
3. **Explicit contribution-type coverage** in My Week, so a designer sees their week described in terms that reflect what they actually did.

**Reasoning:** the adoption risk is _feeling unseen_, not _lacking a Figma integration_. Mitigation 1 addresses the real cause. A Figma connector added while designers still feel their judgment is invisible would not fix the problem; the mitigations without Figma largely would. **Revisit when a customer asks by name.**

### A.5 Marketing / Sales / Ops — the breadth case

**Needs:** No technical fluency required to read or trust it.
**Market readiness:** **69% positive sentiment toward AI**, roughly **6 hours saved per week**, largely on automated summaries.
**Adoption role:** Expansion. These roles justify seats beyond the engineering team and are the bridge to the non-software verticals in Part D.

### A.6 The design conclusion

All five need **the same data through different lenses** — independently confirming the single shared Understanding layer (file 00 §6). Separate per-role products would cost more and cohere less.

---

# Part B — How CAIRN actually gets adopted

## B.1 The market context

| Signal                                                                 | Figure                                              |
| ---------------------------------------------------------------------- | --------------------------------------------------- |
| New subscriber activations from free trials                            | **61%**                                             |
| ARR from trial-initiated customers retaining 12+ months (top quartile) | **38%**                                             |
| B2B SaaS companies running a PLG motion                                | **58%**, of which **91%** are increasing investment |

The dominant 2026 pattern is **hybrid Product-Led Sales**: self-serve acquisition funnels high-intent users to a sales motion focused on expansion.

## B.2 CAIRN sits in the PLG price band

Pure PLG works for products with **$0–30/user/month pricing, individual or small-team adoption, and no compliance complexity.** CAIRN's $12/user Team tier and 5–20 person target sit squarely inside the first two criteria.

## B.3 The tension — two structural deviations from classic PLG

**This is the finding that requires a decision.**

**Deviation 1: CAIRN has significant compliance complexity.** The criteria above specify _no compliance complexity_ — but CAIRN requires worker notification before capture, per-person consent controls, region-specific legal defaults, and (for EU customers) a documented Legitimate Interest Assessment (file 05). These are not optional; they are what keeps the product outside AI Act high-risk classification and what makes it trustworthy. **But they add friction precisely where PLG demands none.**

**Deviation 2: CAIRN cannot deliver value to a single user.** The classic bottom-up path — _individual signs up → invites two teammates → team upgrades → department adopts_ — assumes an individual gets standalone value first. **CAIRN does not work that way.** A team-activity product needs the team connected before it produces anything useful. There is no meaningful single-player mode.

Both deviations point the same direction: **CAIRN's activation unit is the team, not the individual.**

## B.4 Implications

1. **Design the trial around a team, not a user.** The onboarding target is not "one person sees value in 30 minutes" but "a team of eight is connected and sees a useful brief within a week." Time-to-value (file 05 §A.1) should be measured at team level.
2. **Make consent and notification part of activation, not a barrier before it.** Worker notification is a legal requirement (file 05 §B.3.5). Handled well, it becomes the moment the team learns this is a tool _for_ them — the trust story delivered at exactly the right moment. Handled as a compliance form, it becomes the point where trials die.
3. **Founder-led sales for the first cohort is right** — matching the original proposal. With a compliance-complex, team-activated product, high-touch early onboarding is not a scaling failure; it is how the activation problem gets understood before it is automated.
4. **Expect the buying committee to stay small — protect that.** Committee research shows **each additional stakeholder adds 8–22 days of cycle time and 12–22% additional stall probability.** At 5–20 people the founder is usually champion and decision-maker at once. Every enterprise feature added prematurely (SSO requirements, procurement surfaces, security questionnaires) invites more stakeholders and slows the motion. **Moving upmarket is a deliberate later choice, not an accident to drift into.**

---

# Part C — Competitive landscape

Three distinct categories, not one. The original proposal identified only the first.

### C.1 Project management incumbents

Jira, Confluence, Linear, ClickUp, Monday.com, Asana, Notion, Trello, Atlassian Rovo.
**Shared weakness:** all require humans to maintain the picture manually; AI is layered onto manual-entry data models.

### C.2 Engineering intelligence platforms _(identified during specification)_

Swarmia, LinearB, Jellyfish, Waydev, DX, Uplevel, Allstacks. Detail in file 01 §1.

| Their characteristic                             | CAIRN's counter-position                                    |
| ------------------------------------------------ | ----------------------------------------------------------- |
| Dashboards and scores requiring metrics literacy | Plain-English narrative any of the five roles can read      |
| Sold _to management, about developers_           | Symmetrical visibility — the team sees what leadership sees |
| Engineering data only                            | Four sources in one picture                                 |

**Why they cannot copy it:** a platform whose entire value proposition is a management dashboard cannot adopt symmetrical visibility without abandoning its buyer. Structural, not a feature gap.

### C.3 Automatic-tracking tools — closest direct comparison

Stepsize AI, Gitmore, Jarvis, Slacktivity, GitHub for Slack.
**Shared limitation:** narrow — code and chat only, no meetings or documentation, and none address non-technical roles. The category validates the thesis while leaving the full scope open.

### C.4 Adjacent categories

- **AI documentation** — Mintlify, GitBook, Fern, ReadMe (file 04 §1). They generate from code; CAIRN generates from code _plus the human context explaining it_.
- **Meeting notetakers** — Otter, Fireflies, Fathom, Granola, Read.ai (file 03 §1). All strong at transcription, all terminate in their own app.

### C.5 The honest summary

No competitor occupies CAIRN's full scope, but **CAIRN faces credible competition on every individual pillar.** It does not win by beating each category at its specialty — it wins on **integration across four sources plus a trust posture the dashboard vendors structurally cannot adopt.** Parity per pillar is the entry requirement; the combination is the product.

---

# Part D — Industries beyond software

The founder's instinct that large vendors neglect small business is supported:

- **Nearly half of small businesses use some AI tool**, but most rely on **generic rather than purpose-built solutions** — actively underserved and currently searching.
- **63% of professional services firms have no firm-wide AI strategy**; only 18% track AI ROI.

### D.1 Marketing and creative agencies — the strongest Year 2 fit

The operational numbers are compelling:

| Finding                                                          | Figure                                                                                  |
| ---------------------------------------------------------------- | --------------------------------------------------------------------------------------- |
| Account manager time on **manual client reports**                | **4–7 hours per week** — the single largest non-billable time sink in agency operations |
| Client retention with live dashboards vs. static monthly reports | **34% longer**                                                                          |
| Status of the monthly PDF report                                 | _"A retention risk, not a value signal"_                                                |

**This is close to a perfect fit.** CAIRN's core capability — generating an honest status narrative automatically from actual work — directly attacks the largest non-billable cost in the agency model, and the retention data quantifies the upside. Documented pain points (approval delays, lack of visibility, spreadsheet overload, communication scattered across email and WhatsApp) map onto CAIRN's four pillars almost exactly.

**The required addition is a client-facing view** — already noted as a Year 2 roadmap item. Agencies need to show clients a live picture, not just see it internally.

### D.2 Consulting and professional services

Parallel engagements where the work happens in meetings and documents rather than code. **Pillars 3 and 4 matter more here than for software teams** — these firms have no GitHub-equivalent system of record; conversation _is_ the work product.

### D.3 Real estate and sales-driven small business

Existing tools already turn calls and notes into structured documents — pillars 3 and 4 applied to deals rather than code.

### D.4 The common thread

Small distributed teams with no dedicated project manager, in any industry.

### D.5 Roadmap implication

**v1 stays software-focused.** The architecture already generalizes — Understanding and Surface layers barely change; only Capture needs new connectors, which is exactly what file 07's MCP support makes affordable. **This is a market-expansion decision, not a technical rebuild.**

### D.6 Geographic sequence — **[DECIDED]**

**United States first → Tier 1 English-speaking markets (UK, Canada, Australia, Singapore) → Tier 2 thereafter.**

This matches the original proposal's ranking by willingness to pay and timezone workability, and it has a direct infrastructure consequence: **EU market entry is deliberately deferred**, which defers EU data residency, its ~10% AI cost premium, and the associated compliance workload (file 06 §6.1). Signups are geo-gated to supported markets initially so that EU obligations attach by choice rather than by accident (file 06 §6.2).

---

# Part E — Pricing & seat model _(PROVISIONAL — to be revisited)_

**Status: placeholder.** The founder has deferred this decision. What follows is a working assumption so that dependent files (unit economics in file 09 §7.4, activation design in file 11) have something concrete to reference. **It is expected to change and should not be treated as settled.**

### E.1 The structural tension to resolve later

CAIRN has **no single-player mode** (§B.3) — value requires the whole team connected. **Per-user pricing therefore creates a financial disincentive to connect the whole team**, working directly against the product's own activation requirement. A founder weighing "$12 × 15 people" has a real reason to connect only engineers, which is exactly the outcome that causes activation to fail.

This tension is unusual and worth solving deliberately rather than defaulting to per-seat pricing because it is conventional.

### E.2 Provisional working assumption

**Flat team pricing** — a single price per team band rather than per seat:

| Band     | Team size | Indicative price |
| -------- | --------- | ---------------- |
| Free     | Up to 5   | $0               |
| Team     | Up to 15  | ~$99/month       |
| Team+    | Up to 30  | ~$199/month      |
| Business | 30+       | Custom           |

**Why this is the provisional default:**

- Removes any reason to leave someone out — directly serving team activation.
- Eliminates the "user-tier rounding" complaint identified in the original Jira analysis, where a 12-person team pays for 25 seats.
- Simple to understand, which serves the non-technical buyer.

**Known trade-off:** less automatic revenue expansion as a team grows, and pricing bands create their own cliff effects at the boundaries.

### E.3 Alternatives to weigh when this is revisited

- **Full seats plus discounted viewer seats** — standard SaaS, preserves expansion revenue, but creates two user classes which sits awkwardly against the symmetrical-visibility commitment (file 05 §B.2).
- **Uniform per-user pricing** — simplest and most aligned with symmetry, but carries the §E.1 disincentive at full strength.

### E.4 Open question for the revisit

Should the five roles in Part A map to differentiated access tiers at all, or should every team member have identical access regardless of role? This interacts directly with file 05's symmetry commitment and should be decided deliberately.

---

## Decisions

### Resolved

| Decision                       | Outcome                                                                                                                                                                         |
| ------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Figma timing** (§A.4)        | **Year 2 or on customer request**, with three v1 mitigations shipped instead — design contribution surfaced from chat and meetings, weighted equally in the designer's own view |
| **Geographic sequence** (§D.6) | **US → Tier 1 English-speaking → Tier 2.** EU entry deliberately deferred; signups geo-gated initially                                                                          |
| **Pricing model** (Part E)     | **Deferred by founder.** Flat team pricing recorded as the provisional working assumption                                                                                       |

### Still open

1. **Team-level activation (§B.3–B.4) — the significant one.** Confirm the activation unit is the team, not the individual, and that time-to-value is measured at team level. This changes onboarding design, trial structure, and the success metrics in file 00 §3.
2. **Consent as an activation moment, not a barrier (§B.4.2)** — confirm that worker notification is designed as the moment the team learns CAIRN is _for_ them.
3. **Protect the small buying committee (§B.4.4)** — confirm that moving upmarket is a deliberate later decision, accepting that premature enterprise features invite stakeholders who each add 8–22 days and meaningful stall risk.
4. **Agency vertical as named Year 2 target (§D.1)** — confirm, given the 4–7 hours/week non-billable reporting cost and the 34% retention improvement from live client visibility. Also confirm the client-facing view as the enabling feature.
5. **Competitive framing (§C.5)** — confirm the strategy is integration-plus-trust rather than beating any single category, and that this carries into marketing.
6. **Pricing revisit (Part E)** — schedule this before beta launch. The §E.1 tension between per-user pricing and team activation should be resolved deliberately, not defaulted.

---

_§B.3 is the most consequential section here: CAIRN sits in the PLG price band but deviates from the PLG model in two structural ways. Recognizing that early shapes onboarding, trial design, and metrics — recognizing it late looks like an activation problem with no obvious cause._
