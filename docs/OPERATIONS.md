# Running CAIRN

**Status: pre-production.** Nothing here has run outside a development machine. This document
exists so that the gap between "the code works" and "the service is operable" is written down
rather than discovered during the first incident. Stage E (Steps 27–30) closes it.

---

## What exists today

| Concern            | State                                                                                                    |
| ------------------ | -------------------------------------------------------------------------------------------------------- |
| Structured logging | ✅ `structlog`, JSON in non-local environments, tenant id on every job log line                          |
| Health endpoints   | ✅ `GET /healthz` (liveness, no database) and `GET /readyz` (readiness, 503 when not)                    |
| Container image    | ✅ Multi-stage, non-root, one image with two entrypoints                                                 |
| Migrations         | ✅ Alembic, round-trip tested in CI                                                                      |
| Metrics            | ✅ Stage, model, cost, queue and evaluation counters — exported only when an OTLP endpoint is set        |
| Tracing            | ✅ Spans across every pipeline stage, carried over the queue by the envelope's `traceparent`             |
| Fair scheduling    | ✅ On `CAIRN_QUEUE_BACKEND=postgres`: priority and per-tenant limits. Not on Pub/Sub                     |
| Backup / restore   | ⚠️ Rehearsable and self-verifying (`make restore-rehearsal`) — rehearsed locally, never in production    |
| SLOs               | ⚠️ Defined with stated measurement sources (`docs/SLOS.md`) — three of five measurable today             |
| Release gates      | ✅ `uv run python -m cairn_api.ops.gates_cli`, non-zero while anything blocks                            |
| Connector health   | ⚠️ `GET /v1/internal/operations/connectors`, counts and categories only — no source has ever delivered   |
| Slack limits       | ⚠️ Ack budget, retries and the 30,000/hour ceiling recorded as constants — none of the three is measured |
| Alerting           | ❌ Thresholds are written below; no rules and no destination are configured                              |
| Dashboards         | ❌ None                                                                                                  |
| On-call            | ❌ No rotation, no escalation path                                                                       |

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

| Signal                    | Warning                                    | Page                                                | First action                                                                                                                                                                                                                                            |
| ------------------------- | ------------------------------------------ | --------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Queue backlog**         | oldest unprocessed > 15m                   | > 1h, or depth still rising                         | Check the worker is running at all (`queue.inMemoryBroker` true means jobs are lost on restart). Then read `tenantsWaiting`: one is a backfill draining, many is too little capacity. See **The scheduler**.                                            |
| **DLQ growth**            | any dead letter                            | > 5 in an hour                                      | Read the dead-letter reason. A repeated `UnknownJobTypeError` is a deploy that registered no handler; a repeated `DeliveryNotFoundError` is a retention sweep racing a job.                                                                             |
| **Model cost spike**      | 2× the daily median                        | 5×, or a ceiling refusal                            | `operations/spend` by stage. A spike in `synthesis` is usually a brief cache miss storm; in `extract`, a backfill. The per-tenant ceiling in `spend.py` refuses before the bill grows.                                                                  |
| **Evaluation decline**    | any `blocked` case                         | groundedness below the gate                         | Do not ship. `blocked` means a boundary or tone violation — the two md/10 §5 treats as zero-tolerance. Re-run `make eval` against the same dataset before believing a single run.                                                                       |
| **Telemetry export**      | exporter errors > 0                        | no spans for 15m                                    | Telemetry failing must never fail the work: `_attributes` drops unsafe values and `stage()` swallows nothing else. If spans stop, the pipeline is still correct and the dashboard is not — fix the exporter, do not roll back the pipeline.             |
| **Connector failures**    | any `errorsByCategory`                     | one provider failing across many workspaces at once | Count the workspaces first — one is that workspace, many on one provider is the provider or a credential of ours. `disconnected` and `revoked` are the customer's decision and are not incidents. See **Connectors** and `docs/runbooks/connectors.md`. |
| **Slack event budget**    | 24,000 events in an hour for one workspace | 30,000 — the ceiling                                | **Events past the ceiling are dropped, not queued, and never redelivered.** Not recoverable: CAIRN holds no history scope. Tell the customer; there is nothing to replay. Not measurable today — see **What is NOT monitored**.                         |
| **Slack acknowledgement** | any `x-slack-retry-reason: http_timeout`   | timeouts on more than one workspace                 | The 3-second budget is being missed, and Slack discards after three attempts. Move work out of the request path; acknowledge, then queue. Not measured today — see **What is NOT monitored**.                                                           |

### What the numbers mean

- **Oldest unprocessed delivery** is the honest latency measure. Queue depth
  alone hides one stuck job behind a thousand fast ones.
- **Spend is per replica.** `operations/spend` reads an in-process ledger, so on
  N instances the real figure is higher. Stated on the screen; the durable
  version needs the metrics exporter configured.
