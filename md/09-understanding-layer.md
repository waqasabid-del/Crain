# The Understanding Layer — CAIRN's Core AI Engine

**Status:** ✅ LOCKED — includes prompt-injection threat model (§6)
**Depends on:** [01](01-github-integration.md)–[03](03-meeting-intelligence.md) (data sources), [06-infrastructure.md](06-infrastructure.md)
**Feeds into:** Every user-facing surface, and all of [04-auto-documentation.md](04-auto-documentation.md)
**Paired with:** [10-ai-evaluation.md](10-ai-evaluation.md) — the engine without the harness degrades silently

**Why this file exists:** Files 01–04 each capture a data source and hand it to "the shared Understanding layer." That layer is the actual product — capture without understanding is a log file.

---

## 1. What this layer must do

| Output              | Consumer         | Requirement                                                |
| ------------------- | ---------------- | ---------------------------------------------------------- |
| **Founder Brief**   | Owner / lead     | Daily prose summary, factually grounded                    |
| **My Week**         | Every individual | Personal record, editable by its owner                     |
| **Team Feed**       | Everyone         | Searchable, filterable activity stream                     |
| **Extracted facts** | file 04          | Decisions, assignments, blockers — with provenance         |
| **Answers**         | Everyone         | "What happened with the auth work?" answered from evidence |

Four constraints govern every choice below:

1. **Factual grounding** — every claim traces to a source event (file 05 §A.2).
2. **No scoring** — narrative only, never comparative measurement (file 05 §B.3.3). Regulatory architecture, not preference.
3. **Cost discipline** — under $2.00 per user per month at scale.
4. **Injection resistance** — CAIRN ingests attacker-influenceable content by design (§6).

---

## 2. Architecture — four stages

```
ActivityEvent stream
   │
   ├─ Stage 1: CLASSIFY    cheap model · high volume · untrusted input
   ├─ Stage 2: EXTRACT     cheap-mid model · schema-constrained · untrusted input
   ├─ Stage 3: RESOLVE     deterministic code · no LLM · trust boundary
   └─ Stage 4: SYNTHESIZE  premium model · low volume · trusted facts only
         │
         └─→ Brief / My Week / Feed / Documentation
```

The staging is not merely a cost optimization. It is simultaneously the cost strategy (§7), the quality strategy (§5), and the security architecture (§6) — which is why it holds up under pressure from all three directions.

### Stage 1 — Classify

Triage every event: work-relevant, and what kind of signal? Highest volume by far; cheapest capable model. File 02 §7.1 requires a conservative threshold — uncertain content is _excluded_, making this a privacy control as much as a quality one.

### Stage 2 — Extract

Convert relevant events into structured facts: decisions, assignments, blockers, artifacts shipped. **Output is schema-constrained, never free text** — which makes it verifiable, cheap to store, and (critically) resistant to injection (§6.3). Each fact carries its source event ID and confidence from creation.

### Stage 3 — Resolve (no LLM)

Reconcile facts against existing knowledge: identity resolution (file 01 §5.3), cross-source deduplication (a decision mentioned in a meeting _and_ a chat thread is one decision), temporal conflict handling (§3.2).

**Deliberately no LLM.** Research is explicit that freshness and conflict resolution should be deterministic rather than delegated to a model — a model asked which of two contradictory facts is current answers unreliably and unrepeatably. Deterministic rules are cheaper and more correct.

**This stage is also the trust boundary** (§6.2): everything before it has touched untrusted content; everything after it operates on validated, structured facts.

### Stage 4 — Synthesize

Facts become prose. The only premium-model stage, running on pre-digested facts rather than raw activity — which is what makes both the economics (§7) and the security posture (§6) work.

---

## 3. The knowledge layer — a temporal graph

### 3.1 Why not plain vector search

Graph-structured retrieval with relationship traversal achieves **over 36% higher answer accuracy and 21% better retrieval F1 than dense vector retrievers on multi-hop questions.**

CAIRN's questions are almost entirely multi-hop:

> _"Why is the payments feature late?"_ — connect a meeting decision → the PR it blocked → the unavailable reviewer → the chat thread raising it.

Vector similarity retrieves passages that _sound_ related. It cannot traverse that chain.

