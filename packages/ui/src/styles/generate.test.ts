import { readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import { type Theme, darkTheme, lightTheme } from "../tokens/color.js";
import { generateThemeCss } from "./generate.js";

// Resolved from the package root rather than `import.meta.url`: these tests run
// under the jsdom environment, where `import.meta.url` is an http URL and
// `fileURLToPath` rejects it. Vitest sets the working directory to the package
// root, which is stable across the runner and the CLI.
const THEME_CSS = resolve(process.cwd(), "src/styles/theme.css");

/**
 * Run with UPDATE_THEME_CSS=1 to rewrite the stylesheet after a token change:
 *
 *   UPDATE_THEME_CSS=1 pnpm --filter @cairn/ui test
 */
const SHOULD_UPDATE = process.env.UPDATE_THEME_CSS === "1";

describe("theme.css", () => {
  it("matches the tokens it is generated from", () => {
    const expected = generateThemeCss();

    if (SHOULD_UPDATE) {
      writeFileSync(THEME_CSS, expected, "utf8");
    }

    // The point of this assertion. The contrast tests read the TypeScript
    // tokens; components render the CSS. While the two were maintained by hand
    // they could disagree, and the disagreement would be invisible — every
    // accessibility test passing against colours that nobody ships.
    expect(readFileSync(THEME_CSS, "utf8")).toBe(expected);
  });

  it("emits a custom property for every semantic colour role", () => {
    const css = generateThemeCss();

    // Catches a token added to color.ts but never reaching the stylesheet,
    // which would leave components silently falling back to an inherited value.
    for (const [group, roles] of Object.entries(lightTheme)) {
      for (const role of Object.keys(roles)) {
        const kebab = role.replace(/[A-Z]/g, (letter) => `-${letter.toLowerCase()}`);
        expect(css).toContain(`--${group}-${kebab}:`);
      }
    }
  });

  it("defines the same roles in both themes", () => {
    // A role present in one theme and missing from the other produces an
    // interface that is correct in light mode and broken in dark, which is
    // exactly the kind of defect that reaches production — most developers work
    // in one theme.
    const roles = (theme: Theme): string[] =>
      (Object.entries(theme) as [string, Record<string, string>][])
        .flatMap(([group, values]) => Object.keys(values).map((role) => `${group}.${role}`))
        .sort();

    expect(roles(darkTheme)).toEqual(roles(lightTheme));
  });

  it("never inlines a raw colour outside the theme blocks", () => {
    // A hex literal in the base rules would be a colour that no theme can
    // override — invisible in light mode, unreadable in dark.
    const base = generateThemeCss().split("/* Base")[1] ?? "";

    expect(base).not.toMatch(/#[0-9a-f]{3,8}\b/i);
  });
});
