# Service level objectives

**Status: defined, partly measurable, not yet alerted on.** "Slow" is now a
number. Three of the five objectives below can be measured from durable tables
today; two cannot, and this document says so rather than inventing a figure.

The definitions live in code — `apps/api/src/cairn_api/ops/slo.py` — because an
objective that lives in a wiki is one nobody sees when they change the thing it
measures. This page explains them. The code is the source of truth, and the
current readings are on `GET /v1/internal/operations/slo`, which needs an
`engineering` or `security` staff role like every other operations endpoint.

**Nothing here measures a person.** Every objective counts machine work:
deliveries, jobs, requests. "Time to respond" is the natural next objective for
anybody who has run a support team and is exactly the metric md/05 §B.2 promises
never to produce. A test asserts it.

---

## The objectives

| Objective                   | Target                      | Window | Measured from                                                                            | Measurable |
| --------------------------- | --------------------------- | ------ | ---------------------------------------------------------------------------------------- | ---------- |
| **API availability**        | ≥ 99.5% of requests non-5xx | 30d    | The load balancer, or an external prober against `/healthz` and `/readyz`                | ❌ No      |
| **Webhook acknowledgement** | ≤ 500 ms, p95               | 1h     | `cairn.stage.duration` for the webhook route                                             | ❌ No      |
| **Queue first attempt**     | ≤ 15 minutes, worst case    | live   | `max(now() - scheduled_jobs.enqueued_at)` over rows in state `queued`                    | ✅ Yes\*   |
| **Pipeline completion**     | ≥ 95% within 15 minutes     | 24h    | `webhook_deliveries`: `processed_at - created_at` ≤ 15m, over rows created in the window | ✅ Yes     |
| **Delivery error rate**     | ≤ 1%                        | 24h    | `webhook_deliveries`: share of rows in the window with `status = 'failed'`               | ✅ Yes     |

\* On `CAIRN_QUEUE_BACKEND=postgres` only. On any other backend the endpoint
reports it as unmeasurable with the reason, rather than as zero.

**These are starting values, not measured ones** — the same caveat OPERATIONS.md
puts on its alert thresholds, and for the same reason: the system has not run in
production, so every number here was chosen from the shape of the work. Revisit
them after the pilot with a week of real data.

The fifteen minutes in **Pipeline completion** deliberately matches the
`oldest unprocessed > 15m` warning in OPERATIONS.md. Two thresholds describing
the same latency with different numbers is how an operator learns to trust
neither.

---

## What cannot be measured, and why

This is the part that makes the rest of the page worth reading. A status screen
showing three green rows and quietly omitting the other two is worse than no
status screen.

**API availability.** CAIRN stores no request log and no probe history —
deliberately, because a durable per-request record inside the product is a
second copy of who did what. Availability therefore has to be measured from
outside the process: a load balancer, or a prober hitting `/healthz` and
`/readyz`. Neither is deployed (OPERATIONS.md → Dashboards). **This becomes
measurable when a prober exists**, not when someone adds a table.

**Webhook acknowledgement latency.** Nothing durable records when the request
arrived. `webhook_deliveries.created_at` is written _after_ the request has
already been accepted and validated, so it cannot be differenced against an
arrival time that was never stored. The histogram exists and is emitted on every
request; it goes nowhere until `OTEL_EXPORTER_OTLP_ENDPOINT` is set
(OPERATIONS.md → Telemetry is required in a deployed environment). **This becomes
measurable the moment the exporter has a destination.**

Both are kept in the list rather than deleted. An objective nobody wrote down is
one nobody notices is unmeasured.

### One measurement is weaker than it looks

**Queue first attempt** is a live worst case, not a windowed percentile. `ack`
deletes the row when a job completes, so no history of finished waits survives —
the queue can only be asked what is waiting _now_. That is enough to alert on
(it is the same number OPERATIONS.md's backlog row already uses, and queue depth
alone hides one stuck job behind a thousand fast ones) and it is not enough to
answer "what did our queue latency look like last Tuesday". Answering that needs
either the metrics exporter or a completed-job history table, and neither
exists.

---

## Reading the status endpoint

```
GET /v1/internal/operations/slo
```

Each row carries its target, its window, where the number comes from, and one
of three states:

- **A number, with `met: true` or `met: false`.** It was measured.
- **`measured: null`, `met: null`, `measurable: false`, and a reason.** The
  infrastructure cannot produce this number at all.
- **`measured: null`, `met: null`, `measurable: true`, and a note.** It could
  have been measured and there was nothing to measure — an empty window, or a
  queue with nothing in it.

`met` is never `false` for a missing measurement and never `true`. `false` pages
somebody for absent instrumentation; `true` reports an outage as healthy. Only
`null` is honest, and only `null` makes the reader notice.

The response also carries `unmeasurable` and `breaching` as counts, so "four of
five green" cannot be read as healthy when the fifth is availability.

---

## Spend signals

Not an SLO — a cost control — but it is read from the same operations surface
and alerted on from the same table in OPERATIONS.md, so it belongs beside them.

Spend was capped per workspace and silent. It is still capped, and now it
signals:

| Signal                      | Where it appears                                                             | When                                        |
| --------------------------- | ---------------------------------------------------------------------------- | ------------------------------------------- |
| `spend.ceiling_approaching` | Log (`warning`), and `warnings` on `/operations/spend`                       | Spend reaches 80% of a ceiling              |
| `spend.ceiling_refused`     | Log (`error`), `refusals` on `/operations/spend`, and the model-call counter | A ceiling refuses a call                    |
| `spend.ceiling_reached`     | Log (`warning`)                                                              | The ceiling is crossed by the recorded call |

**Both logs are emitted once per unit of work, and both counters increment every
time.** A workspace at ninety per cent of its ceiling makes a call a second; one
line per call is not an alert, it is a denial of service against the log, and
the first occurrence — the line that says when it started — is the one it
buries. The counters are what an alert rule needs; the log is what a person
reads.

The refusal also rides the existing `cairn.model.calls` counter with
`outcome="spend_ceiling_refused"`, zero tokens and zero cost. There is no
bespoke instrument because `telemetry/attributes.py` is a closed allow-list, and
inventing a model call that did not happen would have corrupted the spend
counters it shares. The approach warning has no metric at all for the same
reason — it is a log line and a number on the read model, and that is stated
here rather than implied.

`/operations/spend` shows, per stage: calls, tokens, warnings, refusals, and
`closestApproach` — the highest fraction of a ceiling any single unit of work
reached. **It is not clamped at 1.0.** A ceiling is checked before a call and
recorded after, because a call's cost is unknowable until it returns, so one
call of overshoot is permitted by design; a value far above 1 means one call
costs more than the entire ceiling, which is a configuration error clamping
would render as a tidy "at the limit".

None of it names a workspace. `workspacesRefused` is a count, because "one
workspace" and "every workspace" need different first actions and neither answer
requires naming anybody.

**Spend is still per replica.** These counters live in the process, like the
ledger they read, because no durable spend store exists yet. On N instances the
real figure is higher. The endpoint says so in its own `note` field.

---

## What is still missing

- **No alert has a destination.** Every number above is readable and nothing is
  watching it. That is the Alerting row in OPERATIONS.md and it is unchanged.
- **No error budget.** A target with no budget is a number people argue about
  after the fact rather than a quantity that gets spent.
- **No dashboard.** The status endpoint returns JSON to whoever asks it.
- **No on-call rotation**, so there is nobody for an alert to reach.
