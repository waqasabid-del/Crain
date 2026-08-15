"""Export the OpenAPI schema.

The FastAPI routes are the single source of truth. This emits the OpenAPI
document, from which the TypeScript client's types are generated — so both ends
of the language boundary describe the same contract by construction rather than
by discipline.

This is the mechanism behind Step 9's exit criterion: *a breaking backend change
fails the frontend build*. A regeneration test in CI compares the committed
document to a fresh render, and the TypeScript build then type-checks against
it. Rename a field in Python and the frontend stops compiling — which is the
whole reason for choosing REST with codegen over hand-written client types
(md/06 §6A.2).

Run via ``make schema``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from cairn_api.api.app import create_app
from cairn_api.config import Settings

#: Committed to the repository, like the ActivityEvent schema and for the same
#: reason: it makes a contract change visible in review, which is exactly where
#: a breaking change should be noticed rather than in a failing deploy.
REPO_ROOT = Path(__file__).parents[5]
OPENAPI_PATH = REPO_ROOT / "packages" / "api-client" / "openapi.json"


def build_openapi() -> dict[str, Any]:
    """Render the OpenAPI document.

    Built with explicit ``local`` settings rather than whatever the developer's
    environment holds. The generated document must depend only on the code, or
    two people regenerate it and get different files — and the drift test starts
    failing for reasons unrelated to any change.
    """
    settings = Settings(environment="local")
    schema: dict[str, Any] = create_app(settings).openapi()

    # FastAPI stamps the running app's version. Pinned to the same value the
    # factory declares so a regeneration never produces a spurious diff.
    schema["info"]["version"] = "0.1.0"
    return schema


def write_openapi(path: Path = OPENAPI_PATH) -> Path:
    """Write the document to disk, returning the path written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    # Sorted keys and a trailing newline keep the diff stable, so regenerating
    # without a route change produces no diff at all.
    path.write_text(json.dumps(build_openapi(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


if __name__ == "__main__":
    written = write_openapi()
    print(f"Wrote {written}")
