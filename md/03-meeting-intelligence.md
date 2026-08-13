# Pillar 3 — Meeting Intelligence

**Status:** ✅ LOCKED — decisions resolved, ready for implementation
**Depends on:** [05-ux-design-privacy.md](05-ux-design-privacy.md) (consent is a hard legal gate), [09-understanding-layer.md](09-understanding-layer.md) (extraction and grounding), [02-chat-system.md](02-chat-system.md) (sequencing)
**Feeds into:** [04-auto-documentation.md](04-auto-documentation.md) (decision records)

**Founder's stated goal:** Meetings should be tracked, since decisions are made and work is often assigned verbally during them.

---

## 1. The competitive opening — everyone is good at transcription, nobody is good at what comes after

The AI notetaker market is crowded and mature: **Otter, Fireflies, Fathom, Read.ai, Granola**, plus free built-in transcription now shipping inside Zoom, Google Meet, and Microsoft Teams. On the surface this looks like a saturated category to avoid.

It is not, and the reason is a single finding that recurs across independent 2026 testing:

> _"Most tools are good at transcription, and almost none are good at what happens after transcription. Action items get captured but don't move anywhere. Summaries sit in a standalone app nobody returns to."_

**This is precisely the gap CAIRN occupies.** Every notetaker produces an artifact that terminates in its own application. CAIRN is not a notetaker — it is the system where a meeting's output _connects to everything else_:

| Notetaker output                                      | CAIRN output                                                                                                                      |
| ----------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| "Ali will fix the auth bug" — recorded in a notes app | The same commitment, then **tracked against the actual PR** that appears three days later in file 01 — or flagged when it doesn't |
| A decision, summarized                                | A decision that becomes an **Architecture Decision Record** in the repo (file 04)                                                 |
| A meeting summary in a separate tool                  | A meeting that appears **in the same daily brief** as code and chat activity                                                      |
| Standalone transcript archive                         | Meeting context available when someone later asks _"why did we build it this way?"_                                               |

The free built-in transcription in Meet, Zoom, and Teams reinforces this position rather than threatening it. Transcription is commoditizing toward zero, which means **transcription is not the product — the connection is.** CAIRN should consume free platform transcription wherever available rather than competing with it.

### 1.1 The bot backlash — market validation for the architecture

Independent testing reports that **customers and prospects increasingly notice meeting bots and react negatively.** Reviewers now rank tools partly by how intrusive their bot is, and **Granola — the bot-less option — is the general recommendation** specifically because it produces notes without sending a recorder into the room.

The no-bot decision in §4.2 was originally made on legal and scope grounds. Market evidence now independently validates it as a **product and trust advantage**, not merely a constraint.

### 1.2 A cautionary case worth knowing

**Brewer v. Otter.ai** — a class action filed in late 2025 and still pending — alleges unauthorized recording _and_ the use of customer meeting data for AI training.

Both allegations map to commitments CAIRN has already made: consent-gated capture (§3) and no customer data in training (file 09 §8). This is worth stating explicitly in sales conversations — the category's largest player is in active litigation over precisely the two things CAIRN contractually refuses to do.

---

## 2. The accuracy reality — why the confidence framework is mandatory

This pillar's technical constraints are not mild, and the numbers should be understood before any product promise is made.

| Measurement                                                        | Finding                                                                             |
| ------------------------------------------------------------------ | ----------------------------------------------------------------------------------- |
| Transcription accuracy with noise, accents, or non-English content | Drops to **60–70%**                                                                 |
| **Speaker misattribution in multi-person calls**                   | **~30%**                                                                            |
| Diarization error contribution                                     | Adds **11–13%** error on top of transcription                                       |
| Real-world benchmark (50 meetings)                                 | 6.3% word error rate, 0.71 ROUGE-L summarization, **85.4% F1 on action extraction** |

**The ~30% speaker misattribution figure is the most important number in this file.** CAIRN's core meeting output is _who committed to what_. If speaker labels are wrong roughly a third of the time in multi-person calls, then unqualified statements of the form "Ali agreed to ship Friday" would be wrong at an unacceptable rate.

This is not a reason to skip the pillar. It is the reason **every accuracy control in §6 is mandatory rather than advisable**, and why meeting-derived claims must be visually and linguistically distinguished from GitHub-derived facts (file 05 §A.2). A product that presents a 70%-reliable claim with 100% confidence destroys trust; a product that presents it _as_ a 70%-reliable claim with one-click verification is genuinely useful.

**Design implication:** audio quality is the dominant variable, and approaches that capture **separate per-speaker audio tracks materially outperform** diarization over a single mixed track. Where a platform exposes per-participant audio, CAIRN should prefer it — this is the single highest-leverage accuracy improvement available.

---

## 3. Recording consent — the legal gate

### 3.1 United States: a split map, strictest law governing

- **One-party consent (~38 states)** — only one participant must consent.
- **All-party consent** — every participant must consent: **California, Connecticut, Delaware, Florida, Illinois, Maryland, Massachusetts, Michigan, Montana, Nevada, New Hampshire, Pennsylvania, Washington.**

