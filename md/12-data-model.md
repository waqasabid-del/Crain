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

| Entity               | Description                                                                                       | Mutability                                               |
| -------------------- | ------------------------------------------------------------------------------------------------- | -------------------------------------------------------- |
| **Person**           | Resolved identity graph — handles, emails, display names, merge history                           | Mutable; user-correctable (file 01 §5.3)                 |
| **Fact**             | Extracted decision, commitment, or blocker, with `valid_from` / `valid_until` and `superseded_by` | Mutable via supersession, never overwrite (file 09 §3.2) |
| **Project**          | Inferred grouping of related activity across sources                                              | Mutable                                                  |
| **ExternalIdentity** | One provider account bound to one person, with the evidence for the binding                       | Appended and ended, never deleted (Step 34)              |

### Meeting capture consent (Step 35)

**Three tables, and deliberately no workspace toggle.** `meeting_capture_requests`
records that somebody asked to collect one meeting's platform-produced artifact;
`meeting_participants` records who is expected; `meeting_consents` records each
person's own answer. CAIRN never joins a meeting and never produces a recording
or transcript (md/03 §4.2) — these tables decide only whether it may later ask a
platform for what that platform already made.

Capture is eligible only when **every currently expected participant** holds a
live acceptance against the current policy version. That is computed by
`meetings.eligibility.check` and written in exactly one place; nothing else in
the product may set `eligible`. Adding a participant, a decline, a withdrawal, a
policy change, a reschedule beyond tolerance, an unidentified participant, or an
empty participant list each block it. **An empty list is not unanimity** — the
vacuous-truth branch is refused explicitly.

**No meeting title, join URL or provider attendee id ever leaves the database.**
A calendar title is often the most sensitive string in a workspace and every
participant sees the request; the time window and the requester's written purpose
identify it instead.

Decisions are **append-only** — changing your mind supersedes rather than edits —
and none of the three tables carries a DELETE grant. The history is the evidence
that withdrawal was possible and honoured.

Retention: consent metadata follows the workspace's retention period like every
other tenant row and is removed with the tenant on deletion. It contains no
meeting content, because no meeting content exists at this step.

**Never built on these tables** (md/03 §5.4): talk time, participation scores,
sentiment, coaching, attendance ranking, or any per-person meeting analytic.
There is no duration column, no speaking column and no attendance outcome — only
whether somebody agreed, which is a permission and not a measurement.

---

### Google Meet artifacts (Step 36)

**Meet is artifact-only.** CAIRN never joins a call, never records, and never
transcribes. The only thing it may ever receive is a transcript the meeting
platform itself produced, and only for a meeting every participant consented to
under Step 35.

Two authorisations, deliberately separate. `meetings.space.readonly` (sensitive)
lets Google announce that a transcript exists. `drive.meet.readonly` (restricted)
lets CAIRN fetch one — its own consent action, its own OAuth client, its own
encrypted refresh token. Connecting Meet therefore grants nothing about
transcripts, and the tables reflect that: a connection can exist with no grant.

`kind = 'transcript'` and `provider = 'google_meet'` are CHECK constraints, so a
recording, an audio file or a smart note cannot be stored — not "is not stored",
_cannot be_. Transcript-ness is checked three ways before a byte is written:
reference shape, declared type, and the MIME of what arrived.

Raw transcript bytes live in their own table, encrypted, with **no grant to the
application role**. Retention deletion removes the bytes and leaves the
provenance — provider, meeting id, artifact digest, generated and retrieval
times, checksum, consent-policy version — so "a transcript existed and was
deleted on this date" stays answerable after the content is gone.

Nothing reads a transcript at this step. There is no route that returns one, and
no model call touches one.

---

### Cross-source identity (Step 34)

**One provider account belongs to at most one person per workspace, and CAIRN
never guesses which.** `external_identities` binds a provider account — a Slack
`U…`, a Google Chat `users/…`, a GitHub numeric user id — to a `Person`, and a
row exists only for one of two reasons:

| Verification           | What happened                                                                                                                          |
| ---------------------- | -------------------------------------------------------------------------------------------------------------------------------------- |
| `verified_email_match` | The provider supplied an address it stated it had verified, and it equalled the verified address of a CAIRN account in this workspace. |
| `self_confirmed`       | The person said so, from an authenticated session.                                                                                     |

There is deliberately no third member and no `suggested`/`inferred` state.
**Nothing links a person by display name, similar name, avatar, writing style,
message content, organisation chart, shared channel, working hours, or model
output.** There is no threshold to tune, because a threshold implies a high
enough score would be good enough, and for "is this the same human" it is not.

A CHECK constraint requires the evidence to match the method: a verified-email
row must carry the address that proved it, a self-confirmed row must not — so a
row cannot blur "the provider proved it" with "the person said so".

**Ownership is exclusive while live**, enforced by a partial unique index on
`(tenant_id, provider, provider_account_id) WHERE state = 'active'`. Two people
cannot hold one account, the race between simultaneous confirmations is decided
by the database, and an account can change hands only through an explicit
revocation that leaves its reason behind.

**Unresolved is a first-class answer.** Activity whose provider account matches
no live row stays attributed to the account and to nobody. `fact_people` carries
either a human-readable `mention` (text a model wrote, published, correctable) or
a structured `provider` + `provider_account_id` (internal, never serialised) —
exactly one, by CHECK. The account ids are private provider identifiers and never
reach an API response, an export, a log line or a screen; what a reader sees is a
count, `unresolvedActors`, which says one contributor here has not connected
their account without saying who.

**Ending a link changes the claim, never the record.** Revoking or disputing sets
`state` and clears `person_id` on the rows that account was attributed to. The
fact, its statement, its sources, the quoted evidence and the provider's own
record of who produced it all remain. A disputed link means the attribution was
wrong, not that the work was imaginary.

---

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
