# Pillar 2 — Chat & Communication Intelligence

**Status:** ✅ LOCKED — core architecture decided (§2.4, §4.1, §6); minor items in §10
**Depends on:** [05-ux-design-privacy.md](05-ux-design-privacy.md) (most sensitive data source), [00-overview.md](00-overview.md) §6
**Feeds into:** [04-auto-documentation.md](04-auto-documentation.md) (decisions become records), [07-mcp-integration.md](07-mcp-integration.md)

**Founder's stated goal:** A native chat inside CAIRN with all discussion tracked automatically — _and_ the ability to connect whatever chat app a team already uses, so they keep working where they are while everything stays tracked in CAIRN.

---

## 1. The strategic reframe — CAIRN does not need to beat Slack at chat

This is the most important insight in this file, and it changes what "winning" means for this pillar.

Research into what users actually complain about in Slack and Microsoft Teams produces a consistent list — and every item on it is a problem CAIRN already solves, none of which is a chat feature:

| Documented complaint                                                           | Platform                       | What it actually is                                 |
| ------------------------------------------------------------------------------ | ------------------------------ | --------------------------------------------------- |
| **"Important information gets buried in busy channels"**                       | Slack                          | An _understanding_ problem, not a messaging problem |
| **Notification overload** — a near-universal complaint                         | Slack                          | A _filtering and synthesis_ problem                 |
| **Search is weak** — "finding older messages or files is not always intuitive" | Both (Teams slower than Slack) | A _retrieval and comprehension_ problem             |
| **Interface complexity** — cluttered tabs, deep navigation hierarchies         | Teams                          | A _design_ problem                                  |
| **Resource-heavy client**, slows down during meetings                          | Slack                          | An _engineering_ problem                            |
| **High per-user cost**; Pro/Enterprise Grid jumps are significant              | Slack                          | A _pricing_ problem                                 |

**The conclusion:** Slack and Teams are excellent at message delivery and poor at everything that happens _after_ the message is delivered. Their weaknesses are precisely CAIRN's core competency.

This reframes the native-chat question entirely:

> CAIRN's chat would not compete on message delivery, threading, or presence — table stakes it would take years to match. It would compete on **never burying anything, never requiring search, and never demanding that anyone monitor a channel to stay informed.** That is a different product category, and the incumbents' own users are already describing the gap.

A chat client that is 80% of Slack's messaging quality but eliminates notification overload and buried context is not a worse Slack. It is the thing Slack users are complaining they want.

**This strengthens the founder's original instinct** — but it does not resolve the sequencing question, because the adoption barrier (§4) and the integration constraints (§3) remain real.

---

## 2. Interoperability — "connect whatever they use, stay tracked in CAIRN"

The founder's requirement is explicit: teams should be able to keep using their existing chat app, while CAIRN remains the system of record. This is the correct instinct — it removes the migration barrier entirely — and it has a real technical answer.

### 2.1 Three levels of connection

| Level                            | What it means                                                                                        | Effort           | Coverage                                       |
| -------------------------------- | ---------------------------------------------------------------------------------------------------- | ---------------- | ---------------------------------------------- |
| **Level 1 — Read-only tracking** | CAIRN ingests messages via each platform's API. Users notice nothing.                                | Low per platform | Constrained by each platform's API limits (§3) |
| **Level 2 — Bridged**            | Messages flow _both ways_. A CAIRN user and a Slack user talk to each other, each in their own tool. | High             | Full participation without migration           |
| **Level 3 — Native**             | The team uses CAIRN chat directly.                                                                   | Highest (build)  | Complete, structured, no API dependency        |

**Level 2 is what the founder is describing**, and it is the genuinely differentiating option: nobody migrates, everybody participates, everything is tracked.

### 2.2 The Matrix protocol — the established path to Level 2

Bridging is a solved problem with mature open infrastructure. **Matrix** is an open protocol with persistent history, native end-to-end encryption, and **bridges to over 40 protocols** — including Slack, Microsoft Teams, Discord, Telegram, Signal, IRC, and XMPP. The bridge model works exactly as the founder describes: _a room connected to a Slack channel, where every message posted on one side appears on the other, so everyone uses their preferred tool while communicating together._

Credibility signals are strong:

- **The European Commission is building its internal communications on Matrix**, evaluating it as the foundation for secure, interoperable communication across the institution.
- **Element** offers commercial Microsoft Teams bridging, proving the enterprise model works.
- The EU Digital Markets Act requires messaging interoperability from gatekeepers — no standard has been mandated as of May 2026, but regulatory momentum favors open interoperability, which is a tailwind for this approach.

### 2.3 The honest cost of bridging

Bridges are not free, and this should be understood before committing:

