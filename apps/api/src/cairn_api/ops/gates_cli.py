"""Print the release gates for the current configuration.

    uv run python -m cairn_api.ops.gates_cli

Exits non-zero while any gate still blocks, so a deployment pipeline can call it
as a step rather than a person reading a table and deciding. The output names
the next action for each gate, because "blocked" without a remedy is an
observation rather than a runbook.
"""

from __future__ import annotations

import sys

from cairn_api.ops.release_gates import GateStatus, evaluate_release_gates

_MARK = {
    GateStatus.PASSED: "PASS",
    GateStatus.BLOCKED: "BLOCK",
    GateStatus.UNVERIFIED: "MANUAL",
}


def main() -> int:
    gates = evaluate_release_gates()

    for gate in gates:
        print(f"[{_MARK[gate.status]:>6}] {gate.name}: {gate.detail}")
        if gate.next_step:
            print(f"          -> {gate.next_step}")

    blocking = [gate for gate in gates if gate.blocks_release]
    if not blocking:
        print("\nEvery release gate has passed.")
        return 0

    manual = [gate.name for gate in blocking if gate.status is GateStatus.UNVERIFIED]
    unconfigured = [gate.name for gate in blocking if gate.status is GateStatus.BLOCKED]

    print(f"\n{len(blocking)} gate(s) still block a live release.")
    if unconfigured:
        print(f"  Not configured:      {', '.join(unconfigured)}")
    if manual:
        print(f"  Needs a real check:  {', '.join(manual)}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