### 3.2 Facts change — the system must know it

A person moves projects. A decision reverses. A naive store either overwrites (losing history) or accumulates contradictions (losing truth).

The 2026 pattern is a **temporal knowledge graph** — facts as nodes with typed relationships and **explicit validity intervals**, tracking evolution rather than overwriting. Production systems (Zep, Graphiti) exist for exactly this.

**Essential for CAIRN**: "Ali is working on authentication" three weeks after he moved to billing is precisely the failure that destroys trust. Superseded facts are marked superseded, never deleted — history preserved, only currently-valid facts reaching synthesis.

### 3.3 Implementation

PostgreSQL with pgvector (file 06 §4.4): relational tables with explicit edges and validity columns, plus pgvector for entry-point search. Not a separate graph database — materially simpler to operate and sufficient at CAIRN's scale. Note the **2,000-dimension HNSW ceiling** constrains embedding model choice (file 06 §4.4).

---

## 4. Context engineering

How context is assembled determines output quality as much as model choice does.

### 4.1 The retrieval strategy

The 2026 default for serious systems is **hybrid**: retrieve a substantial but bounded set of tokens — roughly **50K–200K** — then long-context-reason over them. Not everything, and not a handful of chunks.

For CAIRN: graph traversal (§3) selects the bounded set; Stage 4 reasons over it.

### 4.2 Two failure modes to design against

**Lost-in-the-middle.** Models recall the **start and end** of a long context reliably and perform worst on information **buried in the middle**. This is a positional property, not a capability gap.

**Context rot.** Performance _degrades_ as context grows with poorly curated information. More context is not better context — a longer, sloppier prompt produces worse output than a shorter, well-curated one.

**Both argue against the naive approach** of stuffing a week of raw activity into a large context window and asking for a summary. The staged architecture (§2) is what prevents this: Stage 4 sees resolved facts, not raw streams.

### 4.3 Placement rules

Because attention concentrates at the edges:

- **Critical instructions at the start.**
- **Most relevant retrieved facts near the end**, close to the request.
- Lower-salience background in the middle, where recall is weakest and the cost of imperfect recall is lowest.

### 4.4 Contextual retrieval

Adding **chunk-specific summaries before embedding cuts retrieval failures by 49%** compared to raw chunking.

For CAIRN this is natural rather than an add-on: Stage 2 already produces a structured summary of every event. Embedding the _summarized_ fact rather than raw text is both cheaper and substantially more accurate — a case where the architecture already does the right thing and it should be made explicit.

---

## 5. Grounding — how CAIRN avoids stating untrue things

### 5.1 Mandatory citation

**Every claim carries a citation to its source event(s).** Forced citation **cuts hallucination rates by ~45%** by anchoring generation to retrieved content.

This makes file 05's provenance requirement and the primary hallucination defense **the same mechanism** — which is why it is affordable.

### 5.2 Span-level verification

Post-synthesis, each claim is matched against its cited evidence and flagged if unsupported. Unsupported claims are **suppressed, not caveated.** The user-visible failure mode must be _incompleteness_, never _confident wrongness_.

### 5.3 Groundedness as a monitored metric

The proportion of claims traceable to evidence is tracked continuously in production — an early-warning signal that degrades before users complain (file 10 §4).

### 5.4 Stacked mitigations, matched to failure mode

Reliable systems stack the defense fitting each failure type rather than applying one universally:

| Failure mode                    | Mitigation                                               |
| ------------------------------- | -------------------------------------------------------- |
| Invented facts                  | Retrieval grounding + mandatory citation (§5.1)          |
| Stale facts as current          | Temporal validity intervals (§3.2)                       |
| Wrong person credited           | Deterministic identity resolution (Stage 3)              |
| Overconfidence from noisy input | Per-claim confidence + hedged language (file 03 §6)      |
| Contradictory sources           | Deterministic resolution (Stage 3), never model judgment |
| **Injected instructions**       | **Structural separation + capability restriction (§6)**  |

### 5.5 Language discipline

Confidence lives in the writing, not only metadata. _"It looks like the payments work stalled on review"_ invites correction; the unhedged form asserts what the system may not be entitled to assert. Enforced in the prompt layer, tested in evaluation (file 10 §1).

