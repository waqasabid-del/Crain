# Following one webhook to one brief

CAIRN is almost entirely background work. A webhook arrives, a job is queued, a
worker picks it up, that worker queues a second job, and some time later a brief
is different. When the brief is wrong, the question is always the same: _what
happened between those two points?_

Two things answer it, and they answer it in different places.

|                  | `traceparent`                                           | `correlation_id`                      |
| ---------------- | ------------------------------------------------------- | ------------------------------------- |
| What it is       | W3C trace context                                       | An opaque 32-character hex id         |
| Links            | Spans, across services                                  | Log lines, and rows in the queue      |
| Exists when      | A tracer is installed **and** an exporter is configured | Always                                |
| Stored           | Nowhere durable except the queue row                    | The queue row, and every log line     |
| Survives a retry | Yes (same job)                                          | Yes — deliberately, this is the point |

They coexist. Neither replaces the other. `traceparent` is what turns a
distributed trace into one waterfall in a collector; the correlation id is what
`grep` finds when there is no collector — which is the local default, and the
state of any deployment that has not configured one yet.

## Lifecycle

1. **Origin.** `github/webhooks.py` calls `telemetry.correlation.begin()` as the
   first thing it does, before the signature check, so even a rejected delivery
   is greppable. Work with no originating request — a backfill page, a scheduled
   sweep, a job built in a test — gets one from `JobEnvelope`'s default factory
   instead. Nothing is ever without an id.
2. **Bound.** `begin()` sets a `ContextVar` and binds `correlation_id` into the
   structlog context, so every line emitted beneath it carries the id without
   anybody passing the value down a call chain.
3. **On the envelope.** `JobEnvelope.correlation_id` defaults to the ambient id,
   or a new one. It is inherited rather than passed as a parameter because a
   parameter is something a future caller can forget, and the caller who forgets
   is the chain that breaks.
4. **Through the queue.**
   - _In-memory_ and _Pub/Sub_ carry the whole envelope, so the id travels for
     free. Pub/Sub repeats it as a message attribute so it is readable from the
     console and from the dead-letter topic without decoding the body.
   - _PostgreSQL_ stores it inside the `payload` JSONB column under the reserved
     key `__cairn_correlation_id` (`jobs/postgres.py`), written on publish and
     removed again on receive so no handler ever sees it. See "Migration" below.
5. **On the worker.** `Worker._handle` and `run_job` both open
   `correlation.correlated(envelope.correlation_id)`, which rebinds the context
   var and the log context and resets both on the way out — a worker handles
   many jobs in one process, and a leaked id would label the next job's lines
   with the previous one's path.
6. **Onward.** A handler that publishes further work (the GitHub delivery job
   publishing understanding) builds an envelope under that same context, so the
   new job inherits the id. One webhook, one id, all the way to the brief.
7. **On spans.** `run_job` stamps `correlation_id` on the job span alongside the
   trace link, so a collector and a log store can be joined on it.

`grep <correlation_id>` over the log store returns: the webhook receipt, the
delivery job's start and completion, the attribution counts, the understanding
job, and — if it failed — the dead letter.

## Why it is safe to export

`correlation_id` is on the telemetry allow-list (`telemetry/attributes.py`). It
is an identifier, not content: 32 hex characters from `uuid4`, derived from
nothing anybody said, describing nobody.

That holds only while the _shape_ holds, so it is enforced twice: the envelope
refuses to parse an id that is not 32 hex characters, and
`telemetry.correlation.coerce()` discards anything of the wrong shape read back
out of storage (a queue row is storage, not truth). An id that fails either
check is replaced with a fresh one — a small loss of continuity, against a
string of somebody else's choosing landing on a span.

## Migration required (not applied — migrations are serialised this release)

The design above works with no schema change. Two columns would make it better,
and both are additive, nullable and safe to apply while the queue is running.

```sql
ALTER TABLE scheduled_jobs ADD COLUMN correlation_id CHAR(32);
CREATE INDEX ix_scheduled_jobs_correlation ON scheduled_jobs (correlation_id);

ALTER TABLE scheduled_jobs ADD COLUMN dead_at TIMESTAMPTZ;
CREATE INDEX ix_scheduled_jobs_dead_at ON scheduled_jobs (dead_at)
    WHERE state = 'dead';
```

- **`correlation_id CHAR(32) NULL`** — nullable because rows written by earlier
  revisions have no id, and a job that will not parse is worse than a job that
  cannot be joined to its webhook. Today the id lives in the `payload` JSONB
  under a reserved key, which is durable and round-trips correctly but is not
  indexed: "show me every job for this webhook" is a JSONB scan rather than an
  index lookup. `_unpack` in `jobs/postgres.py` keeps working against rows
  written either way, so the column can be introduced and backfilled from the
  payload key at leisure.
- **`dead_at TIMESTAMPTZ NULL`** — the honest home for the time of death.
  `dead_letter()` currently writes `available_at = now()` on the row it kills,
  which is accurate (a dead row is never claimed, and every query reading
  `available_at` filters `state = 'queued'` first) but overloads a column whose
  name says something else. It is what makes `dead_letter_health()` able to
  answer "more than five in the last hour"; the column removes the overload.

## The dead-letter signal

`PostgresJobQueue.dead_letter_health()` returns `DeadLetterHealth`: `total`,
`recent` inside the alert window, `oldest_age_seconds`, `newest_age_seconds`,
`by_job_type`, `by_category`, and `paging` (the `> 5 in an hour` threshold from
`docs/OPERATIONS.md`). Counts of jobs and machines only — never per person.

The metric is `cairn.queue.dead_letters`, deliberately separate from the general
`cairn.queue.events` counter, labelled with `job_type`, `error_category` and
`priority`. The category is `telemetry.dead_letter_category()`'s bounded output:
the leading `Type:` segment of the reason when it looks like an exception class,
`other` otherwise. The full reason stays in the `dead_reason` column and in the
ERROR log line, both of which live under the product's retention and deletion
promises — an exporter does not.
