"""The API contract, and the checks that keep both languages agreeing on it.

Step 9's exit criterion is *a breaking backend change fails the frontend build*.
That is not a property of the code — it is a property of this test plus the
TypeScript typecheck. Without the drift check, `openapi.json` silently goes stale
and the generated client describes an API that no longer exists, which is worse
than having no generated client: it type-checks.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from cairn_api.api.export_openapi import OPENAPI_PATH, build_openapi


@pytest.fixture(scope="module")
def schema() -> dict[str, Any]:
    return build_openapi()


class TestDrift:
    def test_the_committed_document_is_up_to_date(self, schema: dict[str, Any]) -> None:
        """Regenerate and compare.

        Run `make schema` after any change to a route or a Pydantic model.

        This is the check that makes the contract real. A committed schema that
        nothing verifies is a document describing what the API looked like when
        someone last remembered to run the generator.
        """
        if not OPENAPI_PATH.exists():
            pytest.fail(f"{OPENAPI_PATH} is missing. Run: make schema")

        committed = json.loads(OPENAPI_PATH.read_text(encoding="utf-8"))

        assert committed == schema, (
            "openapi.json is out of date with the FastAPI routes. Run: make schema"
        )

    def test_the_generated_typescript_is_up_to_date(self) -> None:
        """The TypeScript half of the same guarantee.

        Only checks that every path in the schema appears in the generated
        types, rather than regenerating — running Node from pytest would make
        the Python suite depend on a working pnpm install. `pnpm typecheck`
        catches the rest, and this catches the specific case that would
        otherwise pass silently: a new endpoint whose types were never
        regenerated.
        """
        generated = Path(OPENAPI_PATH).parent / "src" / "generated" / "schema.ts"
        if not generated.exists():
            pytest.fail(f"{generated} is missing. Run: make schema")

        source = generated.read_text(encoding="utf-8")
        committed = json.loads(OPENAPI_PATH.read_text(encoding="utf-8"))

        missing = [path for path in committed["paths"] if f'"{path}"' not in source]
        assert not missing, (
            f"Endpoints missing from the generated client: {missing}. Run: make schema"
        )


class TestContract:
    """Properties the generated client and its consumers depend on."""

    def test_every_route_is_versioned_or_a_health_probe(self, schema: dict[str, Any]) -> None:
        # Adding a version prefix later means either breaking existing clients
        # or maintaining unversioned aliases forever. Health probes are exempt:
        # their URLs live in a deployment manifest that should not change when
        # the API version does.
        unversioned = [
            path
            for path in schema["paths"]
            if not path.startswith("/v1/") and path not in {"/healthz", "/readyz"}
        ]

        assert unversioned == []

    def test_every_operation_has_a_summary(self, schema: dict[str, Any]) -> None:
        # The summary becomes the doc comment on the generated client method.
        # An endpoint without one produces a method a frontend developer has to
        # read Python to understand.
        missing = [
            f"{method.upper()} {path}"
            for path, operations in schema["paths"].items()
            for method, operation in operations.items()
            if "summary" not in operation
        ]

        assert missing == []

    def test_field_names_are_camel_case(self, schema: dict[str, Any]) -> None:
        # Python writes snake_case, the wire speaks camelCase, and the alias
        # generator converts once. A snake_case field reaching the schema means
        # a model escaped `ApiModel` — and the inconsistency is the kind someone
        # later "fixes" on one endpoint, breaking the contract.
        offenders = [
            f"{name}.{field}"
            for name, definition in schema["components"]["schemas"].items()
            for field in definition.get("properties", {})
            if "_" in field
        ]

        assert offenders == []

    def test_no_response_model_can_carry_a_secret(self, schema: dict[str, Any]) -> None:
        """Nothing named like a credential may appear in any response.

        A blunt check, deliberately. The precise version — auditing each model
        by hand — is the one that stops being run. This fires the moment someone
        adds `token` to `InvitationResponse` because it was convenient for
        testing, which is exactly how an invitation token ends up in the API
        logs of every intermediary.
        """
        forbidden = ("password", "token", "hash", "secret")

        def carries_text(spec: dict[str, Any]) -> bool:
            """Whether this field could hold a credential at all.

            A credential is a string. An integer named `totalTokens` is a count
            of model usage and cannot be one — narrowing by type keeps the check
            blunt where it matters instead of pushing somebody to rename an
            accurate domain word until the detector stops complaining.
            """
            types = {spec.get("type")} | {
                option.get("type") for option in spec.get("anyOf", []) if isinstance(option, dict)
            }
            return "string" in types or types == {None}

        offenders = [
            f"{name}.{field}"
            for name, definition in schema["components"]["schemas"].items()
            if not name.endswith("Request")
            for field, spec in definition.get("properties", {}).items()
            if any(word in field.lower() for word in forbidden) and carries_text(spec)
        ]

        assert offenders == []

    def test_errors_are_documented_as_problem_documents(self, schema: dict[str, Any]) -> None:
        # Every failure has one shape, so the generated client has one error
        # type to narrow on. Asserted through the app's own description because
        # FastAPI does not model a global error type.
        assert "problem+json" in schema["info"]["description"]