**In multi-state meetings, the strictest applicable law generally governs.** A Texas–California call requires all-party consent. Since CAIRN's customers are distributed teams, **the strict standard is the default case, not the exception.**

In all-party states, an employer **cannot unilaterally mandate AI recording** over an employee's objection. An administrative toggle is not a lawful substitute for individual consent.

### 3.2 AI bots carry unresolved legal classification

Courts may treat an AI bot joining a call as a recording device — or as an **unauthorized third-party interceptor**, a materially more serious characterization carrying wiretapping exposure. This remains unsettled, and is a direct argument for the architecture in §4.2.

### 3.3 European Union: consent is the wrong legal basis

GDPR requires informed consent for recording, **but consent is not a valid lawful basis in employment contexts** due to employer–employee power imbalance. The correct basis is **legitimate interest with a documented Legitimate Interest Assessment.**

> CAIRN's EU basis is legitimate interest with documented assessment. Opt-in controls keep that interest proportionate and defensible — they are not themselves the legal basis.

Flagged identically in file 02 §8.1 and file 05 §B.2.1.

### 3.4 Operating rule

**Default to the strictest standard universally: affirmative consent from every participant.** This satisfies every US regime simultaneously, matches documented best practice for multi-jurisdiction organizations, and aligns with file 05's trust posture. The cost of the strict default is low; the cost of error is criminal exposure in thirteen states.

---

## 4. Technical access and architecture

### 4.1 Google Meet constraints

| Constraint             | Detail                                                                                                                 | Consequence                                                                    |
| ---------------------- | ---------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| **Plan requirement**   | Recording and transcript access requires Workspace Business Standard, Enterprise, or Education Plus                    | A **qualifying question at onboarding**, not a support surprise later          |
| **Artifact storage**   | Meet's REST API does not serve recordings; artifacts live in Google Drive and are retrieved via the **Drive API**      | Additional permission scope the customer must approve                          |
| **Manual trigger**     | Someone must click Record, or no artifact exists                                                                       | CAIRN cannot silently capture — a constraint that doubles as a privacy feature |
| **Event notification** | Google Workspace Events API provides webhooks for meeting start/end, participant join/leave, and transcript generation | Enables event-driven ingestion consistent with file 01                         |

### 4.2 No meeting bot in v1 — four independent justifications

CAIRN does **not** join meetings as a participant. It ingests only artifacts the meeting platform itself produced under its own consent flow.

1. **Legal** — sidesteps the unresolved interceptor question (§3.2).
2. **Market** — bot backlash is documented and growing; bot-less is now a recommended-tool characteristic (§1.1).
3. **Trust** — a bot silently appearing in calls is the most surveillance-coded thing this product could do.
4. **Scope** — meeting-bot infrastructure is a substantial engineering domain; mature vendors (Recall.ai) exist because it is hard.

**Accepted trade, stated honestly:** CAIRN captures fewer meetings than bot-based competitors. It captures meetings the team already chose to record, and declines to expand that surface unilaterally. Given §1.1, this is increasingly a selling point rather than a limitation.

**Future option:** integrating an established bot vendor is a Year 2 build-vs-buy evaluation if customer demand justifies it — never a silent default.

### 4.3 Build boundary

CAIRN does not build video conferencing, and does not build a transcription engine. Platform transcription (increasingly free) is consumed where available; where only audio exists, transcription runs through a managed service with diarization (PyAnnote-based services are the current standard).

---

## 5. Functionality — what CAIRN actually does with a meeting

This section defines the pillar's feature surface. Every item exists because it connects meeting content to something outside the meeting — per §1, that connection _is_ the product.

### 5.1 Capture and understand

