# Staging: deploy, migrate, roll back, read logs

**Nothing below has been run. Staging does not exist yet.**

That sentence is the whole point of this heading. Every command here was derived from
`infra/render.yaml`, the Dockerfile and the migrations, and each is marked with whether it has been
executed. A checklist that claims to be tested and is not is worse than no checklist, because the
first person to follow it does so during a deploy.

| Marker | Meaning                                                       |
| ------ | ------------------------------------------------------------- |
| ✅     | Run, here, against a real target                              |
| ⛔     | Never run — needs the Render account and the staging database |

---

## Before anything: create what code cannot

⛔ These are human actions against an account this repository holds no credentials for.

1. Create the Render blueprint from `infra/render.yaml`. It creates one Postgres 16 instance, one
   web service and one worker.
2. Set every `sync: false` value in the dashboard, once. The inventory and the reasoning for each is
   in `infra/DECISIONS.md` §4. Nothing is pasted into a file, a migration or a terminal that keeps
   history.
3. Point `api.staging.<domain>` at the web service and `app.staging.<domain>` at the app.

### The two database roles

⛔ Run once against the staging database, as its owner. The application must **not** connect as the
owner.

```sql
-- The application role. NOBYPASSRLS is the whole tenant isolation mechanism:
-- row-level security is silently inert for a superuser or a BYPASSRLS role,
-- FORCE or not. Preflight refuses to boot if this role holds either.
CREATE ROLE cairn_app LOGIN PASSWORD '<from the secret store>' NOSUPERUSER NOBYPASSRLS;

-- The platform role. This one NEEDS BYPASSRLS: the webhook path resolves an
-- installation to a workspace before any tenant context exists, and every table
-- is FORCE ROW LEVEL SECURITY, so without it that lookup returns nothing.
CREATE ROLE cairn_platform LOGIN PASSWORD '<from the secret store>' NOSUPERUSER BYPASSRLS;
```

`CAIRN_DATABASE_URL` uses `cairn_app`; `CAIRN_PLATFORM_DATABASE_URL` uses `cairn_platform`.

---

## Deploy

⛔ `autoDeploy: false` is set deliberately — a push to `main` does not ship. Deploy from the
dashboard, or:

```bash
render deploys create cairn-staging-api --wait
render deploys create cairn-staging-worker --wait
```

Both, always. They are one image and one revision; deploying one is the version skew the single
image exists to prevent.

## Migrate

⛔ Separately from the rollout, never as a side effect of it — a migration that runs as part of a
deploy cannot be rolled back with the deploy that ran it.

```bash
# CAIRN_APP_ROLE_PASSWORD is required outside local: the migration refuses to
# create the application role with the development password, which is public in
# this repository.
CAIRN_ENVIRONMENT=staging \
CAIRN_APP_ROLE_PASSWORD='<from the secret store>' \
CAIRN_PLATFORM_ROLE=cairn_platform \
CAIRN_DATABASE_URL='<staging app url>' \
  uv run alembic upgrade head
```

✅ The same command shape is what runs locally, and the migrations are verified up, down and up
again on PostgreSQL 16 with pgvector.

**Confirm isolation held: start the API and watch it boot.** Preflight checks both roles at startup
and refuses to serve if the application role is a superuser or holds `BYPASSRLS`, or if the platform
role lacks it. If the API is up, that check passed — there is nothing else to run.

```bash
curl -sf https://api.staging.<domain>/healthz   # liveness, no database
curl -sf https://api.staging.<domain>/readyz    # readiness, 503 until the database answers
```

## Roll back one release

⛔ Code and schema roll back separately, and in that order.

```bash
render rollbacks create cairn-staging-api --to <previous-deploy-id>
render rollbacks create cairn-staging-worker --to <previous-deploy-id>
```

Then, and **only** if the previous revision cannot run against the current schema:

```bash
CAIRN_ENVIRONMENT=staging CAIRN_DATABASE_URL='<staging app url>' \
  uv run alembic downgrade -1
```

Most migrations here are additive and a code rollback alone is enough. Reach for `downgrade` when
the old code cannot read the new schema, and read the migration first — a downgrade that drops a
column drops the data in it.

## Read logs

⛔

```bash
render logs cairn-staging-api --tail
render logs cairn-staging-worker --tail

# The chain a delivery follows, in order.
render logs cairn-staging-worker --text github.delivery_attributed
render logs cairn-staging-worker --text understand.applied
```

Logs are structured JSON. They carry counts, states and categories and never payloads: the
telemetry allow-list is closed, so a repository name or a person's handle will not be there to
search for — by design, not by omission.

---

## The GitHub App

Created from `scripts/create_github_app.py`, installed on one account, and bound to a workspace by
an authenticated connect call. Moving it to staging is one field on the App: replace the tunnel URL
with `https://api.staging.<domain>/v1/webhooks/github`. Nothing else changes - the manifest, the
connect flow and the verification are identical.

---

## Data in staging

**No customer-looking data.** Non-production environments hold synthetic data only.

`apps/api/src/cairn_api/db/seed.py` is synthetic by construction — the accounts are
`ali@acme.example.com`, `sara@acme.example.com`, `jordan@globex.example.com` and
`sam@freelance.example.com`, all on RFC 2606 reserved domains, and the shared password is a public
constant in the source. Nothing in it derives from a real person or a real repository.

It is still not run in staging by default. Staging exists to prove that a real GitHub delivery
becomes a real fact, and pre-seeded facts make that proof harder to read, not easier.

---

## What is still red after this, honestly

- **Email.** `CAIRN_EMAIL_BACKEND=smtp` with no SMTP credentials until Session 11, so invitations
  and verification links fail. Correct and deliberate: the alternative, `console`, is refused in a
  deployed environment because an invited colleague would never hear from us.
- **Telemetry.** `CAIRN_TELEMETRY_OPTIONAL=true` until a collector exists in Session 11.
- **Point-in-time recovery.** Daily managed backups only. Worst case is 24 hours of lost facts,
  briefs, corrections and consent decisions. See `docs/BACKUP-RESTORE.md`.
- **Autoscaling.** Worker count is manual. This host autoscales on CPU and the worker is
  latency-bound, so CPU would never fire.
