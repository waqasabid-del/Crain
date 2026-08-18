# infra/

**This directory is no longer empty, and still nothing is deployed.**

`DECISIONS.md` records where CAIRN will run and why. `render.yaml` declares it.
`STAGING.md` is the checklist, with every command marked for whether it has
actually been run — most have not, because the account and the database do not
exist yet. Read that file's markers before trusting a line of it.

Everything below remains true.

---

**This directory was empty on purpose, and that was a gap rather than a decision.**

An `infra/` directory that contains a plausible-looking `main.tf` nobody has
ever applied is worse than an empty one: it reads, to a reviewer or a customer's
security questionnaire, as infrastructure-as-code that exists. This file is here
so nobody has to open the directory to find out.

## What is not built

- **No infrastructure-as-code.** No Terraform, no Pulumi, no gcloud scripts.
  Nothing in this repository creates a Cloud Run service, a Cloud SQL instance,
  a Pub/Sub topic or an IAM binding. The Pub/Sub topic names in
  `config.py` describe resources that must be created by hand today.
- **No environments.** There is no staging and no production. `Settings`
  distinguishes `local`, `test`, `staging` and `production` and refuses to boot
  a deployed environment on development defaults — but only two of those four
  have ever run.
- **No secrets management.** Secrets are read from environment variables and
  `.env`. Nothing integrates with Secret Manager, nothing rotates anything, and
  there is no answer to "who can read the production database password" because
  there is no production database.
- **No deployment.** CI builds the image (see the `docker-build` job) and does
  not push it. There is no registry, no tagging scheme, no rollout and no
  rollback.
- **No observability wiring.** The application emits structured logs via
  structlog and there is no log sink, no metrics backend, no tracing and no
  alerting. Nothing is watching.
- **No durable cost control.** `pipeline/spend.py` bounds one tenant's model
  spend within one process. It does not survive a restart and is not shared
  across replicas, so a tenant's true ceiling today is the per-process ceiling
  multiplied by however many processes are running.

## What exists instead

- `Dockerfile` — a production image, multi-stage, non-root, no dev
  dependencies, with both entrypoints. Built in CI on every pull request so it
  cannot rot; never pushed anywhere.
- `docker-compose.yml` — local PostgreSQL with pgvector and the Pub/Sub
  emulator. Development only; it is not a deployment target and has never held
  real data.
- `apps/api/migrations/` — Alembic migrations, which are the one piece of
  infrastructure state that _is_ under version control.

## What Stage E adds

Stage E is where this directory stops being a README:

1. Terraform for the GCP project described in `md/06-infrastructure.md` —
   Cloud Run for both entrypoints, Cloud SQL with pgvector, Pub/Sub topics and
   the dead-letter topic, and the service accounts each one runs as.
2. Two environments, staging and production, from the same modules with
   different variables — so that "it worked in staging" means something.
3. Secret Manager for the database URLs, the GitHub App private key and the
   webhook secret, injected as Cloud Run secret volumes rather than environment
   variables baked into a revision.
4. A deploy pipeline: build, push to Artifact Registry with an immutable tag,
   migrate, then roll out — with the migration step separate, because a
   migration that runs as a side effect of a rollout cannot be rolled back with
   it.
5. Log and metric sinks, and alerts on the things this codebase already
   measures but nobody receives: the evaluation gate, queue depth, dead-letter
   volume, and the spend ceilings above.

Until then, treat any statement that CAIRN "deploys to GCP" as a plan.
