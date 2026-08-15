"""The understanding pipeline.

Four stages, of which Step 15 builds the first two:

  1. Classify  — untrusted content in, a label out. Nothing else.
  2. Extract   — untrusted content in, schema-validated facts out. No actions.
  3. Resolve   — deterministic code. The trust boundary (Step 16).
  4. Synthesize — prose from already-validated facts (Step 18).

**The invariant that shapes all of it:** no stage touching untrusted content has
the capability to take an action (md/09 §6.2). Stages 1 and 2 read text people
wrote, some of whom may be adversarial; they can emit a label and a fact, and
there is nowhere in their interfaces to pass them anything more.
"""
