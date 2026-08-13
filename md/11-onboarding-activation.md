# Onboarding & Activation

**Status:** ✅ LOCKED — decisions resolved, ready for implementation
**Depends on:** [08-roles-and-industries.md](08-roles-and-industries.md) §B (team-level activation), [05-ux-design-privacy.md](05-ux-design-privacy.md) (consent, design), [01](01-github-integration.md)–[03](03-meeting-intelligence.md) (connection flows)

**Why this file exists:** File 05 promises value in under 30 minutes. File 08 established that CAIRN's activation unit is the **team, not the individual**. Neither specifies the actual flow. This is where trials succeed or die, and it was the largest unspecified risk in the product.

---

## 1. The activation problem, stated honestly

### 1.1 Industry baseline

| Benchmark                                     | Figure              |
| --------------------------------------------- | ------------------- |
| Trial users who successfully activate         | **36–38%**          |
| Users who complete multi-step product tours   | **5%**              |
| Activation rate achieved by strong onboarding | **40–60%**          |
| Churn reduction from strong onboarding        | **20–50%**          |
| Time-to-value target, top performers          | **Under 5 minutes** |
| Step count before completion drops 30–50%     | **Over 20 steps**   |

**Two findings reshape CAIRN's approach immediately:**

**Only 5% of users complete multi-step product tours.** A guided-tour onboarding is effectively dead on arrival. Onboarding must be _contextual_ — appearing inside the action the user is already trying to complete — not a walkthrough preceding use.

**Best-practice time-to-value is under 5 minutes**, against CAIRN's stated 30-minute target. CAIRN is not a 5-minute product — it requires OAuth to multiple systems and initial indexing. This gap must be managed deliberately (§3), not wished away.

### 1.2 CAIRN's structural difference

Per file 08 §B.3, CAIRN deviates from standard SaaS activation in two ways:

1. **No single-player mode.** A team-activity product produces nothing useful from one connected person.
2. **Compliance is on the activation path.** Worker notification is legally required _before capture_ (file 05 §B.3.5) — it cannot be deferred to later.

**Consequence:** CAIRN has two distinct activation events, and conflating them is the classic mistake.

---

## 2. Defining activation

The standard test: _"A new user is activated when they \___"_ must be answerable with a specific, measurable action. CAIRN needs two answers.

| Level                     | Definition                                                                                                                                                                  | Target                       |
| ------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------- |
| **Individual activation** | The founder has connected GitHub and seen real activity from their own repository rendered in CAIRN                                                                         | **< 10 minutes** from signup |
| **Team activation**       | ≥ 60% of the team has been notified and not opted out, ≥ 2 sources are connected, and the team has received its **first Founder Brief containing genuinely useful content** | **< 7 days** from signup     |

**Team activation is the metric that matters.** Individual activation is a leading indicator — necessary, insufficient, and dangerous to optimize alone, because a founder who activates individually and then fails to bring the team churns while the dashboard reports success.

**Success metric implication:** file 00 §3 should measure activation at team level. Flagged for that file.

---

## 3. The first ten minutes — individual activation

The goal is a single moment: **the founder sees CAIRN describe their own real work, accurately.** Nothing else in the first session matters as much.

### 3.1 Flow (5 steps, well inside the 3–7 guidance)

1. **Sign up** — email or Google/GitHub SSO. No credit card.
2. **Connect GitHub** — install the GitHub App (file 01 §2), select repositories. Per-repo selection is the consent model _and_ the scoping mechanism.
3. **Backfill begins** — 90 days pulled in the background (file 01 §7).
4. **Show something immediately** — as events land, they render live. **The screen is never empty.**
5. **First personal summary** — a narrative of the last week's activity in that repository.

### 3.2 The empty-state problem is the whole problem

Every activity product faces the same trap: on day one there is nothing to show, so the product looks broken precisely when the user is deciding whether it works.

**Three mitigations:**

- **90-day backfill** (file 01 §7) exists specifically for this. GitHub's rate limits permit it; this is why the ceiling matters.
- **Progressive rendering** — show events as they arrive rather than waiting for completion. A visibly filling screen reads as working; a spinner reads as broken.
- **Honest partial state** — "Analyzing 340 commits from the last 90 days — here's what's landed so far" is better than a loading screen and better than a fabricated summary.

### 3.3 What is deliberately _not_ in the first ten minutes

Team invitations, chat connection, meeting setup, documentation configuration. **One connected source, one real output, one moment of belief.** Everything else follows.

---

## 4. The first week — team activation

This is where CAIRN wins or loses, and where the compliance requirement becomes either the best or worst moment in the product.

### 4.1 Worker notification as the pivotal moment

Worker notification is legally mandatory (file 05 §B.3.5). It is also the moment every team member forms their opinion of CAIRN.

**The framing decision matters enormously:**

| Handled as                                                                                                                                                      | Result                                                                                                      |
| --------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| A compliance notice — _"Your employer has enabled activity monitoring"_                                                                                         | The team reads it as surveillance. Adoption dies quietly; the developer becomes the blocker (file 08 §A.2). |
| **An invitation with a promise** — _"CAIRN writes your week for you. Here's exactly what it can see, here's what it will never do, and you control all of it."_ | The trust story arrives at the perfect moment, from the product itself rather than from the founder.        |

**Requirements for the notification:**