- **Operational burden.** Running Matrix homeserver infrastructure plus bridge services is real ongoing work — a meaningful addition to the platform squad's scope.
- **Fidelity loss.** Bridges rarely map features perfectly. Threads, reactions, formatting, edits, and file handling differ per platform, and bridged conversations can feel subtly degraded on one side.
- **The maintenance treadmill.** This is the documented failure mode of the entire aggregator category: platforms change APIs and authentication constantly, and each has unique auth flows, data structures, rate limits, webhook formats, and pagination cursors. Aggregators live or die on absorbing this churn — **Texts.com was discontinued and folded into Beeper**, and the survivors treat integration maintenance as a permanent, staffed cost, not a one-time build.

### 2.4 Interoperability strategy — **[DECIDED]**

**Level 1 satisfies the founder's actual requirement.** The stated goal is _"people keep using their app, tracking happens in our system."_ That is read-only ingestion — not two-way message flow. Level 1 delivers it through each platform's API, at low cost, in Phase 1.

**Level 2 (two-way bridging) is reclassified as a nice-to-have, not a requirement.** It solves a different problem — a CAIRN user and a Slack user conversing across a bridge — which no customer has requested. Revisit only if genuine cross-organization federation demand emerges.

**Matrix is not adopted as the foundation.** An earlier draft of this file recommended Matrix specifically to inherit its 40+ protocol bridges. Since bridging is not the actual requirement, that justification does not hold, and Matrix's costs (§2.3) would be paid for a capability nobody asked for. The chosen foundation for native chat is specified in §4.1.

---

## 3. What integration actually costs — hard constraints

The assumption that integrating Slack is simple is only half true, and the qualifications are material.

### 3.1 Real-time capture works well

Slack's **Events API** pushes messages to a CAIRN endpoint in near-real-time without long-lived per-workspace connections. For ongoing tracking this is clean, well-supported, and correct.

### 3.2 Historical backfill is severely restricted

As of **May 29, 2025**, Slack moved `conversations.history` and `conversations.replies` to **Tier 1** for non-Marketplace apps created or installed after that date — approximately **one request per minute, capped at 15 objects per request.**

Backfilling one active channel's year of history could take hours; a full workspace is effectively impractical. **This undermines the day-one-populated-view goal** in file 01 §7 and file 05's sub-30-minute time-to-value target.

### 3.3 Compliance-grade access is gated

The **Slack Discovery API** — the interface supporting eDiscovery, DLP, and compliance archiving — is restricted to **approved partners** serving customers on **Enterprise Grid**, Slack's most expensive tier. CAIRN cannot assume access to it.

**Consequence:** the professional-grade compliance capabilities in §5 are **not achievable through Slack integration** for typical small-team customers. They are achievable only in CAIRN's own chat. This is a genuine, structural argument for native chat that the original analysis missed.

### 3.4 The strategic dependency

Tier 1 restrictions apply to non-Marketplace apps; Marketplace approval restores workable limits — converting an engineering task into a **third-party approval dependency on a Salesforce-owned competitor.**

- **Mitigation:** apply early; Marketplace listing is also a distribution channel (file 08).
- **Fallback:** design for value from real-time capture alone. A team connecting Monday gets a useful brief by Friday from that week alone.
- **Context:** Slack's June 2025 restructure pushed Business+ to $15/user/month — customers are already re-evaluating Slack spend, which cuts both ways.

---

## 4. Native chat — cost and foundation

Industry estimates put a production chat product at **$100K+ and multiple months** for teams without a dedicated bench — and that buys table stakes, not differentiation. The required surface is larger than it looks: delivery guarantees, threading, search, presence, notification routing across web/mobile/email, file handling, offline sync, read state across devices, and mobile apps.

### 4.1 Foundation decision — **[DECIDED: commercial chat SDK, not Matrix, not from scratch]**

The industry decision rule is clean and directly applicable:

> **If chat is a _feature_, ship on a commercial chat platform (Stream, Sendbird) and revisit at large scale. If chat is _the product_, plan a custom stack from day one and budget the operational tail.**

**For CAIRN, chat is emphatically a feature.** The product is the Understanding layer (file 09). Nobody will choose CAIRN because its message delivery is excellent — they will choose it because it understands their work. Engineering capacity spent on presence indicators and offline sync is capacity taken from the actual differentiator.

**Why not Matrix, despite its strengths.** Matrix is genuinely excellent, but its production sweet spot is not this:

- It is the right answer for **data sovereignty, cross-organization federation, and E2EE with no vendor in the trust path** — which is why adoption is concentrated in **35+ national governments, the UN, NATO, Space Force, the French government, and the German Bundeswehr.**
- Published guidance is explicit that **running a Matrix homeserver at scale is non-trivial and better suited to defence, public sector, or large multinationals than to SaaS chat.**
- A 10-person team should not be operating messaging infrastructure. Synapse is mature and capable, but it is a system to run, not a library to use.
- The primary reason Matrix was originally proposed here — inheriting 40+ bridges — **is no longer a requirement** (§2.4).

