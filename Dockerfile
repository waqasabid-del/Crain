# CAIRN — production image.
#
# ---------------------------------------------------------------------------
# ONE IMAGE, TWO COMMANDS
# ---------------------------------------------------------------------------
# The API (`cairn_api.api.app`) and the worker (`cairn_api.jobs.main`) ship as
# the same image with different commands, not as two images.
#
# They are the same code. Both import the same models, the same queue adapters,
# the same settings and the same pipeline — the worker processes jobs the API
# enqueues, over the same schema. Two Dockerfiles would mean two builds that can
# succeed independently, and the first interesting failure is the one where they
# do: an API on a revision the worker has not been rebuilt for, writing a job
# payload the worker cannot deserialise. One image makes that failure
# impossible to express — a deploy either moves both or neither.
#
# The cost is honest and small: the worker carries uvicorn and the API carries
# the job runner, a few megabytes of Python neither process imports. The
# rejected alternative — a shared base image with two thin children — buys back
# those megabytes and reintroduces exactly the version skew above, because
# nothing then forces the children to be built from the same base at the same
# time.
#
# ---------------------------------------------------------------------------
# WHY MULTI-STAGE
# ---------------------------------------------------------------------------
# The build stage holds uv, a compiler toolchain and the dev dependency group —
# pytest, mypy, ruff. None of that belongs in a running container: every tool
# present is something an attacker who achieves execution can use, and a test
# runner in production is a code-execution primitive with a friendly CLI. The
# final stage copies the virtualenv and nothing else.

# ---------------------------------------------------------------------------
# Stage 1 — build the virtualenv
# ---------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS build

# Pinned by digest-free tag deliberately: uv is a build-time tool whose output
# is pinned by uv.lock, so the lockfile — not the tool version — determines what
# ends up in the image.
COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /usr/local/bin/uv

# UV_LINK_MODE=copy: copy rather than hardlink out of the build cache.
# Hardlinks into a cache mount do not survive into the final stage — the files
# they point at are not part of the layer.
#
# UV_PYTHON_DOWNLOADS=never: use the interpreter this base image already has, so
# the image's Python version is the one the FROM line says it is.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Dependencies before source. This layer is the expensive one and changes only
# when the lockfile does, so ordinary code changes rebuild in seconds.
#
# --no-install-project: the workspace member is installed in the second uv call
# below, after the source arrives. Installing it here would bake a copy of the
# source into the dependency layer and defeat the caching this ordering exists
# for.
# --package cairn-api rather than a bare sync. The root project declares no
# dependencies of its own and lists the workspace member in its *dev* group, so
# `uv sync --no-dev` at the root resolves to nothing at all — a build that
# succeeds and produces an empty virtualenv, discovered at `docker run`.
COPY pyproject.toml uv.lock ./
COPY apps/api/pyproject.toml apps/api/pyproject.toml
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --package cairn-api --no-install-project

COPY apps/api/src apps/api/src
COPY apps/api/alembic.ini apps/api/alembic.ini
COPY apps/api/migrations apps/api/migrations

# --no-dev is the line that keeps pytest, mypy and ruff out of the final image.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --package cairn-api

# ---------------------------------------------------------------------------
# Stage 2 — runtime
# ---------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS runtime

# curl is here for the healthcheck below and is the only addition to the base
# image. Python could do the probe with urllib and no extra package, but a
# HEALTHCHECK that shells into the application's own interpreter fails to
# distinguish "the app is down" from "the interpreter is wedged" — which is the
# case a healthcheck is most needed for.
RUN apt-get update \
    && apt-get install --no-install-recommends -y curl \
    && rm -rf /var/lib/apt/lists/*

# A non-root user with no login shell and no home directory it needs.
#
# Not a formality: this process parses webhooks and model output — content an
# attacker influences — and md/09 §6.2's capability invariant is about what a
# compromised *stage* can reach. This is the same argument one layer down: what
# a compromised *process* can reach. Root inside a container is one namespace
# escape or one mounted socket away from root outside it.
RUN groupadd --system --gid 1001 cairn \
    && useradd --system --uid 1001 --gid cairn --no-create-home --shell /usr/sbin/nologin cairn

# PYTHONUNBUFFERED: tracebacks and log lines appear as they happen rather than
# when a buffer fills. In a container, a buffered crash log is a crash with no
# log.
#
# CAIRN_ENVIRONMENT=production: read by cairn_api.config.Settings, and set here
# rather than left to the deployment. The settings validators refuse to boot on
# development defaults outside `local`, so an image that shipped with `local`
# would ship with that check disabled — and the check exists to catch a revision
# whose database secret was never injected, which is precisely the failure that
# happens on the first deploy of a new environment.
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    CAIRN_ENVIRONMENT=production

WORKDIR /app

COPY --from=build --chown=cairn:cairn /app/.venv /app/.venv
COPY --from=build --chown=cairn:cairn /app/apps/api /app/apps/api

USER cairn

EXPOSE 8080

# Probes /healthz, not /readyz. They answer different questions: readiness
# includes the database, so a brief database blip would fail a readiness-based
# healthcheck and make the orchestrator kill an application process that was
# fine. Restarting the API does not fix PostgreSQL. Liveness asks only whether
# this process can still serve, which is the only question a restart can answer.
HEALTHCHECK --interval=30s --timeout=3s --start-period=15s --retries=3 \
    CMD curl -sf http://localhost:8080/healthz || exit 1

# The API is the default command; the worker overrides it:
#
#   docker run <image>                                    # API
#   docker run <image> python -m cairn_api.jobs.main      # worker
#
# --factory because api/app.py exposes `create_app()` and no module-level `app`
# — a deliberate choice there, so tests can build an instance per settings
# object. Pointing uvicorn at a module attribute that does not exist would fail
# at startup rather than at build time, which is the worst place to learn it.
#
# --host 0.0.0.0 because a container's loopback is not reachable from outside
# it. --port 8080 matches Cloud Run's default contract; PORT is respected where
# the platform sets it.
#
# No --workers: process management belongs to the orchestrator, which can see
# the load and the node. A fixed worker count baked into an image is wrong on
# every machine size except the one it was chosen on, and it hides crashes —
# uvicorn restarts a dead worker and the platform never learns the process died.
CMD ["sh", "-c", "exec uvicorn cairn_api.api.app:create_app --factory --host 0.0.0.0 --port ${PORT:-8080}"]
