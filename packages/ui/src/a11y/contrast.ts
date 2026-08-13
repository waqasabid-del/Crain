/**
 * WCAG contrast calculation.
 *
 * WCAG 2.1 AA is a locked requirement, not an aspiration (md/05 §A.6) — the
 * European Accessibility Act has been in force since June 2025 and applies to
 * any company serving EU customers, and US ADA web accessibility litigation is
 * common regardless.
 *
 * "We checked the colours once in a design tool" is not compliance. This module
 * exists so that contrast is asserted in the test suite, meaning a token change
 * that breaks accessibility fails CI rather than reaching a user.
 *
 * Implements the WCAG 2.x relative luminance and contrast ratio definitions:
 * https://www.w3.org/TR/WCAG21/#dfn-relative-luminance
 * https://www.w3.org/TR/WCAG21/#dfn-contrast-ratio
 */

export interface Rgb {
  r: number;
  g: number;
  b: number;
}

/** WCAG 2.1 minimum contrast ratios. */
export const WCAG_AA = {
  /** 1.4.3 — body text below 18pt (or 14pt bold). */
  normalText: 4.5,
  /** 1.4.3 — text at 18pt+ (or 14pt+ bold). */
  largeText: 3,
  /** 1.4.11 — UI components and graphical objects. */
  nonText: 3,
} as const;

/** WCAG 2.1 AAA, tracked but not required. */
export const WCAG_AAA = {
  normalText: 7,
  largeText: 4.5,
} as const;

/**
 * Parse a hex colour into RGB channels.
 *
 * @throws If the value is not a 3- or 6-digit hex colour. Failing loudly is
 *   deliberate: a silently mis-parsed colour would produce a contrast result
 *   that looks valid and is not.
 */
export function parseHex(hex: string): Rgb {
  const normalized = hex.trim().replace(/^#/, "");

  if (!/^([0-9a-f]{3}|[0-9a-f]{6})$/i.test(normalized)) {
    throw new Error(`Invalid hex colour: "${hex}"`);
  }

  const full =
    normalized.length === 3
      ? normalized
          .split("")
          .map((c) => c + c)
          .join("")
      : normalized;

  return {
    r: Number.parseInt(full.slice(0, 2), 16),
    g: Number.parseInt(full.slice(2, 4), 16),
    b: Number.parseInt(full.slice(4, 6), 16),
  };
}

/** Convert an 8-bit channel to its linear-light value, per WCAG. */
function linearizeChannel(channel8Bit: number): number {
  const c = channel8Bit / 255;
  return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
}

/** Relative luminance of a colour, 0 (black) to 1 (white). */
export function relativeLuminance(color: Rgb | string): number {
  const { r, g, b } = typeof color === "string" ? parseHex(color) : color;
  return 0.2126 * linearizeChannel(r) + 0.7152 * linearizeChannel(g) + 0.0722 * linearizeChannel(b);
}

/**
 * Contrast ratio between two colours, from 1 (identical) to 21 (black on white).
 *
 * Order-independent, matching the WCAG definition.
 */
export function contrastRatio(foreground: Rgb | string, background: Rgb | string): number {
  const l1 = relativeLuminance(foreground);
  const l2 = relativeLuminance(background);
  const lighter = Math.max(l1, l2);
  const darker = Math.min(l1, l2);
  return (lighter + 0.05) / (darker + 0.05);
}

export type ContrastRequirement = keyof typeof WCAG_AA;

export interface ContrastResult {
  ratio: number;
  required: number;
  passes: boolean;
}

/** Check a foreground/background pair against a WCAG AA requirement. */
export function checkContrast(
  foreground: string,
  background: string,
  requirement: ContrastRequirement = "normalText",
): ContrastResult {
  const ratio = contrastRatio(foreground, background);
  const required = WCAG_AA[requirement];
  return {
    ratio: Math.round(ratio * 100) / 100,
    required,
    passes: ratio >= required,
  };
}
