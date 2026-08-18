# Infrastructure decisions

Five decisions, made once, so that Session 9 is execution rather than argument. Each records what
was chosen, what it costs, and what it does not buy — the last being the part a decision record
usually omits and an incident usually needs.

Status: **decided, not deployed.** Nothing in this document has been applied. `infra/README.md` is
still accurate about what exists.

---

## 1. Host: Render

Two services from one image, declared in `infra/render.yaml`: a `web` service running the uvicorn
factory and a `worker` service running `python -m cairn_api.jobs.main`. The Dockerfile already ships
both entrypoints and the API is the default command, so the worker is a `dockerCommand` override and
nothing about the image changes.

**Why.** It is the only option among these where the two-process model, managed Postgres 16 with
pgvector, and per-service secrets are all first-class and declarable in one file that lives in this
repository. A background worker is a service type rather than a workaround, secrets are set in the
dashboard and referenced with `sync: false` so they cannot be committed, and Postgres is a managed
instance with automated daily backups rather than a database the team operates.

| Rejected      | Why not                                                                                                                                                                                     |
| ------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Fly.io**    | `[processes]` expresses two-from-one-image best of any option, but its Postgres was for years an instance you operate yourself — backups included — and that is the opposite of decision 2. |
| **Railway**   | Simplest to click through, weakest to describe in code; the backup and point-in-time story is thinner, and this repository's standard is config as code.                                    |
| **Cloud Run** | Reintroduces GCP after Vertex was dropped, adds Cloud SQL's cost floor, and needs `min-instances=1` for the worker anyway — paying for always-on without the simplicity.                    |
| **A VM**      | Cheapest and the most work. Somebody then owns patching, restarts, backups and TLS, and that somebody is one person building their first solo product.                                      |

**What this does not buy: autoscaling on queue depth.** Render autoscales on CPU and memory.
`docs/OPERATIONS.md` is explicit that the worker's stages are latency-bound on an external API, so
**CPU stays flat while work piles up** — CPU autoscaling would not merely be imprecise here, it
would never fire. Worker count is therefore a manual decision until something better exists, taken
from `tenantsWaiting` and `longestWaitMinutes` on `/v1/internal/operations/queue`, whose meanings
are already tabulated in OPERATIONS.md. Writing this down is the point: an autoscaler that cannot
see the signal is worse than a number somebody sets on purpose.

---

## 2. Database: Render Postgres 16, with pgvector

Version pinned to 16 to match `docker-compose.yml`, so local and staging differ in scale rather than
in behaviour. `pgvector` is required — the temporal graph's entry-point search is a vector search —
and is enabled with `CREATE EXTENSION vector` in the first migration that needs it.

Automated daily backups come with the managed instance and are the only backups that will exist.

**The gap, stated rather than assumed.** `docs/BACKUP-RESTORE.md` is honest that what CAIRN has
today is a **logical dump and not point-in-time recovery**: restore returns the database to the
moment `pg_dump` started, so a nightly cadence means a worst case of twenty-four hours of lost
facts, briefs, corrections and consent decisions. PITR — continuous WAL archiving, recovery to a
chosen second — is the goal and is a paid tier on this host. Staging runs without it deliberately;
production must not. `scripts/backup.sh` keeps its real job either way, which is to rehearse on a
copy that what the provider stored can actually be read back.

Also still unarranged, and unchanged by this decision: an agreed retention schedule, offsite and
cross-region copies, and encryption with a key outside the database's blast radius.

---

## 3. Queue backend: `postgres`

`CAIRN_QUEUE_BACKEND=postgres` in every deployed environment.

**Why: fairness is only expressible where every worker sees the same queue.** Priority and
per-tenant fairness are decisions about the queue as a whole — a live push must outrank a backfill
however long the backfill has waited, and a tenant's second job must lose to another tenant's first.
PostgreSQL is the only backend where that comparison can be made at all. `FOR UPDATE SKIP LOCKED`
decides lease ownership in the database rather than in application logic, and the queue metrics the
alerts fire on come from the same rows.

