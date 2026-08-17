# Running CAIRN

**Status: pre-production.** Nothing here has run outside a development machine. This document
exists so that the gap between "the code works" and "the service is operable" is written down
rather than discovered during the first incident. Stage E (Steps 27–30) closes it.

---

## What exists today

| Concern            | State                                                                                                 |
| ------------------ | ----------------------------------------------------------------------------------------------------- |
| Structured logging | ✅ `structlog`, JSON in non-local environments, tenant id on every job log line                       |
| Health endpoints   | ✅ `GET /healthz` (liveness, no database) and `GET /readyz` (readiness, 503 when not)                 |
| Container image    | ✅ Multi-stage, non-root, one image with two entrypoints                                              |
| Migrations         | ✅ Alembic, round-trip tested in CI                                                                   |
| Metrics            | ✅ Stage, model, cost, queue and evaluation counters — exported only when an OTLP endpoint is set     |
| Tracing            | ✅ Spans across every pipeline stage, carried over the queue by the envelope's `traceparent`          |
| Fair scheduling    | ✅ On `CAIRN_QUEUE_BACKEND=postgres`: priority and per-tenant limits. Not on Pub/Sub                  |
| Backup / restore   | ⚠️ Rehearsable and self-verifying (`make restore-rehearsal`) — rehearsed locally, never in production |
| SLOs               | ⚠️ Defined with stated measurement sources (`docs/SLOS.md`) — three of five measurable today          |
| Release gates      | ✅ `uv run python -m cairn_api.ops.gates_cli`, non-zero while anything blocks                         |
| Alerting           | ❌ Thresholds are written below; no rules and no destination are configured                           |
| Dashboards         | ❌ None                                                                                               |
| On-call            | ❌ No rotation, no escalation path                                                                    |

**The honest reading:** the system can be started, will tell you what it is doing, and can now be
asked what it is doing — the counters and spans exist and carry a trace from webhook to brief.
Nothing is watching them. No alert has a destination, no backup has been restored, and nobody is
paged. It is observable and unmonitored, which are different things.

**The probe paths are `/healthz` and `/readyz`.** This table said `/health` for two stages; that
path returns 404, so a load balancer configured from this document would have marked every instance
unhealthy and sent it no traffic. Liveness never touches the database — a probe that fails when
PostgreSQL is briefly unreachable restarts a process that was working.

---

## The two processes

One image, two commands — chosen so that the API and the worker are always the same build, and a
"works in the API but not the worker" bug cannot come from a version skew.

```bash
# API
uvicorn cairn_api.api.app:create_app --factory --host 0.0.0.0 --port 8080

# Worker
python -m cairn_api.jobs.main
```

The worker is the one that costs money: it runs the model stages. Scale it on queue depth, not on
CPU — the stages are latency-bound on an external API, so CPU stays flat while work piles up.

---

## What to check first when something is wrong

**Briefs are empty or thin.** Look for `synthesize.claims_suppressed` in the logs. Suppression is
deliberate and recorded with a reason; a brief that lost claims to span verification is the system
working, and a brief that lost claims to `referenced a fact that was not supplied` means the model
is hallucinating references and the prompt needs attention.

**No facts are appearing.** The chain is: `github.delivery_attributed` → the understanding job →
`resolve.applied` → `graph.built`. Whichever of those log lines stops is the stage to look at. If
`resolve.applied` reports `merged` for everything, the deduplication thresholds are too loose for
the workspace's writing style.

**Retrieval returns nothing.** Almost always an embedding-model mismatch: vectors are stored under
a model name and searched by the same name. `DEFAULT_EMBEDDING_MODEL` is deliberately defined once
for this reason — if it has been overridden in one call site and not the other, search matches
nothing and logs nothing unusual.

**Costs are climbing.** Every model call records its token counts, and spend is accounted per tenant
and per stage. A runaway is almost always a backfill: it is the only path that processes months of
history at once.

---

## Alert thresholds and what to do about them

Every threshold below is readable today from `/v1/internal/operations/*`, which
needs an `engineering` or `security` staff role. None of it names a workspace or
carries a statement — see `telemetry/attributes.py` for why the allow-list is
shaped that way.

**These are starting values, not measured ones.** They were chosen from what the
system does rather than from what it has done in production, because it has not
run in production. Revisit each after the pilot with a week of real numbers.