---

## 6. Threat model — prompt injection

**This section was flagged in file 07 §4.4 as belonging here.** It is a risk to CAIRN's core product, independent of whether MCP ever ships.

### 6.1 Why CAIRN is exposed

**CAIRN ingests attacker-influenceable content by design.** Pull request descriptions, commit messages, chat messages, meeting transcripts, and issue text — all written by people, any of whom could be adversarial, all flowing into an LLM pipeline.

The underlying vulnerability is architectural, not a bug to patch:

> **LLMs cannot distinguish trusted system instructions from untrusted input** — both appear as natural-language strings in the same context window.

Indirect injection has moved to the centre of the LLM threat model precisely because systems like CAIRN consume attacker-controllable text as a matter of routine.

**Realistic attack:** a contractor with repository access writes a PR description containing instructions intended to make CAIRN's summarizer fabricate progress, suppress mention of their stalled work, or emit context from another part of the pipeline.

### 6.2 CAIRN's structural defense — already largely in place

The most reliable published structural defense is a **privileged planner / unprivileged executor** split: a privileged component handles the request and produces a structured plan, while an unprivileged component processes untrusted retrieved content **but cannot issue privileged calls.**

**CAIRN's staged architecture (§2) already implements this pattern**, and this should be recognized and preserved deliberately rather than eroded for convenience:

| Stage           | Trust status                | Capability                                                    |
| --------------- | --------------------------- | ------------------------------------------------------------- |
| 1 — Classify    | Handles untrusted content   | Emits a label. Nothing else.                                  |
| 2 — Extract     | Handles untrusted content   | Emits schema-validated facts. **No tool access, no actions.** |
| **3 — Resolve** | **Trust boundary**          | Deterministic code. No LLM, therefore no injectable surface.  |
| 4 — Synthesize  | Operates on validated facts | Generates prose from already-structured input                 |

**The architectural rule, stated as an invariant:** _no stage that touches untrusted content has the capability to take an action._ Untrusted text can, at worst, produce a wrong structured fact — which grounding (§5.2), deterministic resolution (Stage 3), and human correction (§9) are all positioned to catch.

### 6.3 Required controls

Current practice prescribes a layered posture; CAIRN's mapping:

| Layer                               | Implementation                                                                                                              |
| ----------------------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| **Structural separation**           | Ingested content passed as clearly delimited data, **never concatenated into instruction context**                          |
| **Input guardrails on all traffic** | Screening at Stage 1, which every event already passes through                                                              |
| **Constrained output**              | **Every Stage 2 output validated against JSON schema before acceptance.** Free-form model text can never trigger an action  |
| **Least privilege**                 | No pipeline stage handling untrusted content holds tool access (§6.2)                                                       |
| **Output guardrails**               | Schema validation, policy checks (no system-prompt leakage), and **PII detection** on outputs                               |
| **Content provenance**              | Every fact carries its origin, so a suspect source is traceable and revocable                                               |
| **Constrained egress**              | Pipeline stages cannot make arbitrary outbound calls — exfiltration channels closed even if an injection partially succeeds |
| **Red-team regression**             | Injection attempts as permanent test cases in the golden dataset (file 10 §2.3)                                             |

### 6.4 Tenant isolation interaction

File 06 §4.3 identifies background-job tenant context as the sharpest infrastructure risk. **These two risks compound:** a successful injection inside a background job that has lost tenant context could reach across tenants. The controls in both files are jointly necessary — neither alone is sufficient.

---

## 7. Cost architecture

The business model needs AI cost under roughly $2.00/user/month. Achievable — but the gap between naive and optimized implementations is **10–50× per user.** Not a tuning exercise to defer.

### 7.1 The four levers

| Lever                | Effect                                                                                                                                                            |
| -------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Model routing**    | Premium-to-small tier cost differential is **100–300×** — the largest single lever. Stages 1–2 cheap, only Stage 4 premium                                        |
| **Prompt caching**   | **~90% savings on cache-hit tokens**, near-zero implementation cost, zero accuracy risk. Applies to stable context: roster, project structure, prompt scaffolding |
| **Batch processing** | Batching ~32 requests cuts per-token cost **~85%** for +20% latency                                                                                               |
| **Staged reduction** | Stage 4 sees a fraction of the tokens — **the architecture is the cost strategy**                                                                                 |

