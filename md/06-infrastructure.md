# Infrastructure & Platform Architecture

**Status:** ✅ LOCKED — includes frontend correction (§2.1) and region/residency decisions (§6)
**Depends on:** [05-ux-design-privacy.md](05-ux-design-privacy.md) (residency, isolation, compliance), [09-understanding-layer.md](09-understanding-layer.md) (AI workload shape)
**Governs:** Where every pillar's data lives, runs, and is protected

**Decision (founder):** Frontend on Cloudflare. AI and backend on GCP.

This is a sound split. Cloudflare is best-in-class for globally distributed frontend delivery; GCP is a strong home for AI and data workloads, with Claude available natively through Vertex AI — keeping the AI supply chain inside one vendor relationship.

**The governing principle of this file:** the decisions that are expensive to reverse are made correctly now. Tenant isolation (§4.2), per-tenant region assignment (§6), and audit logging (§9) cannot be retrofitted cheaply once real customer data exists. Everything else can evolve.

---

## 1. Architecture at a glance

```
                    ┌─────────────────────────────┐
   Users ──────────▶│  CLOUDFLARE                 │
                    │  Workers (OpenNext/Next.js) │
                    │  WAF · DDoS · Access · geo  │
                    └──────────────┬──────────────┘
                                   │ HTTPS
                    ┌──────────────▼──────────────┐
                    │  GCP                        │
   Webhooks ───────▶│  Cloud Run (API + workers)  │
   (GitHub,         │  Pub/Sub · Cloud Tasks      │
    Slack,          │  Cloud SQL (Postgres+RLS)   │
    Workspace)      │  Vertex AI (Claude)         │
                    │  Secret Manager · KMS       │
                    └─────────────────────────────┘
```

---

## 2. Frontend — Cloudflare

### 2.1 Correction: Workers with OpenNext, not Pages

The previous draft specified **Cloudflare Pages**. That guidance is now outdated:

> **Cloudflare now recommends deploying Next.js applications using OpenNext with Cloudflare Workers, not Cloudflare Pages.** The `@opennextjs/cloudflare` adapter has matured and supports the App Router, Server Actions, and Partial Prerendering.

**Adopt Workers + OpenNext.** Choosing Pages now would mean migrating later, against the vendor's own recommendation.

### 2.2 Platform limits that constrain design

| Limit                | Value                                           | Implication                                                       |
| -------------------- | ----------------------------------------------- | ----------------------------------------------------------------- |
| Worker bundle size   | **3 MiB** (free) / **10 MiB** (paid)            | Frontend bundle discipline is a hard constraint, not a preference |
| CPU time per request | **30 ms** subroutine mode / **30 s** standard   | **No heavy computation at the edge** — all AI work belongs on GCP |
| Cold start           | **<3 ms at P99**                                | Effectively negligible; not a design concern                      |
| Builds               | 500/month free, 5,000/month on the $5 paid plan | Adequate; monitor if CI becomes chatty                            |

The 30 ms CPU limit reinforces the split already implied by the architecture: **Cloudflare serves and routes; GCP thinks.**

### 2.3 Edge capabilities used

- **Geo-detection at the edge** — identifies a visitor's country _before_ the request reaches the backend, directly serving the region-aware compliance defaults in file 05 §B.5.
- **WAF and DDoS protection** — strong baseline at near-zero engineering cost, meaningful given data sensitivity.
- **Cloudflare Access** — gates non-production deployments behind identity (Google, GitHub, or any OIDC provider). Staging environments containing real-shaped data must never be publicly reachable; this is also a SOC 2 access-control expectation (§10).

### 2.4 Known constraint

Not all Next.js features are supported on the Workers runtime; `next/image` requires additional configuration or delegation to Cloudflare Images. Verify feature compatibility during the architecture RFC rather than discovering gaps mid-build.

---

## 3. Compute — GCP Cloud Run

Cloud Run over GKE for at least the first 12 months: autoscaling, pay-per-use, and low operational overhead, appropriate to team size. Kubernetes is an escalation path, not a starting point.

### 3.1 The most common production mistake — and how to avoid it

> **Leaving `max-instances` uncapped is the most common Cloud Run production mistake.** A traffic spike can start hundreds of instances in seconds, **exhausting database connection pools and causing cascading failures** before cost even becomes the concern.

This is a direct risk for CAIRN: webhook traffic is inherently spiky. A customer merging a large branch, or a busy Slack workspace, produces bursts that would scale Cloud Run aggressively straight into Cloud SQL's connection limit.

