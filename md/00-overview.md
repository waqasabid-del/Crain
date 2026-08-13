# CAIRN — Product Overview

**Product name:** CAIRN
**Document status:** Draft for review
**Document owner:** Founder
**Version:** 1.0

---

## 1. Purpose

CAIRN is an AI-native team operating system that automatically captures and understands what a team is actually doing — in code, conversation, meetings, and documentation — and turns that into an honest, plain-English picture of progress, without requiring anyone to manually update a ticket, write a status report, or fill in a form.

**Problem it solves:** Every existing team-coordination tool (Jira, Linear, Asana, Monday, ClickUp, Notion) depends on people manually maintaining an accurate picture of their own work. That manual step is disliked, frequently skipped, and produces a system of record that no longer reflects reality within weeks of setup. Small teams (5–20 people) feel this most acutely — they cannot justify a dedicated project manager or scrum master to enforce the discipline these tools require, and are the least-served segment by every major incumbent, all of which are increasingly built for enterprise procurement, not small-team adoption.

**Core principle (win condition):** _Ease of use plus full automatic connection._ If a feature requires manual work to stay accurate, it has failed by definition. Every decision in every pillar file in this folder is judged against one question: does this remove manual work, or does it quietly add it back?

## 2. Target users

CAIRN is not built for one persona but for a small set of roles who all need the same underlying picture of a team's work, seen through different lenses (full detail in [08-roles-and-industries.md](08-roles-and-industries.md)):

| Role                                    | Core need                                                                      |
| --------------------------------------- | ------------------------------------------------------------------------------ |
| Founder / Owner / Team Lead             | An honest, whole-team picture without chasing status updates                   |
| Developer / Engineer                    | Zero manual reporting; contribution speaks for itself through actual work      |
| Product Manager                         | Cross-source visibility tying code, chat, and meetings to specific initiatives |
| Designer                                | Contribution visibility beyond commits — reviews, iteration, decisions         |
| Marketing / Sales / Ops (non-technical) | A plain-English view requiring no technical fluency to read or trust           |

**v1 target customer profile:** software product teams and agencies of 5–20 people already using GitHub, Slack, and Google Workspace, with no dedicated project manager, and a technical founder or tech lead as the buyer.

## 3. Goals and success metrics

| Goal                                              | Metric                                                                         |
| ------------------------------------------------- | ------------------------------------------------------------------------------ |
| Product is genuinely easy to adopt                | Time from signup to first useful output under 30 minutes                       |
| Product removes manual work rather than adding it | Zero required manual data entry for any tracked source                         |
| Teams trust and habitually use it                 | Weekly active teams using the core summary view 3+ times in 7 days             |
| Product is trusted, not feared                    | No surveillance-related complaints or churn reasons in early customer feedback |
| AI output is reliable                             | Evaluation harness factual-accuracy score above 90% on the internal test set   |

## 4. Product scope

CAIRN's specification is organized in three layers: what it captures, what it does with what it captures, and what governs both.

### 4.1 Capture — the six pillars

| #   | Pillar                  | File                                                     | Summary                                                                                                                   |
| --- | ----------------------- | -------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| 1   | Code Tracking           | [01-github-integration.md](01-github-integration.md)     | Automatic, signal-focused tracking of GitHub activity, with correct attribution as the technical moat                     |
| 2   | Chat & Communication    | [02-chat-system.md](02-chat-system.md)                   | Tracked discussion — Slack/Google Chat integration first, native chat on Matrix as Phase 2 with bridging to 40+ platforms |
| 3   | Meeting Intelligence    | [03-meeting-intelligence.md](03-meeting-intelligence.md) | Consent-gated capture of decisions and assigned work from meetings                                                        |
| 4   | Auto Documentation      | [04-auto-documentation.md](04-auto-documentation.md)     | AI-drafted, human-reviewed documentation synthesized from the other three pillars                                         |
| 5   | UX, Design & Compliance | [05-ux-design-privacy.md](05-ux-design-privacy.md)       | Design philosophy and per-company/per-country compliance — **the governing document for the whole folder**                |
| 6   | MCP Client Support      | [07-mcp-integration.md](07-mcp-integration.md)           | Standardized connection to additional tools via the Model Context Protocol                                                |

### 4.2 Intelligence — the core engine

The four capture pillars feed one shared engine. **This is the actual product** — capture without understanding is a log file.

