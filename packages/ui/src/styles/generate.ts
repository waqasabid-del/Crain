/** Generates `theme.css` from the TypeScript tokens, so the contrast tests read
 * the values the interface renders; `generate.test.ts` fails on drift. Committed
 * rather than built on demand — it is what a developer opens to debug a style.
 * @see md/05-ux-design-privacy.md §A.6 */

import { type Theme, accent, darkTheme, lightTheme } from "../tokens/color.js";
import {
  borderWidth,
  duration,
  easing,
  focusRing,
  minTargetSize,
  radius,
  shadow,
  space,
} from "../tokens/layout.js";
import {
  fontFamily,
  fontSize,
  fontWeight,
  lineHeight,
  proseMaxWidth,
} from "../tokens/typography.js";

function colorVariableName(group: string, role: string): string {
  const kebab = role.replace(/[A-Z]/g, (letter) => `-${letter.toLowerCase()}`);
  return `--${group}-${kebab}`;
}

function colorDeclarations(theme: Theme, indent: string): string {
  const groups = Object.entries(theme) as [string, Record<string, string>][];
  return groups
    .map(([group, roles]) =>
      Object.entries(roles)
        .map(([role, value]) => `${indent}${colorVariableName(group, role)}: ${value};`)
        .join("\n"),
    )
    .join("\n\n");
}

function indentBlock(text: string, indent: string): string {
  return text
    .split("\n")
    .map((line) => (line.length > 0 ? indent + line : line))
    .join("\n");
}

const HEADER = `/**
 * Design tokens as CSS custom properties.
 *
 * GENERATED FILE — do not edit.
 *
 * Produced from src/tokens/*.ts by src/styles/generate.ts, and checked for
 * drift by src/styles/generate.test.ts. Editing this file directly will fail
 * that test; change the TypeScript token and regenerate instead.
 *
 * The TypeScript tokens are the single source of truth precisely because the
 * contrast tests read them: a hand-maintained copy could pass every
 * accessibility assertion while shipping a colour that fails WCAG.
 *
 * Theme switching is a single attribute on the root element, so it costs one
 * repaint rather than a re-render.
 */`;

/** Tokens that carry no theme — identical in light and dark. */
function structuralTokens(): string {
  const lines: string[] = [];

  lines.push("  /* Typography */");
  lines.push(`  --font-sans: ${fontFamily.sans};`);
  lines.push(`  --font-mono: ${fontFamily.mono};`);
  lines.push("");
  for (const [name, value] of Object.entries(fontSize)) {
    lines.push(`  --text-${name}: ${value};`);
  }
  lines.push("");
  for (const [name, value] of Object.entries(fontWeight)) {
    lines.push(`  --weight-${name}: ${String(value)};`);
  }
  lines.push("");
  for (const [name, value] of Object.entries(lineHeight)) {
    lines.push(`  --leading-${name}: ${String(value)};`);
  }
  lines.push("");
  lines.push(`  --prose-max-width: ${proseMaxWidth};`);

  lines.push("");
  lines.push("  /* Spacing — 4px base */");
  for (const [step, value] of Object.entries(space)) {
    lines.push(`  --space-${step}: ${value};`);
  }

  lines.push("");
  lines.push("  /* Shape */");
  for (const [name, value] of Object.entries(radius)) {
    lines.push(`  --radius-${name}: ${value};`);
  }
  lines.push("");
  for (const [name, value] of Object.entries(borderWidth)) {
    lines.push(`  --border-${name}: ${value};`);
  }
  lines.push("");
  for (const [name, value] of Object.entries(shadow)) {
    lines.push(`  --shadow-${name}: ${value};`);
  }

  lines.push("");
  lines.push("  /* Interaction */");
  lines.push(`  --min-target: ${minTargetSize};`);
  lines.push(`  --focus-width: ${focusRing.width};`);
  lines.push(`  --focus-offset: ${focusRing.offset};`);
  lines.push(`  --focus-style: ${focusRing.style};`);
  lines.push("");
  for (const [name, value] of Object.entries(duration)) {
    lines.push(`  --duration-${name}: ${value};`);
  }
  lines.push("");
  for (const [name, value] of Object.entries(easing)) {
    lines.push(`  --easing-${name}: ${value};`);
  }

  return lines.join("\n");
}

const BASE = `/* ------------------------------------------------------------------------- */
/* Base                                                                       */
/* ------------------------------------------------------------------------- */

*,
*::before,
*::after {
  box-sizing: border-box;
}

body {
  margin: 0;
  background: var(--bg-default);
  color: var(--fg-default);
  font-family: var(--font-sans);
  font-size: var(--text-base);
  line-height: var(--leading-normal);
  -webkit-font-smoothing: antialiased;
}

/**
 * A single, consistent focus indicator.
 *
 * \`:focus-visible\` rather than \`:focus\` so a mouse click does not leave a ring
 * behind, while keyboard navigation always shows one. Removing focus outlines
 * without replacement is the most common WCAG 2.4.7 failure in production
 * interfaces.
 */
:focus-visible {
  outline: var(--focus-width) var(--focus-style) var(--border-focus);
  outline-offset: var(--focus-offset);
}

/**
 * WCAG 2.3.3 — honour a user's reduced-motion preference.
 *
 * Animation is not decoration for people with vestibular disorders; it can
 * cause genuine physical discomfort.
 */
@media (prefers-reduced-motion: reduce) {
  *,
  *::before,
  *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
    scroll-behavior: auto !important;
  }
}`;

export function generateThemeCss(): string {
  const dark = colorDeclarations(darkTheme, "  ");

  return `${HEADER}

:root {
${structuralTokens()}
}

/* Light theme — the default */
:root,
[data-theme="light"] {
  color-scheme: light;

${colorDeclarations(lightTheme, "  ")}
}

[data-theme="dark"] {
  color-scheme: dark;

${dark}
}

/* Respect the OS preference when no explicit theme is set.

   Scoped with :not([data-theme="light"]) so an explicit light choice still wins
   on a device set to dark — otherwise the theme toggle would appear broken in
   one direction only. */
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    color-scheme: dark;

${indentBlock(dark, "  ")}
  }
}

${BASE}
`;
}

/** Re-exported so the accent ramp is reachable from generated documentation. */
export const generatedAccent = accent;