- **Decisions** — what was decided, with the reasoning that led to it.
- **Commitments** — who agreed to do what, by when (subject to §6's confidence handling).
- **Blockers** — impediments raised, and whether they were resolved in-meeting.
- **Open questions** — things left unresolved, which are the most commonly lost meeting output.
- **Attendance context** — who was present, and notably **who was absent when a decision affecting them was made**.

### 5.2 Connect — the differentiating layer

| Function                       | Behavior                                                                                                                                                                                                               |
| ------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Commitment tracking**        | A commitment made verbally is matched against subsequent activity in files 01 and 02. If a PR appears, the loop closes silently. If nothing appears by the stated date, it surfaces — not as an accusation, as a fact. |
| **Decision → documentation**   | Decisions flow to file 04 as ADR drafts, capturing _why_ alongside _what_.                                                                                                                                             |
| **Meeting → brief**            | Meeting content appears in the daily brief alongside code and chat, as one narrative rather than a separate summary.                                                                                                   |
| **Retrospective retrieval**    | "Why did we choose Postgres?" resolves to the meeting where it was decided, with a timestamp link.                                                                                                                     |
| **Cross-source deduplication** | A decision discussed in a meeting _and_ a chat thread resolves to one decision, not two (file 09 Stage 3).                                                                                                             |

### 5.3 Meeting hygiene — a natural, non-judgmental extension

Because CAIRN sees meetings alongside all other work, it can surface patterns that are useful and carry no evaluative weight about individuals: recurring meetings that consistently produce no decisions, decisions repeatedly revisited without resolution, and commitments that regularly outlive their stated dates.

**Boundary:** these are observations about _process_, never about _people_. No output ranks participants by contribution, talk time, or any comparative measure — that would violate file 05 §B.3.3 and is explicitly out of scope. This distinction matters, because several competitors do sell exactly that (Read.ai's analytics positioning), and CAIRN's refusal is deliberate.

### 5.4 Explicitly not built

- **No talk-time analysis, participation scoring, or sentiment analysis** of individuals (file 05 §B.3.3, file 09 §8).
- **No coaching or performance feedback** — the entire premise of the revenue-intelligence category (Gong, and Read.ai's analytics tier).
- **No standalone meeting archive product** — that is the commoditized layer competitors are stuck in (§1).

---

## 6. Accuracy controls — mandatory, given §2

Three controls, all required, all justified directly by the ~30% misattribution rate:

1. **Per-claim confidence**, surfaced in the interface rather than buried in metadata.
2. **One-click verification** — every claim links to its exact transcript timestamp, so confirmation takes seconds.
3. **Visual and linguistic distinction by source certainty** — meeting-derived claims never render with the same authority as a GitHub assignment.

**Framing rule:** meeting output is phrased as _observation_, not _record_. _"It sounded like Ali agreed to take the auth work"_ invites correction. _"Ali is assigned the auth work"_ asserts what the system cannot guarantee.

### 6.1 Correction as a designed moment

Given the error rates in §2, corrections are expected and frequent for this pillar. Per file 09 §7, each correction supersedes the AI-derived fact and becomes evaluation data (file 10 §2.1). **The pillar with the worst raw accuracy therefore generates the most valuable training signal** — provided correction is effortless. Making correction a one-tap action is a first-order design requirement here, not a settings-page afterthought.

---

## 7. Processing pipeline

1. **Detect** — Workspace Events API webhook signals transcript availability.
2. **Verify consent** — confirm §3 conditions _before_ ingestion. This gate precedes processing; it is never a post-hoc check.
3. **Retrieve** — fetch via Drive API (Meet) or platform equivalent.
4. **Transcribe** — where only audio exists, with diarization; prefer per-speaker tracks where available (§2).
5. **Understand** — extraction via the shared Understanding layer (file 09 Stage 2), with confidence assigned at creation.
6. **Resolve** — deduplicate against chat and code sources; apply temporal validity (file 09 Stage 3).
7. **Normalize** — emit `ActivityEvent` records with meeting metadata, per-claim confidence, and timestamp provenance.

---

## 8. v1 scope

| Decision      | Scope                                                                                                                        |
| ------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| Platforms     | **Google Meet and Zoom** — Meet matches the Workspace-based target customer; Zoom is prevalent even among Meet-primary teams |
| Capture       | Artifact ingestion only; no participant bot (§4.2)                                                                           |
| Consent       | Affirmative all-participant consent, universally (§3.4)                                                                      |
| Opt-in        | Per meeting or per calendar — never a blanket toggle                                                                         |
| Transcription | Platform-provided where available; managed service with diarization otherwise                                                |
| Deferred      | Microsoft Teams, pending a Microsoft 365 customer segment                                                                    |

---

## 9. Sequencing

Built after files 01 and 02 are stable. This is deliberate: the pillar is simultaneously the most technically difficult (§2) and the least forgiving of error, and it benefits from the Understanding layer having been validated first against cleaner sources where mistakes are cheap.

---

## Decisions requested from founder

1. **Consent standard** — confirm affirmative consent from every participant regardless of jurisdiction (§3.4). _Recommendation: confirm._ Jurisdiction-detecting logic is fragile and errors carry criminal exposure in thirteen states.
2. **No meeting bot** (§4.2) — confirm artifact-only capture, accepting reduced coverage. _Recommendation: confirm_ — now supported by market evidence (§1.1), not only legal caution.
3. **Positioning** (§1) — confirm CAIRN is positioned as _the system where meeting outcomes connect to real work_, explicitly not as a notetaker competing with Otter or Fireflies. This should shape marketing language directly.
4. **Accuracy transparency** — confirm that meeting-derived claims are visibly marked as lower-certainty, accepting that this makes demos look less magical than competitors who show unqualified confidence. _Recommendation: confirm._ Given ~30% misattribution, unqualified confidence is not a demo advantage — it is a delayed trust failure.
5. **Workspace plan qualification** (§4.1) — confirm Google Workspace tier is a qualifying question at onboarding.
6. **Onboarding behavior** — should CAIRN prompt teams to enable transcription in their existing tool? _Recommendation: prompt, never enable silently._
7. **GDPR correction** (§3.3) — acknowledge file 05 requires updating: EU basis is legitimate interest, not consent.

---

_Sections 2 (accuracy reality), 3 (consent law), and 6 (accuracy controls) define the boundary within which every other choice in this pillar operates. Where this file appears to conflict with file 05, file 05 governs — except §3.3, which corrects it._
