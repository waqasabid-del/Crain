# Pillar 4 — AI-Generated Project Documentation

**Status:** ✅ LOCKED — decisions resolved, ready for implementation
**Depends on:** [01-github-integration.md](01-github-integration.md), [02-chat-system.md](02-chat-system.md), [03-meeting-intelligence.md](03-meeting-intelligence.md), [09-understanding-layer.md](09-understanding-layer.md)
**Feeds into:** N/A — this is the synthesis pillar

**Founder's stated goal:** Project documentation is important, developers rarely have time to write it, and CAIRN should produce it using AI.

---

## 1. Competitive context — a solved problem and an unsolved one

AI documentation generation is a mature, crowded category: **Mintlify, GitBook, Fern, ReadMe, Document360** all handle authoring, publishing, Git sync, and AI-ready delivery. Adoption is mainstream — roughly **70% of development teams used AI documentation tools in 2025**, and **85% of developers rate AI-generated docs as good as or better than hand-written ones.**

Generating documentation from a codebase is therefore **not a differentiator.** It is commodity capability, and any plan positioning it as CAIRN's advantage is mistaken.

The unsolved problems are two, and CAIRN is uniquely positioned on both:

| Problem                         | Why it's unsolved                                   | CAIRN's position                                                                     |
| ------------------------------- | --------------------------------------------------- | ------------------------------------------------------------------------------------ |
| **Documentation goes stale**    | Generators document once; code moves on             | Staleness detection driven by the same event stream that captures code activity (§2) |
| **The _why_ is never captured** | It lives in Slack threads and meetings, not in code | CAIRN holds all four sources in one graph (§3)                                       |

**The core competitive statement:** every documentation tool generates docs _from code_. CAIRN generates them from **code plus the human context that explains the code.** A tool reading a repository can describe _what_ the auth layer does. Only CAIRN can record _why_ it was built that way, _who_ decided, _when_, and _what alternative was rejected — and where that reasoning was said._ That context is unreachable to any repository-reading tool, and it is exactly what disappears when someone leaves the team.

---

## 2. The staleness problem — the real product

The industry diagnosis is unambiguous and worth quoting:

> A generator that documents a repository once has solved the easy 20% of the problem and left the hard 80% — because **stale documentation is arguably worse than none: it lies with authority.**

This reframes the pillar entirely. **Generating a README is table stakes. Keeping documentation true as code moves is the actual product.**

The established pattern is **docs-on-change automation**: the same pull request that renames an endpoint triggers regeneration of the affected documentation, so docs and code move together because one event drives both. **CAIRN already receives that event** — file 01's webhook pipeline delivers it in real time, meaning the hard part of this pattern is infrastructure CAIRN builds anyway.

**Requirement:** documentation is regenerated or flagged by the _same event stream_ that captures code activity — never by a scheduled job, and never by a human remembering. This is the difference between a documentation generator and a documentation _system_.

---

## 3. The ADR opportunity — the strongest single fit in the product

Architecture Decision Records capture _why_ a technical choice was made. They are widely recognized as valuable and widely abandoned in practice. The documented reasons are precisely CAIRN's capabilities:

> **"ADRs go stale because decisions don't stay in the file — they change in Slack, GitHub and Jira, and nobody updates the ADR."**
>
> **"The real problem isn't writing ADRs; it's that decisions don't stay in the ADR file."**
>
> **"The main barrier to adoption usually isn't disagreement — it's friction."**

Map these against CAIRN:

| Why ADRs fail                                                     | CAIRN's answer                                                                                                     |
| ----------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| Decisions change in Slack and GitHub, and nobody updates the file | CAIRN **watches Slack and GitHub** — it sees the change that invalidated the ADR (files 01, 02)                    |
| Friction stops adoption                                           | CAIRN drafts the ADR automatically; the human cost drops to reviewing, not writing                                 |
| Decisions don't stay in one file                                  | CAIRN's temporal graph tracks decisions _as they evolve_, with supersession rather than overwriting (file 09 §3.2) |

The field's own stated direction confirms the thesis: _"the interesting work in 2026 is building systems where decisions are reasoned across the system rather than read from one file at a time."_ **That is a description of file 09's temporal knowledge graph.**

Two further signals: **there is no dominant ADR tool** — the field is young and open — and AI-assisted ADR drafting from commits is already showing **40–60% reduction in manual effort**, before adding the chat and meeting context that CAIRN uniquely holds.

**Conclusion: ADR generation is the highest-differentiation feature in this pillar**, and arguably in the product. It is gated on files 02 and 03 being accurate (§6), but it should be understood as a headline capability rather than a late addition.

---

## 4. The trust problem — fluency creates false confidence

This is the most important risk in this pillar, and current data on AI-generated output makes it concrete:

| Finding                                             | Figure                                |
| --------------------------------------------------- | ------------------------------------- |
| Developers who do not fully trust AI-generated code | **96%**                               |
| Trust in AI tool accuracy                           | **33%**, down from 43% the prior year |
| Developers who always verify before committing      | **48%**                               |
| AI's share of committed code industry-wide          | **42%**                               |

And the mechanism that matters most here:

> **"Fluent comments and tidy structure can create the impression that the code is more trustworthy than it really is"** — output that reads like a senior engineer wrote it, even when the underlying assumptions are shaky.

**For documentation this is the central hazard.** A beautifully written, well-structured document that is subtly wrong is _more_ dangerous than an obviously rough one, because its polish suppresses the reader's scepticism. A new engineer will act on it. This is the same failure class as **silent failures** in AI code — output that runs without crashing but does not do what was intended, and is harder to catch than an outright error.

### 4.1 What this requires

