# Data Model — The `ActivityEvent` Schema

**Status:** ✅ LOCKED — decisions resolved, ready for implementation
**Depends on:** [01](01-github-integration.md)–[03](03-meeting-intelligence.md) (producers), [09-understanding-layer.md](09-understanding-layer.md) (consumer), [06-infrastructure.md](06-infrastructure.md) (storage, tenancy)

**Why this file exists:** Every pillar file states that its data "normalizes into the shared `ActivityEvent` schema." No file defined it. Since all four capture pillars produce it and the entire Understanding layer consumes it, an undefined schema means four engineers inventing four incompatible versions.

**Design principle:** adopt a standard rather than invent one.

---

## 1. Build on CloudEvents

**CloudEvents** is a CNCF specification defining a vendor-neutral standard for describing event data, adopted by Google Cloud, Azure, and many open-source projects. Since CAIRN runs on GCP (file 06) and consumes webhooks from multiple vendors, adopting it is straightforward and carries real benefits:

- **Interoperability** — Pub/Sub and Cloud Functions understand the format natively.
- **Tracing** — `traceparent` and `tracestate` follow W3C standards, enabling correlation across services and supporting the OpenTelemetry instrumentation required in file 10 §7.
- **Versioning** — a solved problem with an established convention (§4).
- **No invention tax** — the schema is documented, understood, and not CAIRN's to maintain.

**Decision: `ActivityEvent` is a CloudEvents 1.0 envelope with a CAIRN-defined `data` payload.**

---

## 2. The envelope

CloudEvents standard attributes, with CAIRN's usage:

| Attribute         | Type      | CAIRN usage                                                                                                                |
| ----------------- | --------- | -------------------------------------------------------------------------------------------------------------------------- |
| `specversion`     | string    | `"1.0"`                                                                                                                    |
| `id`              | string    | Unique event ID. **Idempotency key** — combined with `source`, the deduplication key for webhook redelivery (file 01 §4.1) |
| `source`          | URI-ref   | Producer: `/github/{installation_id}`, `/slack/{team_id}`, `/meet/{workspace_id}`                                          |
| `type`            | string    | Reverse-DNS with version: `ai.cairn.github.pull_request.merged.v1` (§4)                                                    |
| `subject`         | string    | The entity acted upon: repository, channel, or meeting identifier                                                          |
| `time`            | timestamp | **When the activity occurred**, not when CAIRN received it (§3.2)                                                          |
| `datacontenttype` | string    | `"application/json"`                                                                                                       |
| `dataschema`      | URI       | Points to the registered schema for this `type` — enables validation (§5)                                                  |
| `data`            | object    | CAIRN payload (§3)                                                                                                         |

### 2.1 CAIRN extension attributes

CloudEvents permits extension attributes. CAIRN requires four:

| Extension     | Purpose                  | Why it is on the envelope                                                                                                                                                                        |
| ------------- | ------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `tenantid`    | Owning tenant            | **Mandatory on every event, no exceptions.** This is the field file 06 §4.3 depends on for background-job tenant context. Placing it on the envelope means it can never be lost inside a payload |
| `actorid`     | Resolved CAIRN person ID | Set after identity resolution (file 01 §5.3); null before                                                                                                                                        |
| `ingestedat`  | Receipt timestamp        | Distinct from `time` (§3.2)                                                                                                                                                                      |
| `traceparent` | W3C trace context        | Pipeline tracing (file 10 §7)                                                                                                                                                                    |

**`tenantid` is the single most important field in the schema.** A background job cannot forget tenant context if tenant context is structurally inseparable from the event itself.

---

## 3. The `data` payload

```json
{
  "actor": {
    "raw_identity": "ali@company.com",
    "resolved_person_id": "prs_a1b2c3",
    "display_name": "Ali",
    "is_bot": false,
    "co_actors": ["prs_d4e5f6"]
  },
  "activity": {
    "category": "code | conversation | meeting | document",
    "action": "merged",
    "summary": "Merged PR #482: refactor auth token handling",
    "project_ref": "proj_x7y8z9"
  },
  "provenance": {
    "source_url": "https://github.com/org/repo/pull/482",
    "source_timestamp_ref": null,
    "certainty": "verified | observed | suggested"
  },
  "content": {
    "text": null,
    "metadata": { "files_changed": 12, "additions": 340, "deletions": 89 }
  }
}
```

### 3.1 Field notes

**`actor.is_bot`** — populated from the bot registry (file 01 §5.2). Bot activity is retained as repository context but excluded from human attribution. Filtering at the schema level rather than per-consumer means the rule cannot be forgotten downstream.

**`actor.co_actors`** — first-class, not an afterthought. Squash-merge co-authorship (file 01 §5.1) means collaborative work is systematically erased if co-actors are not modeled explicitly.

**`provenance.certainty`** — the three tiers from file 05 §A.2.2, carried on every event. **Categorical, never numeric** — internal numeric confidence exists for thresholds and evaluation but never enters this field or the UI.

