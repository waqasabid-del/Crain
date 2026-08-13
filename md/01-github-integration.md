# Pillar 1 — GitHub Integration & Code Activity Intelligence

**Status:** ✅ LOCKED — decisions resolved, ready for implementation
**Depends on:** [05-ux-design-privacy.md](05-ux-design-privacy.md) (consent, per-repo opt-out, no-scoring commitment), [06-infrastructure.md](06-infrastructure.md)
**Feeds into:** [04-auto-documentation.md](04-auto-documentation.md), [07-mcp-integration.md](07-mcp-integration.md)

**Founder's stated goal:** GitHub should be connected to CAIRN so it tracks everything happening there automatically.

---

## 1. Competitive context — what we are actually competing against

The original product proposal identified project management tools (Jira, Linear, Asana) as the competitive set. For this pillar specifically, that is incomplete. There is a mature, well-funded category — **engineering intelligence platforms** — that already reads GitHub data and sells insight from it. Any claim that CAIRN's GitHub tracking is differentiated must be measured against these, not against Jira.

| Platform                           | What it does with GitHub data                                                                                                               | Primary buyer                                         |
| ---------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------- |
| **Swarmia**                        | DORA + SPACE metrics, developer experience surveys, team "working agreements" (PR size, review turnaround norms), AI-assisted-PR detection  | Engineering leadership, with deliberate IC visibility |
| **LinearB**                        | Git analytics plus workflow automation — automated PR routing, AI-generated PR descriptions, code review assistance inside the PR lifecycle | Engineering managers                                  |
| **Jellyfish**                      | Engineering investment allocation — "where is our engineering spend going," framed for board-level reporting                                | CTO / VP Engineering                                  |
| **Waydev, DX, Uplevel, Allstacks** | Variations on delivery metrics, flow efficiency, and productivity benchmarking                                                              | Engineering leadership                                |

### 1.1 The strategic gap CAIRN occupies

Every platform above shares three characteristics that define the category — and each one is an opening:

1. **They are dashboards, not narratives.** Their output is charts, scores, and trend lines requiring interpretation by someone fluent in engineering metrics. CAIRN's output is plain-English prose readable by a founder, a designer, or a marketing lead with no engineering vocabulary. This is not a cosmetic difference; it determines who in a company can actually use the product.
2. **They are sold to management, about developers.** The buyer is an engineering leader purchasing visibility _into_ their team. CAIRN's design commitments (file 05 — symmetrical visibility, employee-owned records, no comparative scoring) invert this: the team sees what leadership sees. This is a genuinely different product posture, not a feature difference, and it is defensible precisely because an incumbent whose entire value proposition is a management dashboard cannot adopt it without abandoning their positioning.
3. **They are engineering-only.** They read Git and issue trackers. They do not integrate meetings, conversation, and documentation into one picture of a team. CAIRN's four-pillar scope means GitHub activity is _one input among several_ — a PR merged after a decision made in a meeting and discussed in chat becomes one coherent story rather than four disconnected records. No engineering intelligence platform can produce that, because they never captured the other three sources.

**The honest risk:** these platforms are established, well-funded, and technically competent at the GitHub-reading layer specifically. CAIRN does not win this pillar by reading GitHub _better_ than Swarmia. It wins by reading GitHub _correctly_ (Sections 4–5) and then doing something structurally different with the result. Parity on ingestion quality is the entry requirement; the differentiation is everything downstream of it.

---

## 2. Design stance — why CAIRN deliberately does not produce productivity metrics

This pillar could easily produce commit counts, lines-of-code totals, and per-developer throughput charts. It will not, and this is a considered product decision with substantial evidence behind it.

**Goodhart's Law** — "when a measure becomes a target, it ceases to be a good measure" — is not a theoretical concern in engineering measurement; it is the documented history of the field. Lines of code became the dominant productivity proxy in the 1970s, and the consequences are well established: once LOC became a target, code grew more verbose, deletion became professionally risky, and refactoring registered as _negative_ productivity. A developer solving a concurrency problem in 40 lines produces more value than one writing 400 lines of boilerplate; an engineer removing 2,000 lines of dead code shows up as deeply unproductive. Commit-count targets produce dozens of trivial commits. Every metric in this family degrades the behavior it measures.

