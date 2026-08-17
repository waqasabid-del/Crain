import { describe, expect, it } from "vitest";

import { certaintyTreatment, lightTheme } from "./color.js";
import { breakpoint, breakpointPx, mediaQuery, space, spaceToPx } from "./layout.js";

/**
 * Token invariants.
 *
 * Closes audit finding O13: `spaceToPx` had no caller, and `certaintyTreatment`
 * specified an opacity the component never applied while three documents told
 * readers opacity was how tiers differ.
 *
 * Both are the same shape of defect — a token asserting something nothing
 * enforces — so both get an assertion rather than a comment.
 */

describe("the spacing rhythm", () => {
  it("is a whole number of 4px steps", () => {
    // A step added with an off-rhythm rem value looks right in isolation and
    // breaks the vertical alignment of everything beside it.
    for (const step of Object.keys(space)) {
      const numeric = Number(step) as keyof typeof space;
      expect(spaceToPx(numeric) % 4).toBe(0);
    }
  });

  it("matches the rem values it publishes", () => {
    // The two must agree: `spaceToPx` is what tests reason about, `space` is
    // what ships. A divergence would make every rhythm assertion vacuous.
    expect(spaceToPx(4)).toBe(16);
    expect(space[4]).toBe("1rem");
    expect(spaceToPx(2)).toBe(8);
    expect(space[2]).toBe("0.5rem");
  });
});

describe("breakpoints", () => {
  /**
   * Before these existed, every breakpoint was a literal in a per-file CSS
   * module, written in two different syntaxes — `width <= 60rem` in one place
   * and `max-width: 40rem` in another — so no two files agreed on where a
   * layout changed and nothing could tell you which value was intended.
   */

  it("covers the widths the product is verified at", () => {
    expect(breakpointPx.narrow).toBe(320);
    expect(breakpointPx.phone).toBe(375);
    expect(breakpointPx.tablet).toBe(768);
    expect(breakpointPx.desktop).toBe(1024);
  });

  it("ascends", () => {
    // A scale out of order would make `min-width` queries mask one another, and
    // the symptom — one layout never appearing — looks like a CSS bug.
    const values = Object.values(breakpointPx);
    expect([...values].sort((a, b) => a - b)).toEqual(values);
  });

  it("publishes rem values that match the px values", () => {
    // The rem strings are what stylesheets use; a mismatch would move a
    // breakpoint without any file recording that it had moved.
    for (const [name, px] of Object.entries(breakpointPx)) {
      const rem = breakpoint[name as keyof typeof breakpointPx];
      expect(Number.parseFloat(rem) * 16, `${name} disagrees with its px value`).toBe(px);
      expect(rem.endsWith("rem")).toBe(true);
    }
  });

  it("builds media queries from those same values", () => {
    // `matchMedia(mediaQuery.tablet)` in a component and `@media` in a
    // stylesheet must mean the same width, or a JS-driven layout and a
    // CSS-driven one disagree in a band a few pixels wide.
    expect(mediaQuery.tablet).toBe("(min-width: 48rem)");
    expect(mediaQuery.desktop).toBe(`(min-width: ${breakpoint.desktop})`);
  });
});

describe("certainty treatment", () => {
  it("carries no opacity", () => {
    /**
     * The defect this closes.
     *
     * The tokens specified `opacity: 0.75` for the suggested tier. Dimming text
     * to 75% multiplies its contrast against the background by roughly the same
     * factor, so `fg.muted` at 0.75 lands near 3:1 — below the 4.5:1 the design
     * system asserts everywhere else, and on the tier a person is most being
     * asked to check.
     *
     * The component never applied it, so nothing shipped broken. But three
     * documents described opacity as the mechanism, which is how it would have
     * been "restored" by someone making the code match the docs.
     */
    for (const treatment of Object.values(certaintyTreatment)) {
      expect(treatment).not.toHaveProperty("opacity");
    }
  });

  it("distinguishes tiers without colour", () => {
    // Traffic-light styling would be the only colour in a monochrome system and
    // reads as a judgement about the person rather than the evidence.
    const tiers = Object.values(certaintyTreatment);
    const borderStyles = new Set(tiers.map((t) => t.borderStyle));
    const weights = new Set(tiers.map((t) => t.weight));

    expect(borderStyles.size).toBeGreaterThan(1);
    expect(weights.size).toBeGreaterThan(1);
  });

  it("names tokens that exist", () => {
    // A treatment referencing `fg.faint` would be a silent no-op: the component
    // resolves the token at render and falls back to inherited colour.
    const paths = new Set<string>();
    for (const [group, roles] of Object.entries(lightTheme) as [string, Record<string, string>][]) {
      for (const role of Object.keys(roles)) paths.add(`${group}.${role}`);
    }

    for (const treatment of Object.values(certaintyTreatment)) {
      expect(paths).toContain(treatment.fgToken);
      expect(paths).toContain(treatment.borderToken);
    }
  });
});
