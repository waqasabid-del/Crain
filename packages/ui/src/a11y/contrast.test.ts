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

    it("fg.subtle passes AA for normal text", () => {
      /**
       * Asserted at 4.5:1, not 3:1.
       *
       * The token was documented as "large text and de-emphasised metadata" and
       * tested at the large-text bar, while every one of its callers used it at
       * text-xs or text-sm — timestamps, captions, disabled button labels. The
       * test agreed with the comment and neither agreed with the interface, so
       * the value sat below AA for the type it actually rendered.
       */
      const result = checkContrast(theme.fg.subtle, background);
      expect(
        result.passes,
        `${themeName}/fg.subtle on bg.${surfaceName} was ${String(result.ratio)}:1, needs ${String(result.required)}:1`,
      ).toBe(true);
    });

    it("fg.subtle stays quieter than fg.muted", () => {
      // The point of the token. Raising it to clear 4.5:1 must not raise it to
      // where the hierarchy it exists to express disappears.
      const subtle = contrastRatio(theme.fg.subtle, background);
      const muted = contrastRatio(theme.fg.muted, background);
      expect(subtle).toBeLessThan(muted);
    });

    it("border.strong meets the non-text requirement", () => {
      /**
       * WCAG 1.4.11. In CertaintyBadge this border is the entire difference
       * between a verified claim and an observed one — colour is not available
       * to carry it and the weight difference is one step. A border nobody can
       * see presents an inference with the authority of a fact.
       */
      const result = checkContrast(theme.border.strong, background, "nonText");
      expect(
        result.passes,
        `${themeName}/border.strong on bg.${surfaceName} was ${String(result.ratio)}:1, needs ${String(result.required)}:1`,
      ).toBe(true);
    });

    it("the focus ring meets the non-text requirement", () => {
      // Testing only bg.default was not enough: nav links, setting rows and
      // list rows take bg.muted when hovered or current, which is exactly when
      // they are also being focused.
      const result = checkContrast(theme.border.focus, background, "nonText");
      expect(
        result.passes,
        `${themeName}/focus ring on bg.${surfaceName} was ${String(result.ratio)}:1, needs ${String(result.required)}:1`,
      ).toBe(true);
    });
  });

  it("inverse text passes AA on the inverse surface", () => {
    const result = checkContrast(theme.fg.inverse, theme.bg.inverse);
    expect(result.passes, `inverse pair was ${String(result.ratio)}:1`).toBe(true);
  });

  it("focus ring meets the non-text requirement on the primary button", () => {
    /**
     * The surface the ring is most likely to fail against, and the one that was
     * not being tested.
     *
     * `Button.module.css` fills the primary variant with `fg.default` — near
     * black in light mode, near white in dark. The ring has to clear 3:1
     * against that as well as against the page, which pins the accent into a
     * narrow band: the previous light accent cleared the page at 6.7:1 and the
     * button at 2.95:1.
     */
    const result = checkContrast(theme.border.focus, theme.fg.default, "nonText");
    expect(
      result.passes,
      `${themeName}/focus ring on the primary button was ${String(result.ratio)}:1, needs ${String(result.required)}:1`,
    ).toBe(true);
  });

  it("disabled button text passes AA", () => {
    // Button.module.css puts fg.subtle on bg.muted for the disabled state.
    // WCAG exempts disabled controls; CAIRN does not, because a disabled button
    // still has to say what it would do once it is enabled.
    const result = checkContrast(theme.fg.subtle, theme.bg.muted);
    expect(
      result.passes,
      `${themeName}/disabled button label was ${String(result.ratio)}:1, needs ${String(result.required)}:1`,
    ).toBe(true);
  });

  it("the disabled secondary button keeps a perceivable outline", () => {
    // Its border drops from border.interactive to border.strong when disabled,
    // which is still a control boundary and still carries 1.4.11.
    const result = checkContrast(theme.border.strong, theme.bg.default, "nonText");
    expect(result.passes, `border.strong was ${String(result.ratio)}:1`).toBe(true);
  });

  it("border.subtle is quieter than border.default", () => {
    // The role only exists to sit below `default`. If it ever stopped doing so
    // the seven separators using it would be louder than the boxes they divide.
    const subtle = contrastRatio(theme.border.subtle, theme.bg.default);
    const dfault = contrastRatio(theme.border.default, theme.bg.default);
    expect(subtle).toBeLessThan(dfault);
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
