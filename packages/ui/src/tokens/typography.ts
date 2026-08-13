/**
 * Typography tokens.
 *
 * CAIRN's primary output is prose — a daily narrative someone reads rather than
 * scans (md/05 §A.1). That makes typography the most load-bearing part of this
 * design system, not decoration on top of it.
 *
 * The scale is deliberately small. Fewer sizes used consistently reads as more
 * considered than many sizes used approximately.
 */

export const fontFamily = {
  /** System stack — no webfont, so text renders instantly with no layout shift. */
  sans: [
    "-apple-system",
    "BlinkMacSystemFont",
    "Segoe UI",
    "Roboto",
    "Helvetica Neue",
    "Arial",
    "sans-serif",
  ].join(", "),
  mono: ["ui-monospace", "SFMono-Regular", "Menlo", "Consolas", "monospace"].join(", "),
} as const;

/**
 * Size scale in rem, so text respects the user's browser font-size setting.
 *
 * Using px here would silently break zoom for anyone who has increased their
 * default font size — a WCAG 1.4.4 (Resize Text) failure that is invisible to
 * anyone testing at default settings.
 */
export const fontSize = {
  xs: "0.75rem",
  sm: "0.875rem",
  base: "1rem",
  lg: "1.125rem",
  xl: "1.25rem",
  "2xl": "1.5rem",
  "3xl": "1.875rem",
} as const;

export const fontWeight = {
  normal: 400,
  medium: 500,
  semibold: 600,
} as const;

/**
 * Line heights. Prose gets `relaxed`; UI labels get `tight`.
 *
 * WCAG 1.4.12 (Text Spacing) requires content to survive a line height of 1.5×,
 * so body text starts there rather than being tightened for density.
 */
export const lineHeight = {
  tight: 1.25,
  normal: 1.5,
  relaxed: 1.65,
} as const;

export const letterSpacing = {
  tight: "-0.01em",
  normal: "0",
} as const;

/**
 * Composite text styles — the intended API.
 *
 * Components reference `textStyle.body`, not individual size and weight tokens,
 * so typography stays consistent without each component re-deciding it.
 */
export const textStyle = {
  /** Long-form narrative — the Founder Brief, summaries, generated documentation. */
  prose: {
    fontSize: fontSize.base,
    lineHeight: lineHeight.relaxed,
    fontWeight: fontWeight.normal,
    letterSpacing: letterSpacing.normal,
  },
  body: {
    fontSize: fontSize.base,
    lineHeight: lineHeight.normal,
    fontWeight: fontWeight.normal,
    letterSpacing: letterSpacing.normal,
  },
  bodySmall: {
    fontSize: fontSize.sm,
    lineHeight: lineHeight.normal,
    fontWeight: fontWeight.normal,
    letterSpacing: letterSpacing.normal,
  },
  label: {
    fontSize: fontSize.sm,
    lineHeight: lineHeight.tight,
    fontWeight: fontWeight.medium,
    letterSpacing: letterSpacing.normal,
  },
  caption: {
    fontSize: fontSize.xs,
    lineHeight: lineHeight.normal,
    fontWeight: fontWeight.normal,
    letterSpacing: letterSpacing.normal,
  },
  heading: {
    fontSize: fontSize["2xl"],
    lineHeight: lineHeight.tight,
    fontWeight: fontWeight.semibold,
    letterSpacing: letterSpacing.tight,
  },
  subheading: {
    fontSize: fontSize.lg,
    lineHeight: lineHeight.tight,
    fontWeight: fontWeight.medium,
    letterSpacing: letterSpacing.normal,
  },
} as const;

export type TextStyleName = keyof typeof textStyle;

/**
 * Maximum line length for prose, in characters.
 *
 * Typographic research puts comfortable reading at 45–75 characters per line.
 * Since the Founder Brief is read daily rather than skimmed, this is enforced
 * as a token rather than left to each layout.
 */
export const proseMaxWidth = "68ch";