**Required controls:**

- **`max-instances` set explicitly on every service.** Non-negotiable, treated as a deploy-time check.
- **Connection pooling** in front of Cloud SQL (PgBouncer or Cloud SQL Proxy with pooling), so instance count and connection count are decoupled.
- **Queue-based buffering** — webhooks enqueue and return immediately (file 01 §4.1), converting spikes into queue depth rather than instance count. The ingestion design already does this; the point is that it is a _reliability_ control, not only a latency one.

### 3.2 Concurrency tuning

Concurrency is the number of simultaneous requests one instance handles before Cloud Run scales out. **Lower concurrency means more instances, more cold starts, and higher cost**; higher concurrency absorbs spikes on existing instances.

CAIRN's split:

- **API services** (user-facing, low CPU per request) — higher concurrency.
- **Pipeline workers** (LLM calls, memory-heavy) — lower concurrency, since one instance handling many concurrent LLM calls risks memory pressure and unpredictable latency.

**Minimum instances** are set on user-facing services only, where cold-start latency is visible to a person. Background workers tolerate cold starts and should not pay to avoid them.

---

## 4. Data layer — PostgreSQL on Cloud SQL

### 4.1 Multi-tenancy model

The 2026 default is **shared schema with PostgreSQL Row-Level Security (RLS)** — all tenant data in the same tables with a `tenant_id` column, and RLS filtering unauthorized rows at the database layer. It scales well, simplifies operations, and provides isolation guarantees that satisfy most compliance requirements.

**CAIRN adopts shared schema + RLS**, with the hybrid option (dedicated resources for a large or highly regulated tenant) available later without redesign — the standard escalation path.

### 4.2 RLS is a safety net, not the primary control

Policies enforce `tenant_id = current_setting('app.current_tenant_id')::uuid`, with tenant context set per request in middleware.

**The genuinely hard parts, which practitioners identify explicitly:**

| Challenge                                              | CAIRN's exposure        | Control                                                                                          |
| ------------------------------------------------------ | ----------------------- | ------------------------------------------------------------------------------------------------ |
| Making filtering automatic so it cannot be forgotten   | High — many query paths | Tenant scoping enforced in the data-access layer; raw unscoped queries prohibited by lint/review |
| **Propagating tenant context through background jobs** | **Very high**           | See §4.3                                                                                         |
| Scoping cache keys                                     | Medium                  | Every cache key namespaced by tenant, enforced by a shared helper rather than convention         |
| Explicitly testing cross-tenant isolation              | High                    | Automated tests attempting cross-tenant access must fail; part of CI, not manual QA              |

### 4.3 The background-job risk — CAIRN's sharpest isolation exposure

Tenant context propagation through background jobs is a documented hard problem, and **CAIRN is almost entirely background jobs.** Every webhook, every pipeline stage (file 09 §2), every scheduled brief runs outside a user request — the exact context where `current_setting('app.current_tenant_id')` is not set by default.

**A background job that forgets tenant context does not fail loudly. It silently reads across tenants.** For a product whose entire proposition is trust, this is the single most severe technical risk in the architecture.

**Required controls:**

1. **Tenant ID is a mandatory field on every queued message.** No job payload schema permits its absence.
2. **A single job-execution wrapper** sets tenant context before any handler code runs. Handlers never set it themselves.
3. **Fail closed** — a job whose tenant context cannot be established errors out rather than executing unscoped.
4. **Cross-tenant leakage tests in CI**, including background-job paths specifically, not just API paths.

### 4.4 Vector search — pgvector and its ceiling

File 09 §3.4 specifies pgvector for graph entry-point search. The limits should be understood now rather than discovered at scale:

| Constraint               | Detail                                                                                                                       |
| ------------------------ | ---------------------------------------------------------------------------------------------------------------------------- |
| **Practical ceiling**    | Performance degrades noticeably **beyond 10–20 million vectors**, depending on dimensionality and hardware                   |
| **Memory**               | ~**8–16 GB working memory for 5M vectors at 1536 dimensions**; beyond ~10M, memory pressure becomes a central design concern |
| **HNSW dimension limit** | **2,000 dimensions** — a real constraint on embedding model choice                                                           |
| **Degradation mode**     | Once the index exceeds cache, random access and p99 tail latency rise sharply as pages come from disk                        |

**Assessment for CAIRN:** comfortably sufficient for v1 and well beyond. Activity events per team are modest, and the temporal graph (file 09 §3) means vector search is an _entry point_ rather than the primary retrieval mechanism — reducing dependence on it.

