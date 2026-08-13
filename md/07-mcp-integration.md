# Pillar 6 — MCP Client Support

**Status:** ✅ LOCKED — architectural clarification (§2) and security requirements (§4)
**Depends on:** [01-github-integration.md](01-github-integration.md) (reference integration pattern), [05-ux-design-privacy.md](05-ux-design-privacy.md), [09-understanding-layer.md](09-understanding-layer.md)
**Feeds into:** Year 2 connectors and verticals ([08-roles-and-industries.md](08-roles-and-industries.md))

**Founder's stated goal:** People should be able to authorize the tools they already use through MCP, with tracking still handled entirely inside CAIRN's own system.

---

## 1. The bet is validated — MCP is infrastructure, not speculation

| Signal                | Status                                                                                       |
| --------------------- | -------------------------------------------------------------------------------------------- |
| SDK downloads         | **97 million monthly** by March 2026, from ~100,000 at launch — a 970× increase in 18 months |
| Enterprise adoption   | **28% of Fortune 500** running MCP in production                                             |
| Official registry     | `registry.modelcontextprotocol.io` — **~9,650 servers**, ~29,000 server/version records      |
| Registry backing      | Anthropic, GitHub, Microsoft, PulseMCP                                                       |
| Current specification | **2026-07-28**, including authorization hardening                                            |

The founder's instinct was correct: this is adopting infrastructure a quarter of the Fortune 500 already runs, not betting on an unproven standard.

---

## 2. Architectural clarification — what MCP is actually for

This is the most important correction in this file, and it changes MCP's role in the roadmap.

**MCP is designed for on-demand pull, not continuous streaming.** Current guidance is explicit:

> _"For most MCP use cases, on-demand fetching is the right default, since AI agents typically don't need every tick of a data stream — they need the current state or a recent summary when they decide to look."_

**CAIRN's core requirement is the opposite.** Files 01–03 depend on _continuous capture_ — every commit, message, and meeting as it happens — because the product's promise is that nothing is missed without anyone doing manual work. That is a webhook-driven, push-based architecture.

### 2.1 What this means practically

| Need                                                                                  | Correct mechanism                        | Not MCP because                                                      |
| ------------------------------------------------------------------------------------- | ---------------------------------------- | -------------------------------------------------------------------- |
| Continuous activity capture (files 01–03)                                             | **Webhooks** — push, real-time, complete | MCP's pull model would require polling, missing events between polls |
| On-demand enrichment — "fetch the full content of this document the brief references" | **MCP**                                  | Exactly the on-demand pattern MCP is built for                       |
| Periodic state sync — current project list, roster, board state                       | **MCP**                                  | State snapshots, not event streams                                   |
| Long-tail tool connections where building a webhook integration isn't justified       | **MCP**                                  | Standard interface beats bespoke integration for low-volume sources  |

**Revised positioning:** MCP is not the universal connector that replaces per-tool integration work. It is a **complement** that makes _breadth_ cheap — the long tail of tools a customer wants connected — while webhooks remain the mechanism for the _depth_ sources the product depends on.

This does not diminish the founder's goal. It sharpens it: MCP is how CAIRN says yes to "can you connect X?" for dozens of tools without dozens of bespoke integrations. It is not how CAIRN tracks GitHub.

---

## 3. Strategic rationale

- Makes the long tail of connectors affordable — directly serving the Year 2 verticals in file 08 §C, where agencies and consultancies use tools CAIRN would never build bespoke integrations for.
- One consistent authorization experience across every MCP-supported source.
- Aligns with infrastructure already at enterprise scale (§1).

---

## 4. Security — this section is not boilerplate

MCP's adoption has outpaced its security maturity, and the published data is genuinely alarming. **OWASP now maintains an MCP Security Cheat Sheet**, and the US Department of Defense has issued MCP security guidance — both signals that this is a recognized risk surface, not theoretical concern.

### 4.1 The vulnerability landscape

| Finding                                                     | Prevalence |
| ----------------------------------------------------------- | ---------- |
| **Command injection** in tested MCP servers                 | **43%**    |
| **Path traversal** in implementations using file operations | **82%**    |
| Servers with _some_ security finding in broad scans         | **66%**    |
| Tool poisoning observed in academic study                   | ~5.5%      |