1. **Never publish autonomously.** Every generated document carries a persistent, visually unmistakable **"AI-drafted, pending review"** state until a human approves it (§5.3).
2. **Provenance on every claim.** Each section links to the source activity it derives from — commits, discussion, meetings — so verification takes seconds rather than requiring reconstruction (file 09 §4.1).
3. **Hedge appropriately.** Documentation derived from a noisy meeting transcript (file 03 §2: ~30% speaker misattribution) must not read with the same authority as documentation derived from code structure.

### 4.2 The trust crisis is also the opportunity

If 96% of developers distrust AI output and only half verify it, the winning product is not the one that generates the most confident-looking documentation — it is the one that makes **verification effortless**. CAIRN's provenance architecture (file 09 §4) is exactly that mechanism, and it should be positioned as the differentiator it is: _every claim, one click from its evidence._

---

## 5. Functionality

### 5.1 Generated artifacts

| Artifact                          | Sources                                                      | Trigger                                   |
| --------------------------------- | ------------------------------------------------------------ | ----------------------------------------- |
| **README / setup documentation**  | Code structure, existing docs, commit history                | On connect; on material structural change |
| **PR change summaries**           | Diff plus linked discussion                                  | Every pull request                        |
| **Architecture Decision Records** | Decisions from chat and meetings, plus the implementing code | On decision detection (§3)                |
| **Living project overview**       | Continuous activity across all sources                       | Continuous                                |
| **Onboarding documentation**      | Full project history and current state                       | On request                                |

### 5.2 Staleness management

- **Drift detection** — when code underlying a documented behavior changes materially, the affected section is flagged immediately (§2).
- **Proposed updates, not just warnings** — CAIRN drafts the correction rather than only reporting the problem. A flag without a fix reintroduces the friction the pillar exists to remove.
- **Decision supersession** — when a new decision contradicts a documented one, the prior ADR is marked superseded with a link forward, preserving history (file 09 §3.2). This is what ADR tooling conspicuously lacks (§3).
- **Coverage visibility** — which parts of the system have no explanation at all, so documentation debt is visible rather than assumed.

### 5.3 Review workflow

1. CAIRN opens a **pull request** into the customer's existing repository.
2. The PR body states plainly what changed, why it was generated, and which sources it drew on.
3. Standard code review applies — the team's existing culture supplies the human gate at no additional UX cost.
4. Merge marks the document human-approved; the draft state clears.
5. Rejection or edit becomes evaluation signal (file 10 §2.1).

**Why a PR rather than a CAIRN-hosted wiki:** documentation living beside the code it describes is documentation people actually read, it inherits the team's existing review discipline, and it preserves the "no new tool to learn" principle (file 00 §1). It also means CAIRN's output survives independently of CAIRN — a fairness property worth stating openly to a cautious buyer.

### 5.4 Explicitly not built

- **External-facing product or API documentation** in v1 — a materially higher accuracy bar, and a direct fight with Mintlify and peers on their strongest ground.
- **A hosted documentation site** — that is the commodity layer (§1).
- **Autonomous publishing** without human approval, under any configuration (§4.1).

---

## 6. Machine-readable output

Nearly **half of all documentation-site traffic now comes from AI agents** — Cursor, Claude Code, ChatGPT — rather than human readers, and documentation tools have responded with conventions such as `llms.txt`.

**Implication:** generated documentation is structured for both audiences — clean semantic markdown, explicit headings, unambiguous terminology. This costs nothing at generation time and makes CAIRN's output immediately useful to whatever coding agents the customer's developers already run. It also creates a natural bridge to file 07: a team whose AI agents consume CAIRN-generated documentation is already deriving value from CAIRN's understanding layer.

---

## 7. Build sequencing

**Phase 1 — depends only on file 01:**

1. README / setup generation.
2. PR change summaries.
3. **Staleness detection**, wired into file 01's webhook stream.

**Phase 2 — gated on files 02 and 03 reaching reliable accuracy:** 4. **ADR generation** (§3) — the differentiating feature. 5. Living project overview.

**The gate is not negotiable under demand pressure.** ADRs consume decisions extracted from chat and meeting transcripts. Given file 03's ~30% speaker misattribution rate, shipping ADR generation before those pillars are accurate would produce authoritative-looking documents asserting decisions that were never made — the exact failure §2 and §4 identify as worse than no documentation at all. Ship this when it has been earned.

---

## Decisions requested from founder

1. **Positioning** (§1) — confirm CAIRN is positioned on _staleness and the why_, not on generation quality. Generation is commodity; competing there is a losing fight against Mintlify and GitBook.
2. **ADR as headline capability** (§3) — confirm ADR generation is treated as a flagship differentiator rather than a minor feature, given that the documented reasons ADRs fail map exactly onto CAIRN's architecture.
3. **Staleness detection in Phase 1** (§7) — confirm this ships with initial generation rather than deferring. It is the actual product (§2).
4. **Delivery as pull request** (§5.3) — confirm over a CAIRN-hosted docs site.
5. **Never autonomous** (§4.1) — confirm no configuration permits publishing without human approval, given that fluency creates false confidence and 96% of developers already distrust AI output.
6. **ADR gating** (§7) — confirm ADR generation waits for files 02 and 03 accuracy, even under customer demand.
7. **Internal-only scope** (§5.4) — confirm v1 excludes external-facing documentation.

---

_This file completes the four capture-and-synthesis pillars. Sections 1 and 3 together contain the clearest articulation of why CAIRN's four-pillar architecture exists: documentation enriched by human context no repository-reading tool can access, and decision records that stay true because the system watches where decisions actually change. Both belong directly in marketing material._
