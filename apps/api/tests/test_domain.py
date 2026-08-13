"""Tests for the shared domain vocabulary.

These do more than exercise enums: they encode product constraints that must
not drift. If someone later adds a numeric confidence field or a fifth tenant
role, these tests fail and force the conversation.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from cairn_api.domain import (
    ActivityCategory,
    Certainty,
    TenantRole,
    as_tenant_id,
)

# Path to the TypeScript definitions this module mirrors.
TS_TYPES = Path(__file__).parents[3] / "packages" / "types" / "src" / "index.ts"


def _extract_ts_const(name: str) -> list[str]:
    """Pull a `const X = [...] as const` array out of the TypeScript source."""
    source = TS_TYPES.read_text(encoding="utf-8")
    match = re.search(rf"const {name} = \[(.*?)\] as const", source, re.DOTALL)
    if match is None:
        pytest.fail(f"Could not find `{name}` in {TS_TYPES}")
    return [json.loads(item.strip()) for item in match.group(1).split(",") if item.strip()]


class TestCertainty:
    def test_has_exactly_three_tiers(self) -> None:
        assert len(Certainty) == 3

    def test_is_categorical_never_numeric(self) -> None:
        """Guards md/05 §A.2.1 — certainty must never become a percentage."""
        for tier in Certainty:
            with pytest.raises(ValueError, match="could not convert"):
                float(tier.value)

    def test_matches_typescript_definition(self) -> None:
        assert [t.value for t in Certainty] == _extract_ts_const("CERTAINTY_TIERS")


class TestTenantRole:
    def test_limited_to_four_roles(self) -> None:
        """Guards against role explosion — md/15 §2.2."""
        assert len(TenantRole) == 4

    def test_matches_typescript_definition(self) -> None:
        assert [r.value for r in TenantRole] == _extract_ts_const("TENANT_ROLES")


class TestActivityCategory:
    def test_covers_the_four_capture_pillars(self) -> None:
        assert len(ActivityCategory) == 4

    def test_matches_typescript_definition(self) -> None:
        assert [c.value for c in ActivityCategory] == _extract_ts_const("ACTIVITY_CATEGORIES")


class TestAsTenantId:
    def test_accepts_a_valid_identifier(self) -> None:
        assert as_tenant_id("tnt_abc123") == "tnt_abc123"

    @pytest.mark.parametrize("value", ["", "   ", "\t\n"])
    def test_rejects_empty_or_blank(self, value: str) -> None:
        """Fail loudly — an empty tenant ID is the start of a cross-tenant read."""
        with pytest.raises(ValueError, match="Tenant ID cannot be empty"):
            as_tenant_id(value)