**CAIRN's position:** activity is captured as _evidence for a narrative_, never as a _score_. The system may state "the authentication refactor shipped Tuesday after review from two engineers"; it will never state or imply "Developer A produced 40% more than Developer B." This directly implements file 05's non-negotiable no-scoring commitment, and — usefully — it is also simply the better engineering practice, independent of the trust argument.

---

## 3. Authorization: GitHub App, not OAuth App — settled

GitHub's own documentation recommends the GitHub App model for production integrations. The specifics map directly onto CAIRN's requirements:

| Factor                 | OAuth App                                           | GitHub App                                                       |
| ---------------------- | --------------------------------------------------- | ---------------------------------------------------------------- |
| Acts as                | The authorizing user                                | The app itself, as a first-class GitHub identity                 |
| Permission granularity | Broad, user-level scopes                            | Fine-grained — 50+ distinct permissions, settable per repository |
| Revocation             | Tied to an individual user's access                 | Org admin revokes per repository, centrally                      |
| REST rate limit        | Lower, and **shared with the user's own API usage** | **15,000 requests/hour per installation**, isolated              |

The rate-limit isolation alone is decisive: an OAuth-based integration would compete with the customer's own engineers and CI systems for API quota, degrading their tooling as a side effect of installing CAIRN. That is an unacceptable product outcome. Combined with per-repository revocability — which file 05's opt-out commitment strictly requires — the GitHub App model is the only viable choice.

**Permission posture:** CAIRN requests read-only permissions wherever GitHub's model allows, and never requests write access. CAIRN observes; it does not modify the customer's repository. This is stated explicitly in the app's permission request so that a security-conscious admin can verify it at install time rather than take it on trust.

---

## 4. Ingestion architecture — production-grade reliability

### 4.1 Webhook handling: verify → enqueue → acknowledge

GitHub documents that webhook delivery is not perfectly reliable — consumers must expect duplicate deliveries, occasional gaps, and delayed retries. The ingestion service is therefore built to the established production pattern rather than a naive listener:

1. **Verify first.** Every payload is checked against its HMAC signature (registered at App creation) before any processing. Inbound traffic is additionally restricted to GitHub's published IP ranges at the gateway layer, ahead of signature verification.
2. **Acknowledge fast.** GitHub expects a `2xx` within **10 seconds**. The handler enqueues and returns immediately; normalization and AI handoff happen asynchronously, never in the request path.
3. **Consume idempotently.** Each delivery carries a unique delivery ID, used as an upsert key — a duplicate delivery updates the existing record rather than creating a second one.
4. **Reconcile, don't just retry.** Failed processing uses exponential backoff with jitter, routing to a dead-letter queue after exhausting attempts so nothing is silently lost. A scheduled reconciliation job periodically compares recent GitHub state against CAIRN's records to detect and repair gaps left by dropped deliveries — this is the difference between an integration that is _usually_ right and one that is _verifiably_ right.

### 4.2 API strategy: hybrid REST + GraphQL under a point budget

GitHub enforces two independent quota systems, and using only one wastes available capacity:

| Limit type                   | REST                                              | GraphQL                                               |
| ---------------------------- | ------------------------------------------------- | ----------------------------------------------------- |
| Primary quota                | 15,000 req/hour per installation                  | Point-based, priced by query complexity               |
| Points per minute            | 900                                               | 2,000                                                 |
| Conditional requests (ETags) | Supported — **304 responses don't consume quota** | Not supported                                         |
| Cost visibility              | Response headers                                  | `rateLimit` block returns the query's own cost inline |

**Approach:** route each workload to the cheaper API for that specific job. Bulk historical backfill uses GraphQL, where one well-shaped query replaces many REST round-trips. Polling and freshness checks use REST with ETags, where unchanged resources return `304` and cost nothing against quota. Every GraphQL query includes a `rateLimit` block so actual cost is measured rather than estimated.

**Secondary limits are the real constraint at scale** and are frequently missed: no more than **100 concurrent requests** shared across both APIs, and no more than **90 seconds of CPU time per 60 seconds of real time** (of which at most 60 seconds may be GraphQL). Backfill concurrency is therefore governed by a global scheduler enforcing these ceilings across all tenants — not by per-tenant worker counts, which would breach the shared limit as the customer base grows.

