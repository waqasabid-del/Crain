#!/usr/bin/env bash
#
# Rehearse the restore: dump, restore into a disposable copy, and verify it.
#
# The whole point is the last word. `psql` exits zero on an empty file, so a
# restore that "completed" proves nothing on its own — this checks the alembic
# revision, the row counts on the tables that carry the product's state, and one
# real row read back field by field.
#
#   ./scripts/restore-rehearsal.sh
#   ./scripts/restore-rehearsal.sh --target cairn_restore_2026_08
#
# Exit codes are meant for a scheduler:
#   0  the backup restored and verified
#   1  the restore completed and did NOT verify — the backup cannot be relied on
#   2  refused (a production-looking name, or the source as its own target)
#
# It will not run against a database whose name suggests production, and will
# not restore over its own source. Production backups belong to the managed
# provider; this rehearses the recovery, which is the half nobody tests.
set -euo pipefail

cd "$(dirname "$0")/../apps/api"
exec uv run python -m cairn_api.ops.backup rehearse "$@"