**`provenance.source_timestamp_ref`** — the transcript timestamp for meeting-derived events, enabling one-click verification (file 03 §6). Null for other sources.

**`content.text`** — nullable and frequently null by design. File 01 §6.3 keeps raw diffs out of the pipeline by default; file 02 §7.1 excludes non-work-relevant chat. **The schema permits absence of content, which is the normal case, not a degraded one.**

### 3.2 Two timestamps, deliberately

`time` is when the activity happened; `ingestedat` is when CAIRN received it. These diverge routinely — backfill (file 01 §7) ingests 90 days of history in minutes, and webhook retries arrive late.

**Every user-facing view orders by `time`. Every operational and debugging view orders by `ingestedat`.** Conflating them produces a brief claiming work happened today that actually happened in March.

---

## 4. Versioning

CloudEvents convention places the version in the `type` field: `ai.cairn.github.pull_request.merged.v1`.

**Rules:**

- **Additive changes** (new optional field) do not bump the version.
- **Breaking changes** (removing a field, changing meaning or type) require a new major version, with both supported during migration.
- **Consumers ignore unknown fields** — forward compatibility is mandatory, not optional.

Stored events are immutable. Historical events retain their original version, so any migration is a read-path concern, never a rewrite of history.

---

## 5. Validation

**Every event validates against its registered schema before entering the pipeline.** A schema registry provides centralized versioning and compatibility checking.

This is also a security control: file 09 §6.3 requires that Stage 2 output be schema-validated before acceptance, since schema constraint is what prevents an injected instruction from becoming an arbitrary action. **Schema validation is a boundary, not a formality.**

---

## 6. Derived entities

`ActivityEvent` is the immutable input record. The Understanding layer produces three derived, mutable entities stored separately:

| Entity      | Description                                                                                       | Mutability                                               |
| ----------- | ------------------------------------------------------------------------------------------------- | -------------------------------------------------------- |
| **Person**  | Resolved identity graph — handles, emails, display names, merge history                           | Mutable; user-correctable (file 01 §5.3)                 |
| **Fact**    | Extracted decision, commitment, or blocker, with `valid_from` / `valid_until` and `superseded_by` | Mutable via supersession, never overwrite (file 09 §3.2) |
| **Project** | Inferred grouping of related activity across sources                                              | Mutable                                                  |

**Facts are superseded, never deleted.** History is preserved; only currently-valid facts reach synthesis. A human correction (file 09 §9) supersedes the AI-derived fact and is recorded as such — retaining both the original and the correction, which is what makes corrections usable as evaluation data (file 10 §2.1).

---

## 7. Storage

| Concern          | Approach                                                                                                                                                     |
| ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Table design     | Events partitioned by `time`; tenant-scoped indexes                                                                                                          |
| Tenant isolation | **PostgreSQL RLS on `tenantid`** for every table (file 06 §4.2)                                                                                              |
| Retention        | 12-month default on raw events, per-tenant configurable (file 05 §B.4). Derived facts persist longer                                                         |
| Vector search    | Embeddings on `activity.summary` — not raw content — which is the contextual-retrieval technique giving a 49% reduction in retrieval failures (file 09 §4.4) |
| Deletion         | GDPR Article 17 deletion cascades from events through all derived entities                                                                                   |

---

## 8. Producer contract

Every pillar producing events must guarantee:

- [ ] `tenantid` set on every event, always.
- [ ] `time` reflects when the activity occurred, not when it was received.
- [ ] `id` is stable across redelivery, enabling idempotent consumption.
- [ ] `provenance.source_url` resolves to something a human can open.
- [ ] `provenance.certainty` set honestly by source type.
- [ ] `actor.is_bot` correctly populated.
- [ ] `co_actors` populated where the source supports it.
- [ ] Event validates against its registered schema.

**This checklist is the integration contract.** A new source (file 07) is complete when it satisfies it — nothing more is required, and nothing less is acceptable.

---

## Decisions requested from founder

1. **CloudEvents as the envelope (§1)** — confirm adopting the CNCF standard rather than a bespoke schema, accepting a small amount of structural verbosity for interoperability, tracing, and solved versioning.
2. **`tenantid` on the envelope (§2.1)** — confirm it is structurally mandatory rather than a payload field, given that background-job tenant context is the sharpest infrastructure risk (file 06 §4.3).
3. **Two timestamps (§3.2)** — confirm the `time` / `ingestedat` distinction and the rule that user-facing views order by `time`.
4. **Categorical certainty (§3.1)** — confirm the three-tier field carries no numeric confidence, consistent with file 05 §A.2.1.
5. **Supersession over deletion (§6)** — confirm facts are superseded rather than overwritten, accepting the storage cost for correct history and usable evaluation data.
6. **Producer contract (§8)** — confirm this is the acceptance criterion for every new data source.

---

_This schema is the narrowest waist of the system — four producers above it, one Understanding layer below. Getting it right is cheap now and expensive later, because every producer and consumer encodes its assumptions._
