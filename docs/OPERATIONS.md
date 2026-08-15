# Running CAIRN

**Status: pre-production.** Nothing here has run outside a development machine. This document
exists so that the gap between "the code works" and "the service is operable" is written down
rather than discovered during the first incident. Stage E (Steps 27–30) closes it.

---

## What exists today

| Concern            | State                                                                           |
| ------------------ | ------------------------------------------------------------------------------- |
| Structured logging | ✅ `structlog`, JSON in non-local environments, tenant id on every job log line |
| Health endpoint    | ✅ `GET /health`                                                                |
| Container image    | ✅ Multi-stage, non-root, one image with two entrypoints                        |
| Migrations         | ✅ Alembic, round-trip tested in CI                                             |
| Metrics            | ❌ Nothing emits or scrapes                                                     |
| Tracing            | ❌ No spans, no correlation id across the queue boundary                        |
| Alerting           | ❌ No rules, no destination                                                     |
| Dashboards         | ❌ None                                                                         |
| Backup / restore   | ❌ No procedure, never rehearsed                                                |
| SLOs               | ❌ Undefined                                                                    |
| On-call            | ❌ No rotation, no escalation path                                              |

**The honest reading:** the system can be started and will tell you what it is doing in its logs.
It cannot yet tell you whether it is healthy, and nobody would find out if it stopped.

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

## Before this is production-ready

In rough order of what would hurt most by its absence:

1. **Alerting on the dead-letter queue.** A job that fails permanently currently disappears quietly.
2. **A correlation id carried across the queue**, so one webhook can be followed to one brief.
3. **Rehearsed restore.** A backup nobody has restored from is a hypothesis.
4. **Spend alerting**, not only spend capping — a ceiling that is being hit daily is a signal.
5. **SLOs**, so "slow" becomes a number somebody agreed to.
