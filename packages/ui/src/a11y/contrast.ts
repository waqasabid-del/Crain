/** WCAG contrast calculation. AA is a locked requirement (md/05 §A.6), so this
 * exists to assert contrast in the test suite rather than in a design tool.
 * https://www.w3.org/TR/WCAG21/#dfn-contrast-ratio */

export interface Rgb {
  r: number;
  g: number;
  b: number;
}

/** WCAG 2.1 minimum contrast ratios. */
export const WCAG_AA = {
  normalText: 4.5, // 1.4.3 — body text below 18pt (or 14pt bold)
  largeText: 3, // 1.4.3 — text at 18pt+ (or 14pt+ bold)
  nonText: 3, // 1.4.11 — UI components and graphical objects
} as const;

/** AAA, tracked but not required. */
export const WCAG_AAA = {
  normalText: 7,
  largeText: 4.5,
} as const;

/** @throws If not a 3- or 6-digit hex colour; a mis-parsed one would give a
 *   contrast result that looks valid and is not. */
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

function linearizeChannel(channel8Bit: number): number {
  const c = channel8Bit / 255;
  return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
}

export function relativeLuminance(color: Rgb | string): number {
  const { r, g, b } = typeof color === "string" ? parseHex(color) : color;
  return 0.2126 * linearizeChannel(r) + 0.7152 * linearizeChannel(g) + 0.0722 * linearizeChannel(b);
}

/** 1 (identical) to 21 (black on white). Order-independent, per WCAG. */
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
