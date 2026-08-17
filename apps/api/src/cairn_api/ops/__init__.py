"""Operations: what CAIRN holds itself to, and what it refuses to claim.

Three things live here that are not features and are not infrastructure:

- `slo.py` — what "slow" and "broken" mean, as numbers with a stated
  measurement source rather than adjectives in a runbook.
- `backup.py` — a backup and a restore that verifies itself, because a backup
  nobody has restored from is a hypothesis.
- `release_gates.py` — the external dependencies CAIRN cannot verify from
  inside itself, and the distinction between "configured" and "proven".

All three are deliberately in the application rather than in a deployment
repository. An objective that lives beside the code is one a reviewer sees when
they change the thing it measures.
"""

from cairn_api.ops.release_gates import (
    Gate,
    GateStatus,
    blocking_gates,
    evaluate_release_gates,
)

__all__ = ["Gate", "GateStatus", "blocking_gates", "evaluate_release_gates"]