**Chosen approach: a commercial chat infrastructure platform**, with **Stream** as the leading candidate (strongest developer experience and pricing for SaaS at this stage) and Sendbird as the alternative if advanced moderation or compliance tooling becomes decisive.

### 4.2 Two consequences to manage

**Subprocessor exposure.** A commercial chat platform holds customer message content, which adds a subprocessor to CAIRN's data story — and CAIRN's differentiation _is_ its data story (file 05). Requirements: EU data residency support verified before selection, the vendor added to the DPA and named in the Trust & Privacy Center (file 05 §B.6), and file 05's handling rules applied to the vendor relationship.

**MAU-based pricing.** These platforms price per monthly active user. At B2B team scale this is predictable and modest; the model only becomes painful at consumer-social scale, which CAIRN will not reach. Verify against unit economics (file 09 §7.4) before committing.

### 4.3 When to revisit

Reconsider self-hosted Matrix only if one of two things becomes true: a sovereignty-sensitive customer (government, defence, regulated) requires no third party in the trust path, or genuine cross-organization federation becomes a customer requirement rather than a hypothetical.

### 4.4 The adoption barrier

Teams have years of history, habits, and integrations in Slack or Teams. Requiring migration as the price of entry contradicts the founder's win condition (file 00 §1). This is why Phase 1 tracks Slack rather than replacing it — native chat must earn migration over time, not demand it upfront (§6).

---

## 5. What makes it professional — the enterprise requirements

The founder's question — _what makes this professional enough that people use it_ — has a concrete answer beyond design quality. Buyers evaluating team communication tools assess a specific capability set, and its absence disqualifies a product from serious consideration regardless of how good the AI is.

| Capability               | Requirement                                                                                                                                                             | CAIRN status                                                                                            |
| ------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------- |
| **Data Loss Prevention** | Detect sensitive data — PII, PHI, PCI, credentials, **source code** — in real time, with remediation: redaction, tombstoning, deletion, file quarantine, channel blocks | Required for native chat. **Source-code detection is especially relevant** given CAIRN's customer base. |
| **eDiscovery**           | Search, hold, and export communication for litigation, regulatory inquiry, or internal investigation                                                                    | Required for native chat                                                                                |
| **Legal hold**           | Org-wide holds placed on specific users, channels, or date ranges, preventing deletion                                                                                  | Required for native chat                                                                                |
| **Retention policy**     | Per-workspace and per-channel: indefinite, fixed duration, or automatic deletion                                                                                        | Aligns with file 05 §B.4                                                                                |
| **Independent archive**  | A compliant archive must remain **accessible independent of the source platform** and of subscription changes                                                           | **CAIRN is inherently this** — see §5.1                                                                 |
| **Audit logging**        | Complete, attributable access records                                                                                                                                   | Already required by file 05 §B.2                                                                        |

### 5.1 An unexpected strategic asset

Compliance guidance is explicit that **a compliant archive must be independent of the source platform, remaining accessible regardless of changes to the organization's subscription.**

CAIRN — capturing and normalizing communication into its own store — **already satisfies that definition as a side effect of its core architecture.** A team whose Slack plan lapses, or who migrates from Slack to Teams, retains a continuous, searchable, AI-comprehensible record in CAIRN.

**This is a genuinely valuable, currently-unmarketed capability**, and it should be positioned deliberately: CAIRN is not only the system that understands your work, it is the system that _remembers_ it independent of any vendor you might leave. That is a real switching-cost moat and a real compliance selling point.

### 5.2 Sequencing note

Full DLP and eDiscovery are **not v1 requirements** — the initial target customer (5–20 person software teams) rarely has formal legal-hold obligations. They become required as CAIRN moves upmarket, and they are only _possible_ in native chat (§3.3). This is a Year 2+ capability set, but the native-chat architecture should not foreclose it.

---

## 6. Strategy — **[DECIDED: both, phased, with native chat as the destination]**

**Founder's decision:** build both. Slack tracking first, then native chat — with the deliberate intent that **teams migrate toward CAIRN's own chat over time**, making tracking progressively easier and more complete as they do.

This is not "Slack integration, and maybe native chat later." Native chat is the **planned end state**. Phase 1 exists to earn the right to build it, and to make the migration voluntary rather than demanded.

### Phase 1 — Track where they already are

Slack and Google Chat as read-only tracked sources via Events API, normalized per file 01's pattern. Real-time capture from day one; backfill best-effort pending Marketplace approval (§3.4). **Zero migration friction** — this is what makes adoption possible at all.

### Phase 2 — Native CAIRN chat, on a commercial chat platform (§4.1)