**Pagination:** page size is set explicitly to the maximum (100) rather than accepting the default (30), reducing round-trips by roughly 3× on every paginated traversal.

---

## 5. Attribution correctness — the quality moat

This section is where most GitHub integrations quietly fail, and where CAIRN earns credibility. If the system misattributes work, every downstream summary, brief, and document inherits the error — and a founder who catches one wrong attribution stops trusting the entire product. Accuracy here is not a technical nicety; it is the foundation of the trust the product is sold on.

### 5.1 Squash-merge attribution

Squash merging is the default workflow at most modern teams, and it historically destroyed attribution: whoever opened the PR became the sole author of the squashed commit, erasing every other contributor. GitHub improved this in 2019 by automatically crediting all commit authors as `Co-authored-by` trailers on the squash commit.

**Requirement:** CAIRN parses `Co-authored-by` trailers as first-class attribution data, not as commit-message text. A pairing session, a colleague's fix pushed onto a branch, or a mob-programming session must credit every participant. Reading only the commit author field — the naive implementation — systematically erases collaborative work, which would directly contradict the "non-code and collaborative contribution is surfaced deliberately" commitment in file 05.

### 5.2 Bot and automation noise

Automated accounts generate enormous volume with near-zero human signal. Dependabot, Renovate, release bots, and CI accounts can easily out-commit every human on a team. Worse, GitHub's squash behavior adds `Co-authored-by` lines carrying the _bot's_ identity, meaning naive co-author parsing (Section 5.1) actively imports bot noise into human attribution.

**Requirement:** maintain an explicit bot-identity registry (accounts with the `[bot]` suffix, GitHub App actors, and a configurable per-tenant list for custom automation). Bot activity is retained as _repository context_ — "dependencies were updated," useful for a project summary — but is strictly excluded from _human contribution attribution_. Both the author field and every parsed co-author trailer are filtered through this registry.

### 5.3 Identity resolution

The same person routinely appears under multiple identities: a work email in commits, a personal email on weekend contributions, a GitHub handle, and a display name that differs from all three. Unresolved, one person fragments into three partial contributors — each with an incomplete, misleading record.

**Requirement:** an identity graph resolving GitHub handles, commit author emails, and co-author trailer emails to a single CAIRN person record, with a user-facing merge/split control. Consistent with file 05's employee-owned-records principle, each individual can review and correct their own identity mappings — the system proposes, the person confirms.

### 5.4 AI-authored code attribution

This is the newest and most consequential attribution problem, and it is actively reshaping the engineering measurement category. Current estimates place AI-generated code at **30–70% of committed code**, which has partially invalidated the assumptions underneath conventional delivery metrics — deployment frequency and lead time become misleading when a substantial share of code is machine-generated. Competitors have already responded: Swarmia ships AI-assisted-PR detection for Copilot, Cursor, and Claude Code.

The detection landscape, honestly assessed:

- **Reliable signals exist but are partial.** Agent-driven work often commits under identifiable bot actors (Copilot Workspace commits as `github-copilot[bot]`), and recent research fingerprinting five major coding agents across 33,580 pull requests achieved a 97.2% F1 score using 41 features spanning commit message structure, PR shape, and code characteristics.
- **Heuristic detection has a hard ceiling.** Inline assistant suggestions leave no marker, engineers routinely edit AI output before committing, and model behavior shifts continuously — patterns identifying one model may not identify its successor. Genuinely reliable attribution would require observing authorship at commit time on the developer's machine, which means a client-side install.

**CAIRN's position — deliberately restrained:** capture the _reliable_ signals (identifiable agent actors, explicit trailers, structural fingerprints) and represent AI involvement as **context on the work, never as a judgment about the person**. CAIRN will not attempt probabilistic "was this human-written?" scoring of individual contributions. That capability, even if technically achievable, would convert the product into exactly the surveillance instrument file 05 forbids — and would be wrong often enough to destroy trust the first time it accused someone incorrectly. The restraint here is a positioning asset, and should be stated publicly as such.

---

## 6. Signals captured

### 6.1 v1

