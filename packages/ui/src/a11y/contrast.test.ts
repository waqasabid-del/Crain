import { describe, expect, it } from "vitest";

import { darkTheme, lightTheme } from "../tokens/color.js";
import { WCAG_AA, checkContrast, contrastRatio, parseHex, relativeLuminance } from "./contrast.js";

describe("parseHex", () => {
  it("parses six-digit hex", () => {
    expect(parseHex("#ffffff")).toEqual({ r: 255, g: 255, b: 255 });
    expect(parseHex("#0a0a0a")).toEqual({ r: 10, g: 10, b: 10 });
  });

  it("expands three-digit shorthand", () => {
    expect(parseHex("#fff")).toEqual({ r: 255, g: 255, b: 255 });
  });

  it("tolerates a missing hash and surrounding whitespace", () => {
    expect(parseHex("  ffffff ")).toEqual({ r: 255, g: 255, b: 255 });
  });

  it("throws rather than silently mis-parsing", () => {
    // A silently wrong colour produces a contrast result that looks valid.
    expect(() => parseHex("not-a-colour")).toThrow("Invalid hex colour");
    expect(() => parseHex("#12345")).toThrow("Invalid hex colour");
  });
});

describe("relativeLuminance", () => {
  it("matches the WCAG reference values at the extremes", () => {
    expect(relativeLuminance("#000000")).toBe(0);
    expect(relativeLuminance("#ffffff")).toBe(1);
  });
});

describe("contrastRatio", () => {
  it("returns 21:1 for black on white — the theoretical maximum", () => {
    expect(contrastRatio("#000000", "#ffffff")).toBeCloseTo(21, 5);
  });

  it("returns 1:1 for identical colours", () => {
    expect(contrastRatio("#737373", "#737373")).toBeCloseTo(1, 5);
  });

  it("is order-independent, per the WCAG definition", () => {
    const a = contrastRatio("#171717", "#fafafa");
    const b = contrastRatio("#fafafa", "#171717");
    expect(a).toBeCloseTo(b, 10);
  });
});

/**
 * The tests that matter.
 *
 * These assert that every colour combination the design system actually uses
 * meets WCAG 2.1 AA. A token change that breaks accessibility fails CI here,
 * which is the difference between accessibility being a requirement and being
 * an intention.
 */
describe.each([
  ["light", lightTheme],
  ["dark", darkTheme],
])("%s theme contrast", (themeName, theme) => {
  const surfaces = [
    ["default", theme.bg.default],
    ["subtle", theme.bg.subtle],
    ["muted", theme.bg.muted],
  ] as const;

  describe.each(surfaces)("on bg.%s", (surfaceName, background) => {
    it("fg.default passes AA for normal text", () => {
      const result = checkContrast(theme.fg.default, background);
      expect(
        result.passes,
        `${themeName}/fg.default on bg.${surfaceName} was ${String(result.ratio)}:1, needs ${String(result.required)}:1`,
      ).toBe(true);
    });

    it("fg.muted passes AA for normal text", () => {
      const result = checkContrast(theme.fg.muted, background);
      expect(
        result.passes,
        `${themeName}/fg.muted on bg.${surfaceName} was ${String(result.ratio)}:1, needs ${String(result.required)}:1`,
      ).toBe(true);
    });

    it("fg.subtle passes AA for large text at minimum", () => {
      // fg.subtle is reserved for large text and de-emphasised metadata.
      const result = checkContrast(theme.fg.subtle, background, "largeText");
      expect(
        result.passes,
        `${themeName}/fg.subtle on bg.${surfaceName} was ${String(result.ratio)}:1, needs ${String(result.required)}:1`,
      ).toBe(true);
    });
  });

  it("inverse text passes AA on the inverse surface", () => {
    const result = checkContrast(theme.fg.inverse, theme.bg.inverse);
    expect(result.passes, `inverse pair was ${String(result.ratio)}:1`).toBe(true);
  });

  it("focus ring meets the non-text requirement against the default surface", () => {
    // WCAG 1.4.11 — a focus indicator nobody can see is not a focus indicator.
    const result = checkContrast(theme.border.focus, theme.bg.default, "nonText");
    expect(result.passes, `focus ring was ${String(result.ratio)}:1`).toBe(true);
  });

  it("accent text passes AA on the default surface", () => {
    const result = checkContrast(theme.accent.default, theme.bg.default);
    expect(result.passes, `accent was ${String(result.ratio)}:1`).toBe(true);
  });

  it("text on the accent surface passes AA", () => {
    const result = checkContrast(theme.fg.onAccent, theme.accent.default);
    expect(result.passes, `fg.onAccent was ${String(result.ratio)}:1`).toBe(true);
  });

  it("interactive borders meet the non-text requirement", () => {
    // WCAG 1.4.11 — the outline of an input carries essential information about
    // where a control is. It must be perceivable.
    const result = checkContrast(theme.border.interactive, theme.bg.default, "nonText");
    expect(
      result.passes,
      `border.interactive was ${String(result.ratio)}:1, needs ${String(result.required)}:1`,
    ).toBe(true);
  });

  it("decorative borders are deliberately below the non-text threshold", () => {
    // Asserted rather than assumed. If someone later darkens border.default to
    // "fix accessibility", this test explains why that is the wrong change and
    // points them at border.interactive instead.
    const result = checkContrast(theme.border.default, theme.bg.default, "nonText");
    expect(
      result.passes,
      "border.default should stay decorative — use border.interactive for controls",
    ).toBe(false);
  });
});

describe("WCAG thresholds", () => {
  it("uses the AA values defined by the specification", () => {
    expect(WCAG_AA.normalText).toBe(4.5);
    expect(WCAG_AA.largeText).toBe(3);
    expect(WCAG_AA.nonText).toBe(3);
  });
});