- **Evaluation counts are from the committed baseline**, not a live run. A
  dashboard that graded on demand would be spending model budget on a page
  refresh.
- **A connector's `null` is not a zero.** Only GitHub has a durable inbound
  record, so the other providers report `null` delivery counts with a reason. A
  zero there would read as "connected and quiet", which is the most reassuring
  possible rendering of "this cannot be seen from here".

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

## Connectors

Slack and Google Chat arrive in Step 32. The operations half is here first, so
that when they do, an operator can tell whether a source is working **without
any customer content leaving the product**.

`cairn_api.ops.connectors.connector_health` is the read model: one row per
provider, over `source_connections` — the provider-neutral connection record a
migration trigger already projects every `github_installations` write into. It
is counts, ages and categories only. There is no field for a message, a channel,
a space, an account label, a repository or a person, and a test asserts that over
the model's fields rather than over the source, so one cannot be added quietly.

It carries the same access rules as everything else under
`/v1/internal/operations/*`: `engineering` or `security` staff role, nothing
weaker. Support and Billing Ops cannot read it — least privilege applies
internally too, and a connector screen is exactly the surface somebody would
argue Support needs.

### The three causes that look identical

A source that has stopped delivering shows the same thing on every dashboard:
zero events. The cause is one of three, and they need completely different
responses.

| What you see                                                                                      | What it means                        | What to do                                                                                                               |
| ------------------------------------------------------------------------------------------------- | ------------------------------------ | ------------------------------------------------------------------------------------------------------------------------ |
| `workspacesByState` shows `disconnected` or `revoked`; no error category                          | The customer turned it off           | Nothing technical. **Never re-issue credentials** — that is an attempt to restore access somebody deliberately withdrew. |
| `errorsByCategory` shows `authentication_expired` or `permission_revoked`                         | Our credential is no longer accepted | Ours to fix. A rotation we missed, or a scope an admin removed that needs the customer to re-authorise.                  |
| `errorsByCategory` shows `provider_unavailable` or `rate_limited`, across many workspaces at once | The provider is down or throttling   | Nothing to fix. Check their status page and back off. Time fixes `rate_limited`; nothing else does.                      |
| `state` = `connected` with `health` = `failing`                                                   | Authorised and delivering nothing    | The worst one to miss. A customer seeing a green "connected" while nothing ingests is worse than an honest failure.      |

**Count the workspaces before deciding.** One is about that workspace; many on
one provider, starting within the same few minutes, is the provider or one of
our credentials. Full procedure in `docs/runbooks/connectors.md`.

### Slack

Slack's published limits are recorded in `ops/connectors.py` as constants
(`SLACK_LIMITS`), so a threshold here and a number in the runbook cannot drift
apart. The full procedure is in `docs/runbooks/connectors.md`.

| Limit            | Value                                     | Why an operator cares                                                                                        |
| ---------------- | ----------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| Acknowledgement  | HTTP 2xx within **3 seconds**             | The entire budget, TLS and cold start included. Anything slower is discarded after three attempts.           |
| Retries          | **3 total** — immediately, 1m, 5m         | `x-slack-retry-num` and `x-slack-retry-reason` say which attempt and why. Rising `http_timeout` is ours.     |
| Event deliveries | **30,000 per workspace per app per hour** | Past it Slack **drops** events. Not queued, not redelivered, and CAIRN holds no history scope to fetch them. |
| Web API          | Tiered, separate, `Retry-After` on 429    | `conversations.list` and `users.info` have their own limits. Never call `users.info` per message.            |

**The scopes are exactly `channels:history`, `channels:read`, `users:read`.**
`channels:join` is deliberately not among them: CAIRN does not add itself to
channels, a customer decides what it sees by inviting the bot, and **an
uninvited bot receives nothing at all** while every configuration check passes.
That is the first thing to check when "the scopes look right but no events
arrive", and it is the first step in the runbook for that reason.

`app_uninstalled` and `tokens_revoked` both signal the customer removing us,
need no scopes, and **arrive in no guaranteed order** — teardown is idempotent
and keyed on `team_id`. Neither is an incident and neither is a reason to
re-issue a credential.

**A rate-limited Slack workspace is data loss, not a delay.** It is the only
connector failure in this document that cannot be repaired after the fact, so
the response is disclosure rather than recovery.

### The metrics

`cairn.connector.deliveries`, `cairn.connector.errors` and
`cairn.connector.rate_limit_windows`, carrying `source`, `outcome`,
`error_category` and an optional `tenant_id` and nothing else. A workspace is
the smallest thing any of them may be grouped by — it is a customer, not a
person — and it is offered because Slack's ceiling is per workspace, so a
platform-wide total cannot warn anybody they are about to lose data. The
reduction to a category
happens inside `ops/connectors.py` rather than at the call site: the telemetry
allow-list checks attribute _keys_, so a caller handed a free string could pass a
provider's error body as an `error_category` and it would be waved through.
Provider errors quote the request that failed, which for Slack and Chat means
channel names, user handles and message fragments.