**Two-thirds of scanned MCP servers have a security finding.** Any policy that treats "it's an MCP server" as equivalent to "it's safe" is indefensible.

### 4.2 The threat classes that matter for CAIRN

**Tool poisoning** — malicious instructions hidden in tool descriptions, parameter schemas, or return values, designed to manipulate the consuming LLM. Because CAIRN feeds MCP output into its Understanding layer, a poisoned tool description is a direct injection path into CAIRN's AI pipeline.

**Rug pull** — a server changes its tool definitions _after_ the user has approved it. This is not hypothetical: the **Postmark backdoor** followed exactly this pattern — previously clean code, then malicious code, same package name, same publisher.

**Supply chain compromise** — the **official `nx` npm packages were briefly modified to exfiltrate authentication tokens from developer machines, including GitHub tokens, npm tokens, and Anthropic API keys cached in environment variables.** CAIRN holds precisely these credential types.

**Confused deputy** — documented **one-click account takeover** vulnerabilities in OAuth-based MCP flows. CAIRN would hold delegated access to customers' GitHub, chat, and document systems; a confused-deputy compromise could be leveraged against _the customer's_ systems, not merely CAIRN's data. This risk profile is more severe than a typical integration bug.

**Shared token patterns** — where one token serves all users, every action appears under one identity in audit logs, and a single compromise exposes the whole organization. This directly conflicts with file 05 §B.2's employee-owned-records and correction-rights commitments, which require knowing _whose_ authorization produced a given data flow.

### 4.3 Required controls

| Control                                     | Requirement                                                                                                                                                                                                                                     |
| ------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Token scope**                             | Read-only wherever the server supports it. CAIRN observes; it does not act.                                                                                                                                                                     |
| **Token identity**                          | Per-user, per-tenant. **Never a shared token.**                                                                                                                                                                                                 |
| **Token lifecycle**                         | Short-lived with rotation; no long-lived static credentials. Encrypted at rest with per-tenant key derivation (file 06 §7).                                                                                                                     |
| **Authorization**                           | OAuth 2.1 with PKCE; MCP servers act as resource servers validating tokens from an external authorization server. **Note:** PKCE protects token-exchange integrity but does **not** prove requester identity — it is necessary, not sufficient. |
| **Tool-definition pinning**                 | **Cryptographic hashes pin approved tool definitions; any change alerts and suspends the connection pending re-review.** This is the specific, published mitigation for rug pulls.                                                              |
| **Treat all MCP output as untrusted input** | See §4.4                                                                                                                                                                                                                                        |
| **Audit**                                   | Every MCP-mediated access logged with the authorizing identity (file 05 §B.2(3))                                                                                                                                                                |
| **Spec currency**                           | Track 2026-07-28 or later; authorization hardening is active work and lagging revisions inherit known weaknesses                                                                                                                                |
| **Security review per server**              | Independent review before enablement — registry listing is not a substitute (§5)                                                                                                                                                                |

### 4.4 Prompt injection — a risk that exists with or without MCP

**This deserves attention beyond this file.** CAIRN ingests untrusted content by design: pull request descriptions, chat messages, meeting transcripts, and issue text — all written by people, some of whom may be adversarial, and all of it fed into an LLM pipeline.

**Indirect prompt injection** — malicious instructions embedded in data sources rather than user input — is therefore a live risk for CAIRN's core product, not only for its MCP connections. A crafted PR description could attempt to manipulate the summarization stage into fabricating content, exfiltrating context, or suppressing legitimate activity.

**Required mitigations, applicable across all pillars:**

1. **Structural separation** — ingested content is passed as clearly delimited data, never concatenated into instruction context.
2. **Constrained output** — extraction stages emit schema-validated structured output (file 09 Stage 2), which sharply limits what an injection can achieve.
3. **No tool access from ingestion paths** — the pipeline stages that process untrusted content have no ability to take actions, only to produce structured facts.
4. **Grounding verification** — span-level checking (file 09 §4.2) catches claims unsupported by source evidence, which is what a successful injection would produce.