| File                                                   | Role                                                                                                                                                                                                                                          |
| ------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| [09-understanding-layer.md](09-understanding-layer.md) | The four-stage AI pipeline (classify → extract → resolve → synthesize), the temporal knowledge graph that tracks how facts change over time, grounding rules that prevent fabrication, and the cost architecture the unit economics depend on |
| [10-ai-evaluation.md](10-ai-evaluation.md)             | How output quality is measured and defended — golden dataset, calibrated LLM judge, release gates, and the failure taxonomy. Built _before_ the pipeline scales, not after                                                                    |

### 4.3 Foundation

| File                                                     | Role                                                                                         |
| -------------------------------------------------------- | -------------------------------------------------------------------------------------------- |
| [06-infrastructure.md](06-infrastructure.md)             | Cloudflare frontend, GCP backend and AI, per-tenant region assignment                        |
| [08-roles-and-industries.md](08-roles-and-industries.md) | The five user roles, the three competitor categories, and industry expansion beyond software |

**Explicitly out of scope for v1:**

- **A full enterprise replacement for any established incumbent** — Jira, Confluence, Linear, ClickUp, Monday.com, Asana, Notion, or Trello — for large engineering or operations organizations. CAIRN is not competing feature-for-feature with these tools at enterprise scale in v1; it is targeting the small-team segment they serve poorly.
- **An engineering productivity metrics platform.** Research during specification identified a second competitor category the original proposal missed — engineering intelligence platforms (Swarmia, LinearB, Jellyfish, Waydev, DX). CAIRN deliberately does **not** compete on their terms: it produces no productivity scores, delivery benchmarks, or per-developer throughput metrics. See [08-roles-and-industries.md](08-roles-and-industries.md) §B and [01-github-integration.md](01-github-integration.md) §1–2 for why this refusal is both a positioning advantage and a regulatory necessity.
- **A performance evaluation, ranking, or scoring system** of any kind, regardless of competitor precedent (several incumbents, and Atlassian's Rovo specifically, layer AI on top of existing ticket-scoring patterns — CAIRN does not follow this pattern, by design, per file 05).
- **A chat, meeting, or document-editing tool built from scratch as a primary, standalone product** — CAIRN integrates with existing tools (Slack, Google Chat, Google Meet, Zoom) rather than replacing them in v1, with native chat as a deliberately deferred, optional Phase 2 (file 02).
- **Support for non-software verticals** — marketing agencies, consulting firms, real estate, and other business types identified as strong future fits are deferred to Year 2 and beyond, per file 08.
- **Manual ticket/task management as a fallback mode** — CAIRN does not offer a traditional manually-maintained board or ticket system as an alternative input method; this would directly contradict the core "no manual work" principle in Section 1 and blur the product's positioning against every manual-entry competitor listed above.

## 5. Non-functional requirements

These apply across every pillar and are not restated per file:

- **Privacy and granular opt-in by default** — every data source is off until explicitly authorized; no feature produces comparative scores or rankings between individuals. Full detail in file 05.
- **Regional compliance** — data handling and residency adapt automatically per company and per country, not one global policy. Two corrections established during research and detailed in file 05 §B: CAIRN's **EU lawful basis is legitimate interest with a documented assessment, not consent** (consent is not valid in employment contexts under GDPR), and the **EU AI Act high-risk deadline has moved from August 2026 to December 2, 2027**.
- **Regulatory design boundary** — CAIRN must never allocate work, evaluate performance, or inform employment decisions. These are not only trust commitments; they are what keeps the product outside EU AI Act high-risk classification (file 05 §B.3). Treated as a hard product boundary with financial consequences.
- **Reliability of AI output** — every AI-derived claim about a person's work carries a confidence level and one-click provenance to its source, with human review before anything is treated as fact. The interface must express certainty gradation consistently across all pillars (file 05 §A.2).
- **Performance** — fast time-to-first-value (under 30 minutes from signup), consistent with the product's core adoption principle.
- **Infrastructure** — frontend on Cloudflare, AI and backend on GCP, with per-tenant region assignment built in from day one. Full detail in [06-infrastructure.md](06-infrastructure.md).

## 6. Architectural and sequencing decisions

These affect more than one pillar file, so they are decided here rather than separately in each file. All three are treated as the current working direction, and — consistent with the founder's guidance to move forward now and refine with time — remain open to revision as real usage and customer feedback come in, rather than being permanent, unchangeable commitments.

1. **Build order — DECIDED.** GitHub tracking (file 01) plus a minimal chat integration (file 02, Phase 1) ship first as the MVP wedge. These two sources alone are sufficient to produce a genuinely useful first summary, without requiring meeting intelligence or auto-documentation to exist yet.
2. **Chat strategy — DECIDED.** A phased approach: Slack and Google Chat integration first (zero migration friction, fastest to ship), with native CAIRN chat following as an optional Phase 2 once the core AI tracking layer is proven. Full detail and rationale in file 02.
3. **AI architecture — DECIDED.** One shared "Understanding" layer processes all data sources through the common `ActivityEvent` schema, rather than separate per-source pipelines. This keeps AI behavior consistent across pillars and is materially cheaper to build and maintain. Files 01–04 and 07 are already written on this assumption.

## 6A. Material findings from specification research

Research conducted while writing the pillar files surfaced findings that changed the plan. Consolidated here so they are visible in one place:

| Finding                                                                                                                                          | Impact                                                                                                                            | Detail                   |
| ------------------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------- | ------------------------ |
| **A second competitor category exists** — engineering intelligence platforms already read GitHub and sell insight from it                        | Repositions pillar 1; differentiation is narrative + symmetry + multi-source, not better GitHub reading                           | file 01 §1, file 08 §B.2 |
| **Slack severely restricted history access (May 2025)** — `conversations.history` moved to ~1 request/minute for non-Marketplace apps            | Historical backfill is impractical without Slack Marketplace approval — a third-party dependency on a Salesforce-owned competitor | file 02 §2.2–2.3         |
| **GDPR: consent is not a valid lawful basis in employment**                                                                                      | Legal framing changes to legitimate interest with documented assessment; product design unchanged                                 | file 05 §B.2.1           |
| **EU AI Act high-risk deadline moved to December 2, 2027**                                                                                       | More runway; direction unchanged, urgency reduced                                                                                 | file 05 §B.3.1           |
| **Annex III explicitly covers task allocation and performance monitoring**                                                                       | CAIRN's no-scoring/no-allocation design is load-bearing regulatory architecture, not just ethics                                  | file 05 §B.3.2–3.3       |
| **13 US states require all-party recording consent; strictest law governs distributed teams**                                                    | Strict consent default is the only workable standard for meetings                                                                 | file 03 §2               |
| **Vertex AI regional endpoints cost ~10% more than global**                                                                                      | EU customers cost measurably more to serve; must be priced or absorbed deliberately                                               | file 06 §3.2             |
| **MCP is established, not speculative** — 28% Fortune 500 adoption, official registry with ~9,650 servers                                        | Validates the MCP direction; but documented confused-deputy/account-takeover risks require real security controls                 | file 07 §1, §4           |
| **Attribution correctness is the real technical moat** — squash merges, bot noise, and identity fragmentation silently corrupt contribution data | Elevated from polish to MVP requirement; wrong attribution destroys trust irrecoverably                                           | file 01 §5               |

## 7. How this folder is governed

The `md/` folder is a planning workspace, deliberately kept separate from the product codebase so early-stage thinking does not leak into or constrain the actual system architecture. Each pillar has its own file with a consistent structure: dependencies, detailed specification, and a closing list of decisions requested from the founder. A file's status moves from **Draft** to **Locked** only once its listed decisions are confirmed. This file (00) is the anchor — every other file traces back to the purpose, users, and principles defined here, and no pillar file should introduce a goal or principle that contradicts this one.

---

## Decisions requested from founder

Section 6's three architectural questions are now resolved (see above). The following remain open for explicit confirmation:

1. **Confirm the problem and purpose statement in Section 1** reflects your intent accurately, particularly the framing of the core principle as the standard every feature is judged against.
2. **Confirm the target user table in Section 2** and the v1 target customer profile — this determines who every design and feature decision downstream is optimized for.
3. **Confirm the "explicitly out of scope for v1" list in Section 4** — these boundaries prevent scope creep into enterprise, scoring, or non-software-vertical features before the core product is proven.

---

_This file remains in Draft status until items 1–3 above are confirmed. Once confirmed, it moves to Locked and becomes the reference every other pillar file is checked against for consistency. Decisions in this document — including the three now marked DECIDED in Section 6 — are working commitments, not permanent constraints; they can be revisited as real customer usage informs the plan._
