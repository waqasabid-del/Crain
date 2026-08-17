import { describe, expect, it } from "vitest";

import { visuallyHidden } from "./utilities.js";

describe("visuallyHidden", () => {
  it("resolves to a real class name", () => {
    // An empty string here would be silent: the label simply becomes visible,
    // which looks like a design mistake rather than a broken build.
    expect(visuallyHidden).not.toBe("");
    expect(visuallyHidden).toContain("visuallyHidden");
  });
});