Documented outcome: routing, caching, and batching together took cost per answer **from $0.41 to $0.07 — an 83% reduction.**

### 7.2 Latency is a design input

Batching trades latency for cost — acceptable for daily briefs and documentation drafts, unacceptable for a live question. **Real-time paths bypass batching; scheduled paths use it.** This split exists in the architecture from the start.

### 7.3 Cost attribution is mandatory

Every call tagged by **feature, tenant, plan, region, model**. Without this, "AI costs are too high" is undiagnosable. Alert when per-user cost crosses threshold — before it reaches the P&L.

### 7.4 Pricing sanity check

The SaaS heuristic puts blended AI cost near **1/5 of price**, with hosting adding $1–3/user. At $12/user that implies a **~$2.40 AI ceiling** against a $1.20–1.80 target — consistent, but **without much margin.** The optimizations above are load-bearing. If real usage exceeds target, optimize first, reprice second.

---

## 8. Failure behavior

When confidence is insufficient, the system says so. It does not fill gaps with plausible inference.

- Insufficient data → state what is known and what is missing.
- Unresolvable conflict → surface both with sources; let the human decide.
- Low-confidence extraction → route to the person concerned for confirmation (file 05 §B.2.3 grants correction rights; this is the natural moment).

**A product principle, not an engineering fallback.** A tool that occasionally admits uncertainty is trusted. A tool that is confidently wrong once is not trusted again.

---

## 9. Human correction as a first-class input

File 05 §B.2.3 commits to employee-owned records, so correction is an _input_, not a UI affordance:

- Corrections supersede AI-derived facts in the temporal graph (§3.2).
- Corrections become evaluation data — real, labeled production failures, exactly what file 10 §2.1 requires.
- Repeated correction of one pattern is a quality alarm, not user error.
- **Corrections also serve as an injection tripwire** — a sudden rise in corrections concentrated on one source or author warrants investigation (§6).

This converts a trust commitment into compounding quality advantage: the product improves precisely where it has been wrong, on data no competitor holds.

---

## 10. Explicit non-capabilities

Restated here because this is where a well-meaning engineer would most plausibly add them:

- **No scoring, ranking, or productivity measurement** of individuals (file 05 §B.3.3, file 01 §2).
- **No work allocation** — CAIRN observes assignments humans made; it never proposes or routes work.
- **No inference about people** beyond observable work — no sentiment analysis, engagement scoring, or behavioral profiling.
- **No cross-tenant learning** — one customer's data never informs another's outputs or model behavior.

Boundaries with regulatory and contractual force (file 05 §B.3), not preferences.

---

## Decisions requested from founder

1. **Threat model (§6) — new and important.** Acknowledge prompt injection as a live risk to the core product, and confirm the architectural invariant: **no stage touching untrusted content may hold the capability to act.** _This constrains future design — any proposal to give the pipeline action capability must be evaluated against it._
2. **Temporal knowledge graph (§3)** — confirm over simple vector search, accepting design complexity for materially better multi-hop accuracy and correct handling of changing facts.
3. **Grounding as absolute (§5)** — confirm every claim carries provenance and unsupported claims are suppressed rather than caveated.
4. **Staged model routing (§2, §7.1)** — confirm the cheap/premium split, accepting pipeline complexity for the 100–300× cost differential the unit economics depend on.
5. **Context discipline (§4)** — confirm the bounded-retrieval approach over naive large-context stuffing, given documented lost-in-the-middle and context-rot effects.
6. **Latency/cost split (§7.2)** — confirm batching for scheduled outputs, real-time paths for live queries.
7. **Failure behavior (§8)** — confirm admitting uncertainty over confident completion, **even where it makes demos less impressive.** This choice will be tested by the temptation to demo well.
8. **Implementation (§3.3)** — confirm PostgreSQL + pgvector with relational graph modeling for v1, rather than a dedicated graph database prematurely.

---

_The staged architecture in §2 carries three loads simultaneously — cost, quality, and security. That convergence is the strongest signal it is the right design, and the strongest argument against eroding it for short-term convenience._