**Action item:** this belongs in file 09 as a first-class threat model section, not only here. Flagged for that file's next revision.

---

## 5. Server vetting and supply chain

The **official MCP Registry** provides the vetting mechanism the earlier draft lacked — but given §4.1, registry presence establishes _discoverability, not safety._

**Policy:**

- Supported servers must be listed in the official registry.
- **Vendor-published servers strongly preferred** (GitHub's own, Notion's own) over community implementations.
- **Independent security review before enablement**, weighted toward the specific classes in §4.1 — command injection and path traversal above all.
- **Version pinning, mandatory.** Unpinned dependencies on third-party servers are an uncontrolled change surface, and the rug-pull and npm findings in §4.2 make this concrete rather than theoretical.
- **Tool-definition hash pinning** with change alerting (§4.3).
- **Periodic re-review** of enabled servers — a server safe at enablement may not remain so.

---

## 6. Implementation specification

### 6.1 Transport

**Streamable HTTP** for remote servers — a single endpoint accepting JSON-RPC over POST, optionally returning SSE streams. Implementation requirements: handle both `application/json` and `text/event-stream` responses, capture and echo `MCP-Session-Id`, send `MCP-Protocol-Version`, re-initialize on `404`, and issue a best-effort `DELETE` on disconnect.

`stdio` transport is local-only and not relevant to CAIRN's server-side architecture.

### 6.2 Deprecations to avoid

**As of the 2026-07-28 specification, Roots, Sampling, and Logging are deprecated.** They continue to work for at least twelve months, but **new implementations should not adopt them.** Server-to-client request patterns are being redesigned around Multi Round-Trip Requests (MRTR), removing the need for persistently open bidirectional streams.

**Consequence:** because CAIRN is building fresh, it should skip these entirely rather than adopting and later migrating — a meaningful advantage of starting now rather than having built in 2025.

### 6.3 Data handling

MCP-sourced and webhook-sourced data normalize into the identical `ActivityEvent` schema (file 01 §7). The Understanding layer has no awareness of which path delivered an event. All file 05 commitments apply identically regardless of connection method.

---

## 7. Out of scope

**CAIRN exposing its own MCP server** — letting external AI agents query CAIRN's understanding layer — is the inverse role and distinct work. It has natural adjacency to file 04 §6 (AI agents already consume CAIRN-generated documentation) and is a genuine Year 2 opportunity, but it is not client-side scope and should not be conflated in estimation.

---

## 8. Sequencing

Built after file 01 is stable. Given §2, MCP is explicitly **not** on the critical path for MVP — it accelerates breadth after the depth sources work. Its natural moment is when the first customer asks to connect a tool CAIRN does not natively support.

---

## Decisions requested from founder

1. **Architectural role (§2) — the significant one.** Confirm MCP is positioned as the **breadth** mechanism (long-tail connectors, on-demand enrichment, periodic sync) rather than the universal connector replacing webhook-based capture. This is a correction to the earlier framing and affects roadmap expectations.
2. **Security controls (§4.3) as mandatory** — acknowledge the vulnerability data (43% command injection, 82% path traversal, 66% with some finding) and approve the full control set including **tool-definition hash pinning**, per-user tokens, and per-server security review.
3. **Prompt injection threat model (§4.4)** — acknowledge this as a product-wide risk requiring treatment in file 09, not an MCP-specific concern. _This is arguably the most important finding in this file, since it applies to the core product with or without MCP._
4. **Vetting policy (§5)** — confirm registry listing plus vendor preference plus independent review plus version pinning, accepting that this makes adding each MCP server slower than a naive integration.
5. **Skip deprecated features (§6.2)** — confirm Roots, Sampling, and Logging are not adopted, taking advantage of building fresh against the current specification.
6. **Launch timing** — confirm fast-follow rather than v1 requirement, now reinforced by §2.
7. **First MCP-connected source** — Notion and Linear are leading candidates; final choice should follow customer signal.

---

_Sections 2 (architectural role) and 4.4 (prompt injection) are the findings that matter most here. The first corrects a roadmap assumption; the second identifies a risk that exists in CAIRN's core product independent of whether MCP is ever shipped._
