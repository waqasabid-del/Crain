import { describe, expect, it } from "vitest";

import { ACTIVITY_CATEGORIES, CERTAINTY_TIERS, TENANT_ROLES, asTenantId } from "./index.js";

describe("certainty tiers", () => {
  it("exposes exactly the three categorical tiers", () => {
    expect(CERTAINTY_TIERS).toEqual(["verified", "observed", "suggested"]);
  });

  it("contains no numeric confidence representation", () => {
    // Guards md/05 §A.2.1 — certainty is categorical, never a percentage.
    for (const tier of CERTAINTY_TIERS) {
      expect(Number.isNaN(Number(tier))).toBe(true);
    }
  });
});

describe("tenant roles", () => {
  it("is limited to four roles to prevent role explosion", () => {
    expect(TENANT_ROLES).toHaveLength(4);
    expect(TENANT_ROLES).toEqual(["owner", "admin", "member", "viewer"]);
  });
});

describe("activity categories", () => {
  it("covers the four capture pillars", () => {
    expect(ACTIVITY_CATEGORIES).toEqual(["code", "conversation", "meeting", "document"]);
  });
});

describe("asTenantId", () => {
  it("accepts a non-empty identifier", () => {
    expect(asTenantId("tnt_abc123")).toBe("tnt_abc123");
  });

  it.each(["", "   ", "\t\n"])("rejects %o rather than producing an unusable brand", (value) => {
    // Fail loudly — a silently empty tenant ID is the start of a cross-tenant
    // read. Whitespace is included because Python rejects it too, and a value
    // that is a bug in one language and valid in the other is worse than either.
    expect(() => asTenantId(value)).toThrow("Tenant ID cannot be empty");
  });
});
