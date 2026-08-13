"""Export the ``ActivityEvent`` JSON Schema.

The Python model is the single source of truth. This emits JSON Schema, from
which TypeScript types are generated — so the two languages describe the same
shape by construction rather than by discipline.

A test regenerates and compares, so a model change that is not propagated fails
CI rather than surfacing later as a frontend that quietly disagrees with the
backend about what an event looks like.

Run via ``make schema``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from cairn_api.events.schema import ActivityEvent

#: Checked into the repository. Generated files are committed deliberately:
#: it makes the diff of a schema change visible in review, which is exactly
#: where a breaking change should be noticed.
REPO_ROOT = Path(__file__).parents[5]
SCHEMA_PATH = REPO_ROOT / "packages" / "types" / "schemas" / "activity-event.json"


def build_schema() -> dict[str, Any]:
    """Produce the JSON Schema document."""
    schema = ActivityEvent.model_json_schema(mode="serialization")
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = "https://cairn.ai/schemas/activity-event/v1.json"
    schema["title"] = "ActivityEvent"
    schema["description"] = (
        "A CloudEvents 1.0 envelope carrying a CAIRN activity payload. "
        "Generated from apps/api/src/cairn_api/events/schema.py — edit that, not this."
    )
    return schema


def write_schema(path: Path = SCHEMA_PATH) -> Path:
    """Write the schema to disk, returning the path written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    # Sorted keys and a trailing newline keep the diff stable, so a regeneration
    # with no model change produces no diff at all.
    path.write_text(json.dumps(build_schema(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


if __name__ == "__main__":
    written = write_schema()
    print(f"Wrote {written}")