**Escalation path when needed:** `pgvectorscale` (DiskANN-based) extends Postgres to the low hundreds of millions of vectors without leaving the ecosystem. **Do not adopt a separate vector database prematurely** — it adds an operational system for a problem CAIRN will not have for a long time.

**Embedding model constraint:** the 2,000-dimension HNSW limit must be checked against the chosen embedding model before selection, not after.

---

## 5. AI access — Claude via Vertex AI

### 5.1 Pricing parity confirmed

Claude on Vertex AI uses the **same base rates as the direct Anthropic API**, and both **prompt caching and the 50% Batch API discount are available** — meaning the cost optimizations file 09 §5 depends on carry over intact.

### 5.2 Caveat: regional endpoints cost ~10% more

Vertex offers global and regional endpoints; **regional carries roughly a 10% premium** ($3.00 → $3.30 per MTok input).

> **EU data residency requires regional endpoints, so EU customers cost ~10% more to serve in AI spend.**

Not a reason to weaken residency — a cost to price or absorb deliberately. **Mitigation is architectural:** route per tenant. US tenants use global endpoints; EU tenants use `europe-west` regional. Region is already a per-tenant value (§6), so no new mechanism is needed.

### 5.3 Caveat: model availability lags

New Claude models reach the direct Anthropic API first; **Vertex can lag by weeks or months.** Manageable — CAIRN does not need same-week model access, and the evaluation harness (file 10) requires re-validation before adopting any new model regardless.

**Required mitigation:** build the LLM access layer behind an internal abstraction from day one, so provider is a configuration choice. Switching a subset of traffic to the direct Anthropic API then becomes a config change, not a refactor. This costs almost nothing now and preserves optionality.

### 5.4 Why Vertex remains the default

Billing consolidates into GCP, access is governed by IAM, audit logs land in Cloud Logging, and residency is managed cloud-side. For a product whose enterprise motion involves AI-governance review (file 05 §B.6), **one vendor with unified audit logging is a materially easier compliance story than two.**

---

## 6. Data residency and regions — **[DECIDED]**

### 6.1 Market sequence drives region strategy

**Founder decision on go-to-market sequence:** **United States first → Tier 1 English-speaking markets (UK, Canada, Australia, Singapore) → Tier 2 thereafter.** The EU is not a near-term market.

This resolves the EU cost question (§5.2) cleanly: **EU regional endpoints and their ~10% premium are not incurred until deliberate EU market entry.** No pricing decision is needed now. When EU entry happens, residency is offered on **Business tier and above**, where margin absorbs the premium comfortably.

| Phase            | Region              | Trigger                                                            |
| ---------------- | ------------------- | ------------------------------------------------------------------ |
| Now              | `us-central1` only  | US and Tier 1 markets are served acceptably from US infrastructure |
| EU entry (later) | `europe-west` added | Deliberate market entry decision, not a single inbound customer    |

### 6.2 Self-serve signup creates exposure the market sequence does not control

**This nuance matters and is easy to miss.** Choosing not to _target_ the EU does not prevent an EU team from signing up self-serve — and the moment one does, GDPR, the EU AI Act, and the European Accessibility Act attach regardless of go-to-market intent.

**Two defensible options:**

| Option                             | Effect                                                                                                                                                                                                                                                           |
| ---------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Geo-gate signups (recommended)** | Restrict self-serve signup to supported markets — _"not available in your region yet."_ Standard practice, honest, and keeps compliance scope tight and deliberate. Cloudflare edge geo-detection (§2.3) already provides the mechanism at zero additional cost. |
| Accept all signups                 | Requires maintaining full EU compliance posture from day one — LIA, residency, AI Act documentation — for customers not being pursued.                                                                                                                           |

**Recommendation: geo-gate initially.** It converts EU compliance from an ambient obligation into a deliberate, funded market-entry decision.

**Note:** accessibility (file 05 §A.6) is **not** deferred by this. WCAG 2.1 AA remains a v1 requirement — US web accessibility litigation under the ADA is common and frequent, so the standard is justified by the US market alone, independent of the EAA.

### 6.3 Per-tenant region assignment is still built now

**Region remains a per-tenant configuration value**, built in Phase 0 even though only one region is live. File 05 §B.5 commits to automatic region defaults, and retrofitting per-tenant region assignment after tenants exist is data migration under compliance pressure — one of the most expensive possible corrections. Deferring EU _entry_ does not justify deferring the _capability_.