Delivers three things Slack integration structurally cannot:

1. **The anti-Slack value proposition** (§1) — chat that never buries anything and requires no channel monitoring. Built directly against the complaints Slack's own users voice.
2. **Complete, structured capture** — no API rate limits, no Marketplace dependency, no history gaps. Tracking quality improves materially the moment a team moves.
3. **A path to enterprise compliance** (§5) — DLP, eDiscovery, and legal hold, which are gated behind Slack Enterprise Grid and therefore unreachable via integration (§3.3).

Plus the structured capabilities generic chat cannot offer: in-thread work assignment that becomes a tracked commitment, explicit decision marking, meeting follow-up threads linked to their source meeting (file 03), and conversation natively linked to code and documents.

### Phase 3 — Voluntary migration

The migration path is a product concern, not a sales one. Teams should be able to run both side by side, move one channel at a time, and choose CAIRN chat because the structured features are better — never because the integration was degraded to force the move. **Deliberately crippling Slack tracking to drive migration would be a betrayal of the trust positioning and is out of bounds.**

**Why this ordering works:** tracking value lands immediately, the largest engineering investment waits until the AI core is proven, the Slack Marketplace dependency is de-risked, and native chat launches with a _reason_ to switch rather than a _request_ to switch.

---

## 7. What is captured, under any approach

- Messages classified as work-relevant.
- Decisions reached in a thread.
- Work assigned or committed to in conversation.
- Questions left unanswered; blockers raised.

### 7.1 The classification requirement

Chat is overwhelmingly noise by volume. Feeding raw channel history to a summarizer produces diluted output and wastes AI spend. A classification stage runs **before** summarization, with a deliberately **conservative** threshold: where relevance is uncertain, exclude. The cost asymmetry justifies it — a missed work message is a small gap; a surfaced personal message is a trust violation that ends the relationship. Model tiering applies (a cheaper model for this high-volume stage).

---

## 8. Privacy — the highest-risk pillar

Chat captures people's unguarded words in a way GitHub activity does not. Strictest handling applies:

- **Channel-level granularity.** Opt-in per channel, never workspace-wide. **Private channels and direct messages excluded by default**, requiring separate explicit authorization.
- **Conservative classification** (§7.1) as a privacy control, not merely a quality one.
- **First proving ground** for the Trust & Privacy Center (file 05 §B.6).
- **Bridging raises a specific consent question** (§2.2): when a CAIRN user and a Slack user converse across a bridge, the Slack-side participants must be notified that messages are being captured. Bridge notification is a mandatory feature, not a setting.

### 8.1 Cross-file correction

Under GDPR, **consent is not a valid lawful basis in employment contexts** (power imbalance). CAIRN's EU basis is **legitimate interest with a documented assessment**; opt-in controls are what keep it proportionate and defensible. Detailed in file 05 §B.2.1.

---

## 9. Technical architecture (Phase 1)

Consistent with file 01's ingestion pattern:

- **Events API endpoint** — verify Slack's signature, enqueue, acknowledge fast; no processing in the request path.
- **Idempotent consumption** keyed on Slack's event ID.
- **Exponential backoff on 429s**, honoring `Retry-After`.
- **Tier-aware call budgeting** — per-method rate tiers tracked explicitly, not assumed uniform.
- **Normalization** into the shared `ActivityEvent` schema, feeding the single Understanding layer (file 00 §6).

---

## 10. Decision status

### Resolved

| #   | Decision                   | Outcome                                                                                                                 |
| --- | -------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| 1   | **Sequencing**             | **Both, phased.** Slack tracking first; native chat as the planned destination, with voluntary migration over time (§6) |
| 2   | **Native chat foundation** | **Commercial chat platform (Stream leading candidate), not Matrix, not from scratch** (§4.1)                            |
| 3   | **Two-way bridging**       | **Reclassified as nice-to-have.** Read-only tracking satisfies the actual requirement (§2.4)                            |

### Still open

4. **Slack Marketplace application** — approve applying early, accepting a third-party approval dependency outside our control (§3.4).
5. **Backfill expectation** — confirm value is delivered from real-time capture alone, with backfill as enhancement rather than launch requirement.
6. **Private channels and DMs** — confirm excluded by default, requiring separate explicit authorization (§8).
7. **Compliance roadmap** — confirm DLP/eDiscovery/legal hold are Year 2+ capabilities the native-chat architecture must not foreclose (§5.2), and that the independent-archive positioning (§5.1) carries into marketing.
8. **Migration ethics (§6 Phase 3)** — confirm that Slack tracking is never deliberately degraded to drive migration to native chat.

---

_The core architectural decisions are resolved. Native chat is the destination, reached by earning migration rather than demanding it, built on infrastructure that lets a 10-person team ship it without becoming a messaging-infrastructure operator._