| Signal                 | Warning                  | Page                        | First action                                                                                                                                                                                                                                |
| ---------------------- | ------------------------ | --------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Queue backlog**      | oldest unprocessed > 15m | > 1h, or depth still rising | Check the worker is running at all (`queue.inMemoryBroker` true means jobs are lost on restart). Then read `tenantsWaiting`: one is a backfill draining, many is too little capacity. See **The scheduler**.                                |
| **DLQ growth**         | any dead letter          | > 5 in an hour              | Read the dead-letter reason. A repeated `UnknownJobTypeError` is a deploy that registered no handler; a repeated `DeliveryNotFoundError` is a retention sweep racing a job.                                                                 |
| **Model cost spike**   | 2× the daily median      | 5×, or a ceiling refusal    | `operations/spend` by stage. A spike in `synthesis` is usually a brief cache miss storm; in `extract`, a backfill. The per-tenant ceiling in `spend.py` refuses before the bill grows.                                                      |
| **Evaluation decline** | any `blocked` case       | groundedness below the gate | Do not ship. `blocked` means a boundary or tone violation — the two md/10 §5 treats as zero-tolerance. Re-run `make eval` against the same dataset before believing a single run.                                                           |
| **Telemetry export**   | exporter errors > 0      | no spans for 15m            | Telemetry failing must never fail the work: `_attributes` drops unsafe values and `stage()` swallows nothing else. If spans stop, the pipeline is still correct and the dashboard is not — fix the exporter, do not roll back the pipeline. |

### What the numbers mean

- **Oldest unprocessed delivery** is the honest latency measure. Queue depth
  alone hides one stuck job behind a thousand fast ones.
- **Spend is per replica.** `operations/spend` reads an in-process ledger, so on
  N instances the real figure is higher. Stated on the screen; the durable
  version needs the metrics exporter configured.
- **Evaluation counts are from the committed baseline**, not a live run. A
  dashboard that graded on demand would be spending model budget on a page
  refresh.

### Rolling back telemetry

Telemetry is a no-op unless an exporter is configured. To disable it entirely,
unset the exporter environment variables and restart — instrumentation stays in
the code, costs nothing, and emits nothing. There is no separate feature flag,
deliberately: a flag that can turn spans off in one environment and not another
is how an incident ends up with no trace from the instance that mattered.

---

## The scheduler

`CAIRN_QUEUE_BACKEND=postgres` selects the scheduling queue. It is the only
backend that can enforce priority and per-tenant fairness, for a structural
reason: those are decisions about the queue as a whole, and PostgreSQL is the
only place every worker sees the same queue.

**How work is chosen.** Priority first and absolutely — a live push always
outranks a backfill, however long the backfill has waited, because backfill is
work nobody is waiting for. Then by what the job costs its tenant's share: a
tenant's second queued job loses to another tenant's first. Then by age.

**What bounds a tenant.** Four jobs in flight at once
(`MAX_ACTIVE_PER_TENANT`), and five hundred queued before new work is held back
thirty seconds at a time (`MAX_QUEUED_PER_TENANT`). Held back, not dropped: the
row exists, `available_at` moves forward, and it runs when the backlog drains.

**Leases.** A claimed job is held for five minutes (`LEASE_SECONDS`). A worker
that dies mid-job has its work reclaimed on the next poll by whoever is up. Two
workers cannot hold the same job — `FOR UPDATE SKIP LOCKED` decides that in the
database, not in the application.

### Reading the fairness numbers

`/v1/internal/operations/queue` reports `tenantsWaiting` and
`longestWaitMinutes` alongside depth. They are counts of jobs, not of people.

| What you see                                           | What it means                    | What to do                                                                      |
| ------------------------------------------------------ | -------------------------------- | ------------------------------------------------------------------------------- |
| `longestWaitMinutes` high, `tenantsWaiting` 1          | One workspace has a long backlog | Normal for a backfill. Nobody else is affected — that is the design working.    |
| `longestWaitMinutes` high, `tenantsWaiting` many       | Not enough workers for the load  | Add worker instances. Fairness divides capacity; it does not create it.         |
| `scheduledRunning` at a multiple of four and flat      | Every worker is busy             | Same as above.                                                                  |
| `scheduledWaiting` rising with `scheduledRunning` at 0 | No worker is claiming            | The worker process is down, or on a different `CAIRN_QUEUE_BACKEND` to the API. |

The tuning values above are starting points chosen from the shape of the work,
not measured under production load, because this has not run under production
load. Revisit them after the pilot.

### What Pub/Sub does not do

`CAIRN_QUEUE_BACKEND=pubsub` is durable and delivers in arrival order. It has no
per-tenant fairness and no priority: on that backend one customer's backfill can
occupy every worker and delay another customer's live push. The worker logs
`queue.fairness_not_enforced` at startup when a deployed environment selects it.

It also emits no queue metrics — `cairn.queue.events` stays empty, so the DLQ and
retry alerts above have nothing to fire on. Both are reasons to deploy
`postgres` unless something specifically requires Pub/Sub.