---

## 6A. API architecture — **[DECIDED: REST + OpenAPI codegen]**

Not previously specified. The 2026 norm is a **hybrid**: REST for public APIs, tRPC or GraphQL for internal frontends, gRPC between services.

### 6A.1 Why not tRPC, despite the monorepo

tRPC is the strongest option for typed monorepos where _"a single TypeScript team owns both ends."_ It is also **TypeScript-only** — and CAIRN's backend is **Python/FastAPI**, chosen for AI ecosystem maturity. tRPC is therefore structurally unavailable without abandoning the Python backend, which would be a far worse trade.

**Worth naming explicitly**, because "monorepo with shared types" naturally suggests tRPC, and an engineer could lose a sprint discovering it cannot work here.

### 6A.2 The chosen approach

**REST with OpenAPI-generated TypeScript clients.** FastAPI generates an OpenAPI schema automatically from Python type hints; that schema generates TypeScript types and a typed client. The result is **end-to-end type safety across a language boundary** — most of tRPC's benefit, with a Python backend.

| Concern             | Handling                                                                                                         |
| ------------------- | ---------------------------------------------------------------------------------------------------------------- |
| Type safety         | OpenAPI → generated TS types, regenerated in CI. A backend change breaking the contract fails the frontend build |
| Public API (Year 2) | Already REST — no second API to build when customers want programmatic access                                    |
| Caching             | Standard HTTP caching, which GraphQL sacrifices                                                                  |
| Versioning          | Standard REST versioning, aligned with the event schema convention (file 12 §4)                                  |

### 6A.3 Not GraphQL

GraphQL suits highly variable client data needs and multi-source aggregation. CAIRN's surfaces are well-defined (file 15 §4), aggregation happens server-side in the Understanding layer rather than client-side, and GraphQL forfeits HTTP caching while adding query-complexity and N+1 concerns. Not justified.

### 6A.4 MCP is not an alternative to this

Restating file 07 §2 because the question recurs: **MCP is pull-based and designed for on-demand fetching.** CAIRN's core capture requirement is continuous push. MCP is the _breadth_ mechanism for long-tail connectors and on-demand enrichment; webhooks and REST are the _depth_ mechanism. They are complementary, not competing.

---

## 6B. Scaling architecture

This must scale professionally from small to large. The patterns below are cheap now and very expensive to retrofit.

### 6B.1 Queue-first ingestion — confirmed correct

Established practice is unambiguous: **naive implementations that process webhooks on the main application thread collapse under load.** A queue-first architecture decoupling production from processing is what survives. CAIRN's design (file 01 §4.1 — verify → enqueue → acknowledge) already does this.

**Scale reference:** mature webhook systems handle tens of millions of events per quarter; the largest pipelines run millions per second. CAIRN's volumes will be orders of magnitude smaller for years — **the architecture matters more than current numbers**, because retrofitting under load is not feasible.

### 6B.2 Backpressure — gap now closed

Previously unspecified. Without flow control, **producers overwhelm consumers, queues fill, and the system collapses.**

| Level                                | Mechanism                                                                                         |
| ------------------------------------ | ------------------------------------------------------------------------------------------------- |
| **Queue depth monitoring**           | Depth beyond threshold triggers scaling or throttling — the primary signal, monitored and alerted |
| **Autoscale workers on queue depth** | Pipeline workers scale on backlog, not CPU. CPU is a poor proxy for LLM-bound work                |
| **Consumer rate limiting**           | Workers throttle rather than overwhelming Cloud SQL or Vertex AI, both of which have limits       |
| **Dead-letter queues**               | Unprocessable events move aside instead of blocking the stream (file 01 §4.1)                     |
| **Graceful degradation**             | Individual failures must not cascade; one malformed payload cannot stall the pipeline             |

### 6B.3 Noisy-neighbour isolation — the scale risk specific to CAIRN

**Also previously unspecified, and the more serious gap.**

CAIRN is multi-tenant with wildly uneven activity. One customer merging a 5,000-commit branch, or a 200-person Slack workspace during an incident, generates orders of magnitude more events than a quiet ten-person team.

**Without fair scheduling, one heavy tenant starves every other tenant** — and affected customers experience it as "CAIRN is broken" with no visible cause. At small scale this is invisible; it appears precisely when the product starts succeeding.

Required:

- **Per-tenant queue partitioning or fair-share scheduling** — capacity allocated across tenants, not first-come-first-served.
- **Per-tenant ingestion rate limits** — generous by default, protecting the shared pipeline from an outlier.
- **Per-tenant queue-depth metrics** — the diagnostic that surfaces this before customers report it.
- **Backfill at lower priority than live events** — so a new customer's 90-day import never delays an existing customer's daily brief.

That last point bites immediately: onboarding (file 11 §3) triggers large backfills, so a new customer onboarding during another's business hours would otherwise degrade the incumbent's experience.

### 6B.4 Scaling path

| Stage              | Change                                                                                                                                   |
| ------------------ | ---------------------------------------------------------------------------------------------------------------------------------------- |
| Now → ~100 tenants | Architecture unchanged. Cloud Run + Cloud SQL + Pub/Sub is comfortable                                                                   |
| ~100–1,000 tenants | Read replicas; separate worker pools per pipeline stage; fair scheduling becomes load-bearing rather than precautionary                  |
| 1,000+ tenants     | Dedicated infrastructure for large tenants (hybrid tenancy, §4.1); evaluate `pgvectorscale` if vector volume approaches the §4.4 ceiling |
| Any stage          | GKE only if Cloud Run genuinely constrains — never by default                                                                            |

**No stage requires re-architecture.** Each is an incremental change to a design that already accommodates it. That is what "professional from small to large" means in practice — not building for 1,000 tenants today, but ensuring nothing built today must be torn out to get there.

---

## 7. Security architecture

| Control                   | Implementation                                                                                                                                  |
| ------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| **Encryption in transit** | TLS everywhere, including internal service-to-service                                                                                           |
| **Encryption at rest**    | Cloud SQL and storage encryption via Cloud KMS                                                                                                  |
| **Secrets**               | GCP Secret Manager; **no secrets in environment variables, images, or code**                                                                    |
| **Access control**        | IAM with least privilege; **SSO enforced across all production tooling** (a SOC 2 expectation, §10)                                             |
| **Network**               | Private VPC connectivity to Cloud SQL; no public database endpoints                                                                             |
| **Webhook ingress**       | Signature verification plus source IP restriction at the gateway (file 01 §4.1)                                                                 |
| **Third-party tokens**    | Customer OAuth tokens encrypted at rest with per-tenant key derivation, short-lived where supported, never shared across tenants (file 07 §4.3) |
| **Audit logging**         | Every access to customer data logged with actor identity — required by file 05 §B.2(3), and by SOC 2                                            |

**Non-production environments never contain real customer data.** Where realistic data is required for testing, it is synthesized or irreversibly anonymized.

---

## 8. Reliability, backup, and disaster recovery

RPO and RTO **should be business decisions, not guesses.**

### 8.1 Targets — **[DECIDED]**

| Data class                               | RPO              | RTO           | Rationale                                                                                            |
| ---------------------------------------- | ---------------- | ------------- | ---------------------------------------------------------------------------------------------------- |
| Customer activity data and derived facts | **≤ 15 minutes** | **≤ 4 hours** | Partly reconstructible from source systems, but re-ingestion is slow and rate-limited (file 02 §3.2) |
| Configuration, auth, tenant metadata     | **≤ 5 minutes**  | **≤ 1 hour**  | Not reconstructible; loss is unrecoverable                                                           |
| Generated documentation                  | ≤ 24 hours       | ≤ 24 hours    | Already delivered into customer repositories (file 04 §5.3)                                          |

**Implementation consequence:** these targets require **continuous WAL archiving**, not daily backups alone (§8.2). Chat data in particular deserves this treatment — Slack's Tier 1 history limits mean chat history effectively cannot be re-ingested at speed, making it genuinely unrecoverable rather than merely inconvenient to restore.

**A point worth noting:** because much of CAIRN's raw input originates in customers' own systems, catastrophic data loss is partially recoverable by re-ingestion — _but_ Slack's Tier 1 history limits (file 02 §3.2) mean chat history is effectively **not** re-ingestable at speed. Chat data therefore deserves the stricter treatment despite intuition suggesting otherwise.

### 8.2 Backup strategy

Reliable PostgreSQL point-in-time recovery combines **three layers**: regular base backups, continuous WAL archiving, and **verified restore automation.**

- **Daily automated backups with tested restoration** — an explicit SOC 2 control (§10).
- **Continuous WAL archiving** for point-in-time recovery.
- **`pgBackRest` or `pg_basebackup`** for physical backups — _orders of magnitude faster to restore_ than `pg_dump` at meaningful data sizes.
- **Cross-region backup storage**, respecting per-tenant residency constraints (§6).
- **Tiered lifecycle** for cost: standard → nearline → coldline → expiry.

