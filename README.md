# CAIRN

An AI-native team operating system. CAIRN reads the work a team already does — in GitHub, chat, meetings and documents — and produces an honest, automatic picture of what is happening, so nobody updates tickets and nobody's contribution goes unseen.

## Documentation

All specifications live in [`md/`](./md). Start with:

| File                                                              | What it covers                                       |
| ----------------------------------------------------------------- | ---------------------------------------------------- |
| [`00-overview.md`](./md/00-overview.md)                           | Product purpose, users, scope, success metrics       |
| [`16-build-steps.md`](./md/16-build-steps.md)                     | The 30 implementation steps and where we are         |
| [`17-engineering-standards.md`](./md/17-engineering-standards.md) | How we build — workflow, testing, definition of done |
| [`14-decision-register.md`](./md/14-decision-register.md)         | Every architectural decision, with its reasoning     |

Specifications are the source of truth. **If code and `md/` disagree, one of them is wrong** — resolve it, do not ignore it.

## Requirements

| Tool                             | Version | Purpose                   |
| -------------------------------- | ------- | ------------------------- |
| Node.js                          | ≥ 22    | Frontend and tooling      |
| pnpm                             | ≥ 10    | JS package management     |
| Python                           | ≥ 3.12  | Backend and pipeline      |
| [uv](https://docs.astral.sh/uv/) | ≥ 0.8   | Python package management |

## Setup

```bash
pnpm install     # JS dependencies + git hooks
uv sync --dev    # Python dependencies
```

## Commands

```bash
pnpm check       # Everything: lint, types, format (both languages)
pnpm test        # TypeScript tests
uv run pytest    # Python tests

pnpm lint        # Lint TypeScript
pnpm typecheck   # Typecheck TypeScript
pnpm format      # Format everything

uv run ruff check .    # Lint Python
uv run mypy .          # Typecheck Python
```

## Repository layout

```
apps/
  web/        Next.js frontend (Cloudflare Workers + OpenNext)
  api/        FastAPI backend
packages/
  ui/         Design system — black/white tokens, WCAG 2.1 AA
  types/      Shared types, mostly generated from OpenAPI
  config/     Shared lint and TypeScript configuration
services/     Ingestion and pipeline workers — deployed separately
              because they scale independently of the API
infra/        Terraform
md/           Specifications
```

## Contributing

Read [`md/17-engineering-standards.md`](./md/17-engineering-standards.md) first. In short:

- **Trunk-based development.** Short-lived branches, merged via PR.
- **Conventional Commits.** `feat(scope): description` — enforced by commitlint.
- **Tests ship with the code**, not after.
- **Five blocking checks** cannot be waived: tests, CI green, no secrets, tenant isolation verified, AI boundary check.

Git hooks run formatting, linting and secret scanning before every commit, and typecheck plus tests before every push.

## Three things that are easy to get wrong

1. **Tenant isolation.** CAIRN is almost entirely background jobs, and a job that loses tenant context does not fail loudly — it silently reads across tenants. Every queued message carries a tenant ID; jobs fail closed without one.
2. **Certainty is categorical, never numeric.** No confidence percentages reach the interface. See `md/05` §A.2.1.
3. **The product never scores, ranks, or allocates.** This is not a preference — it is what keeps CAIRN outside EU AI Act high-risk classification. See `md/05` §B.3.3.