### Telemetry is required in a deployed environment

The API and the worker refuse to start when `CAIRN_ENVIRONMENT` is `staging` or
`production` and no `OTEL_EXPORTER_OTLP_ENDPOINT` is set. Instrumentation that
exports nowhere is worse than none: every call site looks instrumented, every
span is built and discarded, and it is discovered during the incident it was
supposed to explain.

To run deliberately without it, set `CAIRN_TELEMETRY_OPTIONAL=true`. That is a
decision somebody writes down rather than a default nobody noticed.

### Changing the caps

Raising `MAX_ACTIVE_PER_TENANT` raises how much of the fleet one tenant can take
and lowers scheduling overhead. Lowering it makes a busy platform feel more even
and leaves capacity idle when only one tenant has work. Neither is free, and
neither should be changed to resolve an incident — during an incident, add
workers.

---

## Release gates

Run this before any deploy. It exits non-zero while anything blocks, so a
pipeline can call it as a step rather than a person reading a table and
deciding:

```bash
cd apps/api && uv run python -m cairn_api.ops.gates_cli
```

Each gate reports one of three states, and the third is why the command exists:

| State    | Meaning                                                                       |
| -------- | ----------------------------------------------------------------------------- |
| `PASS`   | Configured, and everything checkable from inside the process checks out.      |
| `BLOCK`  | Not configured. This environment cannot do the thing at all.                  |
| `MANUAL` | Configured, but the proof needs a real round-trip to a real external service. |

**`MANUAL` blocks a release exactly as firmly as `BLOCK`.** A GitHub App id in an
environment variable proves somebody set a variable — not that the app is
installed, that the webhook secret matches, or that a signed delivery has ever
arrived. Treating configuration as proof is how a release gets signed off on the
strength of a `.env` file, so the command never claims more than the evidence
supports and always names the action that would close the gap.

Nothing in it calls out to a network. A gate that made a live API call would
fail in CI for reasons unrelated to the code, and would need production
credentials wherever it ran.

### Closing the manual gates

| Gate           | What closes it                                                                                                                                                                                                                                                |
| -------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **email**      | `uv run python -m cairn_api.email.probe --to you@example.com`, then confirm it **arrives** — check spam. The probe refuses to run on the console backend, because a pass there would mean nothing. A relay accepting a message is not a person receiving one. |
| **telemetry**  | Set `OTEL_EXPORTER_OTLP_ENDPOINT`, restart, send one webhook, and find its trace in the collector. An endpoint that refuses connections looks identical to one nobody has sent to.                                                                            |
| **github**     | Install the App on one repository, push a real commit, and confirm the delivery verifies its signature and produces a fact attributed to the right person.                                                                                                    |
| **model**      | `uv run python -m cairn_api.evaluation.runner --pipeline real` against live Vertex, and record the baseline. Every quality number in this repository was produced by a deterministic stand-in, and says so.                                                   |
| **audit-sink** | Replicate the audit chain to an append-only sink outside this database. Until then the log is **tamper-evident, not tamper-proof** — see below.                                                                                                               |

### The audit log is tamper-evident, not immutable

The internal audit log is hash-chained and the application role holds `INSERT`
and `SELECT` with no `UPDATE` and no `DELETE`, so an attacker inside the
application can append but cannot rewrite history undetected.

It lives in the application database. A compromise of the database _owner_ can
drop the table outright, and a chain nobody can read proves nothing. Until a
separate append-only sink exists, do not describe it externally as "immutable"
or "customer-verifiable". It is tracked as a release gate rather than a note, so
that "we should do that eventually" cannot quietly become "we did that".

---

## Before this is production-ready

1. ~~**Alerting on the dead-letter queue.**~~ Done — see the alert table above.
2. ~~**A correlation id carried across the queue.**~~ Done — see `docs/CORRELATION.md`.
3. ~~**Rehearsed restore.**~~ Rehearsable — see `docs/BACKUP-RESTORE.md`. Rehearsed **locally**; production backups are still a manual gate.
4. ~~**Spend alerting**, not only spend capping.~~ Done — approach and refusal are both signalled.
5. ~~**SLOs**, so "slow" becomes a number somebody agreed to.~~ Defined — see `docs/SLOS.md`. Several are measurable today; the rest say so rather than reporting a fabricated number.

What remains is not code:

- **Nothing is watching.** Thresholds are written down and readable; no alert has
  a destination and nobody is paged.
- **No production backup has been restored.** The rehearsal runs against a local
  database. Managed backups, retention, offsite copies and encryption still have
  to be arranged and then actually exercised.
- **Stage B and Stage C are unevidenced.** No real GitHub App has processed real
  activity, and no real model has produced a brief.