**Pub/Sub is not needed and would cost something real.** Without GCP there is no reason to run it,
and on that backend one customer's 90-day backfill can occupy every worker and delay another
customer's live push — it has no fairness and no priority. It also emits no queue metrics, so the
dead-letter and retry alerts would have nothing to fire on. The in-memory broker is not a candidate:
the API and the worker are separate processes and would not share a queue, which presents as an
acknowledged webhook that never becomes a fact.

---

## 4. Secrets

**The rule: a secret never appears in a file in this repository, in a migration, in CI output, or in
a terminal or chat transcript.** Secrets live in the host's per-service store and are injected as
environment variables at runtime. In `infra/render.yaml` every one of them is declared `sync: false`
— the name is in the repository, the value is set once in the dashboard and never leaves it.

`.env.example` is the inventory, and is now enforced as one: `apps/api/tests/test_env_inventory.py`
fails if a `Settings` field is undocumented, if a documented name is read by nothing, or if any
secret-shaped name is committed with a value after the `=`. When that test was written, **29 of 55
settings were undocumented**, including the connector encryption key and every Slack, Google Chat
and Google Meet credential.

### What staging needs

| Secret                           | Why staging needs it                                                     |
| -------------------------------- | ------------------------------------------------------------------------ |
| `CAIRN_DATABASE_URL`             | The application role — `NOSUPERUSER`, `NOBYPASSRLS`, so RLS applies      |
| `CAIRN_PLATFORM_DATABASE_URL`    | The platform role, which holds `BYPASSRLS` for cross-tenant reads        |
| `CAIRN_APP_ROLE_PASSWORD`        | Required by migrations in a deployed environment; not read by `Settings` |
| `CAIRN_SECRET_KEY`               | Session signing. A rotation signs everybody out, which is the intent     |
| `CAIRN_CONNECTOR_ENCRYPTION_KEY` | Encrypts stored connector tokens; without it a published dev key is used |
| `CAIRN_GITHUB_APP_ID`            | Not secret, kept beside the pair it is useless without                   |
| `CAIRN_GITHUB_PRIVATE_KEY`       | Grants every installed repository until somebody notices                 |
| `CAIRN_GITHUB_WEBHOOK_SECRET`    | The only unauthenticated write path in the service verifies against it   |
| `CAIRN_OPENAI_API_KEY`           | Billed per call                                                          |
| `CAIRN_SMTP_*`                   | Session 11. `CAIRN_EMAIL_BACKEND=smtp` refuses to boot without it        |

Not needed by staging until their connectors are configured: the Slack, Google Chat and Google Meet
credentials. They are documented in `.env.example` so that "not set" is a visible decision rather
than an oversight.

**Rotate what has been exposed.** Any key pasted into a chat, a terminal history or a log is
compromised regardless of what was done with it afterwards, and rotation is the only response that
does not depend on a guess about who read it. Three OpenAI keys were pasted into this project's
working sessions and all three must be rotated. `CAIRN_CONNECTOR_ENCRYPTION_KEY` is the exception
that needs a plan rather than a rotation: rotating it re-encrypts nothing, so every connector must
be reconnected, which makes it a customer-visible event.

---

## 5. DNS and origins

| Environment | API                     | App                     |
| ----------- | ----------------------- | ----------------------- |
| Local       | `http://localhost:8000` | `http://localhost:3000` |
| Staging     | `api.staging.<domain>`  | `app.staging.<domain>`  |
| Production  | `api.<domain>`          | `app.<domain>`          |

Two hostnames rather than one with a path split, so that a cookie scoped to the registrable domain
reaches both while the API and the app stay separately deployable. `CAIRN_SESSION_COOKIE_DOMAIN`
becomes `.staging.<domain>` in staging for exactly that reason; it stays unset locally, where both
processes are on `localhost`.

**Plan for the config's refusals now, because they are correct and they will fire on the first
deploy.** Outside `local`, `Settings` rejects a wildcard CORS origin and rejects `http://`. So
`CAIRN_PUBLIC_APP_URL=https://app.staging.<domain>` and `CAIRN_CORS_ALLOWED_ORIGINS` lists that
exact origin and nothing else. The app must be served from an origin the API allows or the CSRF
origin check rejects every sign-in with a 403 that looks like nothing happening at all — which is
the failure worth anticipating rather than debugging.
