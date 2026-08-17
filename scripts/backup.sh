#!/usr/bin/env bash
#
# Take a logical backup of a CAIRN database.
#
# A thin wrapper. All of the behaviour — the production-name refusal, the
# client-binary fallback into the compose container, the timing — lives in
# `cairn_api.ops.backup`, where it is type-checked and tested. A shell script
# that reimplemented any of it would be the copy that drifts.
#
#   ./scripts/backup.sh                       # the local development database
#   ./scripts/backup.sh --dump /tmp/cairn.sql # somewhere specific
#
# Restoring is a separate command on purpose: see ./scripts/restore-rehearsal.sh.
# A backup and a restore sharing an entry point is how somebody restores when
# they meant to back up.
set -euo pipefail

cd "$(dirname "$0")/../apps/api"
exec uv run python -m cairn_api.ops.backup dump "$@"