- **Commits** — message, diff statistics, files touched, branch, full author and co-author attribution.
- **Pull requests** — opened, reviewed, commented, merged, or closed without merge.
- **Code review activity** — who reviewed, and review turnaround time.
- **Issues** — created, assigned, closed, and linkage to related pull requests.
- **CI/CD status** — build outcomes and deployment events, distinguishing "shipped" from "in progress."

### 6.2 v2 (once v1 is proven in production)

- Branch lifetime and stale-branch detection, surfacing stuck work.
- Review substance signals — distinguishing a considered review from a rubber-stamp approval.
- Non-coding contribution visible through GitHub — documentation commits, unblocking review comments, issue triage.

### 6.3 Content handling — metadata over raw source

Raw diffs and full commit content are **not** sent to the AI layer by default. Only metadata and diff statistics (files changed, lines added/removed, commit message) are processed automatically. Full diff content is retrieved on demand only — for example, when a user explicitly asks what changed in a specific change. This keeps AI cost proportionate to the product's purpose (understanding work, not auditing code) and — more importantly — avoids routing customers' proprietary source code through the AI pipeline as a matter of routine. This is a meaningful security posture worth stating explicitly in sales conversations.

---

## 7. Historical backfill and normalization

| Aspect        | Approach                                                                                                                                             | Rationale                                                                                                                                                                                                   |
| ------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Backfill      | GraphQL bulk pull on first connection, capped at 90 days by default (configurable), executed under the global concurrency scheduler from Section 4.2 | A populated, useful view on day one rather than an empty dashboard — supporting the sub-30-minute time-to-value target in file 05 — without breaching shared secondary rate limits during onboarding spikes |
| Normalization | Every event converted into the shared `ActivityEvent` schema (actor, resolved identity, timestamp, type, project, summary, source link, confidence)  | The identical schema used by chat, meetings, and documentation, so the single shared Understanding layer (decided in file 00, Section 6) operates on one consistent shape rather than source-specific logic |

---

## 8. MVP scope

Commits, pull requests, and code reviews — with correct attribution per Section 5 — are sufficient to produce a genuinely useful first summary. Issues and CI/CD status follow shortly after, reusing the same webhook infrastructure at minimal additional cost.

**Explicitly included in MVP, not deferred:** squash-merge co-author parsing, bot filtering, and identity resolution (Sections 5.1–5.3). These are not polish. An integration that misattributes work from day one produces summaries a team will not trust, and trust lost during a pilot is not recoverable by a later fix.

---

## 9. Compliance alignment (per file 05, Section B.6)

- **Off by default** — no repository is tracked until the organization explicitly installs and configures the GitHub App.
- **Per-repository opt-out** — contributors or teams can exclude specific repositories (for example, personal projects hosted under a work organization).
- **Read-only, minimum-scope permissions** — verifiable by the customer at install time.
- **No comparative scoring** at any point in the pipeline (Section 2).
- **Individual correction rights** — each person can review and correct their own identity mappings and attribution record (Section 5.3).

---

## Decisions requested from founder

1. **Platform scope for v1:** GitHub only, or GitLab/Bitbucket parity from launch. _Recommendation: GitHub-only_ — matches the target customer profile and avoids splitting integration effort before the core product is proven.
2. **Per-repository opt-out:** confirm contributors can exclude specific repositories. _Recommendation: yes_, required under file 05.
3. **Backfill window:** confirm 90 days as the default on first connection.
4. **Diff content policy:** confirm full diff content is retrieved only on explicit request, never processed by default.
5. **AI-attribution posture (new):** confirm the restrained position in Section 5.4 — capture reliable AI-involvement signals as context, decline to build probabilistic human-vs-AI scoring of individuals. _Recommendation: confirm_, and treat the restraint as a public positioning asset rather than a missing feature.

Sections 3 (authorization), 4 (ingestion architecture), and 5 (attribution correctness) are settled engineering standards rather than open questions. They require awareness, not sign-off — but Section 5 in particular should be understood as the pillar's actual competitive moat: correctness that competitors' dashboards can match only by rebuilding their attribution layer.

---

_Once confirmed, this file moves from Draft to Locked, and becomes the reference implementation pattern for how [07-mcp-integration.md](07-mcp-integration.md) and all future source integrations normalize into the shared `ActivityEvent` schema._