### 8.3 Restore testing is the control, not the backup

**An untested backup is a hypothesis.** Restores are exercised on a schedule, with time-to-restore measured against the §8.1 RTO targets and recorded as SOC 2 evidence. This is the control auditors actually examine, and the one teams most often cannot demonstrate.

---

## 9. Observability

| Layer                   | Tooling                                                                      |
| ----------------------- | ---------------------------------------------------------------------------- |
| Infrastructure          | Cloud Logging, Cloud Monitoring                                              |
| Application errors      | Sentry                                                                       |
| Product analytics       | PostHog                                                                      |
| **Pipeline tracing**    | **OpenTelemetry across all four Understanding-layer stages** (file 10 §7)    |
| **AI cost attribution** | Every LLM call tagged by feature, tenant, plan, region, model (file 09 §5.3) |

**Centralized log aggregation with 90–180 day retention** is a SOC 2 expectation and should be configured from the outset rather than backfilled during audit prep.

Without stage-level tracing, debugging a four-stage AI pipeline degrades into guesswork — this is an operational necessity, not a compliance checkbox.

---

## 10. SOC 2 readiness — build for it, don't retrofit

SOC 2 Type II demands **sustained evidence across 64+ control points** covering the entire review period. Retrofitting is where the cost explodes; controls configured from day one generate evidence automatically.

**Infrastructure controls to establish now:**

- [ ] **SSO enforced** across all production tooling
- [ ] **Centralized log aggregation**, 90–180 day retention
- [ ] **Daily automated backups with tested restoration** (§8.3)
- [ ] **Documented change management** — linked tickets and pull-request approval trails
- [ ] MFA everywhere; role-based access control
- [ ] Encryption in transit and at rest, with evidence of configuration
- [ ] Access provisioning and deprovisioning records
- [ ] Vulnerability scanning
- [ ] Incident response plan, documented and exercised

**Compliance is a continuous operation, not a project:** monthly patching, quarterly access reviews, annual risk assessment. A compliance automation platform (Vanta, Drata, Secureframe, Sprinto) continuously collects evidence — without one, teams burn hundreds of hours chasing artifacts before each audit. The original proposal already budgets $25–45K all-in for SOC 2 Type I; that figure assumes controls exist to be evidenced.

---

## 11. Cost controls

- **`max-instances` caps** on every Cloud Run service (§3.1) — a budget safeguard as much as a reliability one.
- **AI cost attribution** per feature, tenant, and model (file 09 §5.3), with alerting when per-user cost exceeds threshold.
- **Batch processing** for scheduled work; real-time paths reserved for interactive queries (file 09 §5.2).
- **Storage lifecycle policies** on backups and raw activity beyond the retention window (file 05 §B.4).
- **Weekly cost review** alongside quality review (file 10 §8) — the two trade against each other and reviewing either alone produces poor decisions.

---

## Decisions requested from founder

1. **Frontend correction (§2.1)** — approve Cloudflare **Workers with OpenNext** rather than Cloudflare Pages, following Cloudflare's current recommendation. _Recommendation: confirm_ — choosing Pages now means migrating later.
2. **Background-job tenant isolation (§4.3)** — acknowledge this as the architecture's sharpest risk, and approve the four required controls including fail-closed behavior and cross-tenant tests in CI. _This is the most important technical decision in this file._
3. **Per-tenant region assignment from day one (§6)** — confirm it is built now despite only one live region, because retrofitting is data migration under compliance pressure.
4. **RPO/RTO targets (§8.1)** — confirm or adjust. These should be your business decision; the proposed values are a starting position, and the chat-data nuance in §8.1 is worth reviewing specifically.
5. **Claude access path (§5)** — confirm Vertex AI as default, accepting the ~10% EU regional premium and model-availability lag, with the provider abstraction built from day one.
6. **EU cost treatment (§5.2)** — decide whether the ~10% higher EU serving cost is absorbed in margin or reflected in regional pricing.
7. **SOC 2 controls from day one (§10)** — confirm the control list is configured during initial build rather than before audit, and approve a compliance automation platform early.
8. **Existing accounts** — confirm whether GCP and Cloudflare organization accounts exist or need creating.

---

_Sections 4.3 (background-job isolation), 6 (per-tenant regions), and 10 (SOC 2 controls) are the decisions that are expensive to reverse. Everything else in this file can evolve with the product._