There is no per-channel, per-space, per-conversation or per-account attribute,
and no allow-list entry that could carry one. That is the boundary, not an
omission, and a structural test rejects the addition.

### What is NOT monitored

Honest gaps, so they are read here rather than discovered during an incident.

- **No provider writes `health` or `last_successful_sync_at` yet.** GitHub's rows
  come from the migration's projection of `github_installations`, and that table
  recorded neither, so every GitHub connection reads as never-synced with
  `unknown` health. For GitHub the delivery counts are the real signal; the
  health and sync-age columns become meaningful per provider as Step 32's
  connectors start writing them.
- **Only GitHub has a durable inbound record.** Slack and Google Chat report
  `null` delivery counts with a reason rather than zero.
- **Slack's distance from its 30,000-event ceiling is not measured.** The
  ceiling is per workspace per hour; every count in the read model is
  platform-wide, and Slack has no inbound record here to count. The published
  number is on the Python read model (`event_budget_per_hour`, warn at
  `event_budget_alert_at`) — `ConnectorHealthView` does not expose it, so the
  comparison is against `SLACK_LIMITS` in `ops/connectors.py` — and
  the comparison is manual. Nothing estimates the fraction, deliberately: a
  platform-wide gauge would read 3% while one workspace sat at 100% and lost a
  morning. Closing it needs a per-workspace inbound event count —
  `record_connector_delivery` already accepts `tenant_id`; the Slack connector
  has to pass it.
- **Slack acknowledgement latency is not recorded.** The 3-second budget is
  documented and unmeasured. A workspace losing every event to `http_timeout` is
  visible only as a silence, and the evidence (`x-slack-retry-reason`) is in
  Slack's request rather than in anything CAIRN stores.
- **Dropped Slack events are counted as windows, never as events.**
  `cairn.connector.rate_limit_windows` says a window was throttled; how many
  events were lost inside it is unknowable, because Slack does not say and there
  is no history scope to reconcile against.
- **No chat connector has ever delivered anything.** `inboundVerified` is false
  for Slack and Google Chat because they do not exist yet, and false for GitHub
  in any environment that has not received a real webhook — it is derived from
  recorded deliveries, not from configuration. The `connectors` release gate says
  the same thing at release time.
- **There is no endpoint yet.** The read model is a typed function; mounting it
  at `/v1/internal/operations/connectors` behind `OPERATIONS_ROLES` is a
  separate, small change to `api/routers/internal.py`.
- **Nothing is alerting.** As with every other threshold in this document: no
  destination, no rotation, nobody paged. Somebody has to open the screen.

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

| Gate           | What closes it                                                                                                                                                                                                                                                                                                                                                                                                                            |
| -------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **email**      | `uv run python -m cairn_api.email.probe --to you@example.com`, then confirm it **arrives** — check spam. The probe refuses to run on the console backend, because a pass there would mean nothing. A relay accepting a message is not a person receiving one.                                                                                                                                                                             |
| **telemetry**  | Set `OTEL_EXPORTER_OTLP_ENDPOINT`, restart, send one webhook, and find its trace in the collector. An endpoint that refuses connections looks identical to one nobody has sent to.                                                                                                                                                                                                                                                        |
| **github**     | Install the App on one repository, push a real commit, and confirm the delivery verifies its signature and produces a fact attributed to the right person.                                                                                                                                                                                                                                                                                |
| **model**      | `uv run python -m cairn_api.evaluation.runner --pipeline real` against live Vertex, and record the baseline. Every quality number in this repository was produced by a deterministic stand-in, and says so.                                                                                                                                                                                                                               |
| **audit-sink** | Replicate the audit chain to an append-only sink outside this database. Until then the log is **tamper-evident, not tamper-proof** — see below.                                                                                                                                                                                                                                                                                           |
| **connectors** | Install the app, **`/invite` the bot to one channel** — an uninvited Slack bot receives nothing, and CAIRN never requests `channels:join` — post one message, and confirm `inboundVerified` for that provider. Read `inboundVerified`, not `deliveriesLastHour`: Slack has no inbound record, so that count stays `null` forever. This gate **cannot reach `PASS`**: every input it has is configuration, and none of them is a delivery. |

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
- **No connector has ever delivered.** The connector health read model works and
  reports honestly; what it currently reports is that nothing has been verified.
  The `connectors` release gate is `MANUAL` and structurally cannot be anything
  better until a real event arrives from a real workspace.