- Sent to each person individually before _any_ of their activity is captured.
- States plainly what is tracked, what is not, and who can see it (file 05 §B.6).
- States what CAIRN contractually refuses to do — no scoring, no ranking, no employment decisions (file 05 §B.3.4).
- Offers per-source opt-out **in the notification itself**, not buried in settings.
- Shows the person their own record first — before anyone else sees anything about them.

**The strongest single trust signal available:** the first thing a team member sees is _their own contribution record_, and the first action available is _correcting it_. That single sequence communicates "this is yours" more effectively than any amount of policy copy.

### 4.2 Second source connection

Chat (file 02) is the natural second source — highest signal density and it makes the brief markedly better. Prompted after GitHub is producing value, never during initial setup.

**Set expectations honestly:** file 02 §3.2 means Slack history backfill is severely constrained. Onboarding should say so — _"Chat tracking starts now; we can't retrieve your history"_ — rather than let the user discover a gap and conclude the product is broken.

### 4.3 The first Founder Brief

The product's central artifact should arrive when it has enough to be genuinely good — not on a fixed schedule. A thin first brief does more damage than a delayed one.

**Gate:** the first brief sends only when it clears a substance threshold. Until then, the founder sees the live feed and a clear note on what is still needed.

---

## 5. Contextual guidance, not tours

Given the 5% tour-completion figure, CAIRN uses **contextual assistance appearing inside the action the user is already taking**:

- Connecting a second source is suggested when the brief would visibly improve from it — with the reason stated.
- Meeting setup is offered when calendar activity indicates recurring meetings exist.
- Documentation generation is offered when a repository with a thin README is detected.

**Each prompt names the concrete benefit**, never the feature. _"Your brief is missing what the team discussed — connect Slack"_ rather than _"Enable chat integration."_

---

## 6. Onboarding for the four non-founder roles

Per file 08 Part A, four other roles arrive through the notification in §4.1 — never through signup. Each needs a different first screen:

| Role                | First view                                                                            | First action                   |
| ------------------- | ------------------------------------------------------------------------------------- | ------------------------------ |
| **Developer**       | Their own contribution record from GitHub                                             | Correct anything wrong         |
| **Designer**        | Their contributions including reviews and discussion, **explicitly not just commits** | Correct anything missing       |
| **Product Manager** | Cross-source view of a live initiative                                                | Follow a project               |
| **Marketing / Ops** | The plain-English team brief                                                          | Nothing — reading is the value |

**Design requirement:** the developer and designer views must survive first contact with a sceptical person. This is the adoption moment file 08 §A.2 and §A.4 identify as the highest-risk in the product.

---

## 7. Measurement

| Metric                        | Target                | Purpose                                                                  |
| ----------------------------- | --------------------- | ------------------------------------------------------------------------ |
| Individual activation rate    | > 50%                 | Signup → first real output seen                                          |
| Time to individual activation | < 10 min              | Leading indicator                                                        |
| **Team activation rate**      | **> 40%**             | The metric that matters — matches strong-onboarding benchmark            |
| Time to team activation       | < 7 days              | Full-value delivery                                                      |
| Notification opt-out rate     | **< 10%**             | **The trust barometer** — a rise means the framing in §4.1 is failing    |
| Day-7 / Day-30 retention      | Per file 00 §3        | Habit formation                                                          |
| Correction rate in week one   | Tracked, not targeted | High is fine and healthy; _zero_ means nobody trusts it enough to engage |

**The opt-out rate is the most diagnostic metric here.** It measures directly whether the "visibility, not surveillance" positioning is landing with the people it must land with.

---

## 8. Failure modes to design against

| Failure                                   | Cause                                     | Mitigation            |
| ----------------------------------------- | ----------------------------------------- | --------------------- |
| Founder activates alone, team never joins | Notification framed as compliance         | §4.1                  |
| Empty first session                       | No backfill, blocking load                | §3.2                  |
| Thin first brief                          | Sent on schedule rather than on substance | §4.3                  |
| Developer opts out and influences others  | Feels monitored                           | §6, plus file 05 §B.2 |
| Designer feels invisible                  | Code-centric first view                   | §6                    |
| User expects Slack history and finds none | Unstated limitation                       | §4.2                  |

---

## Decisions requested from founder

1. **Two-level activation (§2)** — confirm team activation is the primary metric and individual activation is a leading indicator only, and that file 00 §3's metrics update accordingly.
2. **Worker notification framing (§4.1) — the most consequential decision here.** Confirm the notification is designed as an invitation carrying the trust promise, with per-source opt-out offered inline and the person's own record shown first.
3. **Substance-gated first brief (§4.3)** — confirm the first brief waits until it is genuinely good rather than sending on schedule.
4. **Contextual guidance over tours (§5)** — confirm, given only 5% complete multi-step tours.
5. **Honest limitation disclosure (§4.2)** — confirm onboarding states the Slack history constraint plainly rather than letting users discover it.
6. **Opt-out rate as a tracked trust metric (§7)** — confirm < 10% as the target and as an early-warning signal on positioning.

---

_§4.1 is the highest-leverage design decision in the entire product. Worker notification is legally required, arrives before anyone has formed an opinion, and reaches every future user simultaneously. Handled well it is the best marketing CAIRN will ever do; handled poorly it is where every trial quietly dies._
