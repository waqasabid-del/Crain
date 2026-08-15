/** Typography tokens. CAIRN's primary output is prose read rather than scanned
 * (md/05 §A.1), and the scale is deliberately small. */

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

/** rem, not px, so text respects the browser font-size setting: px would fail
 * WCAG 1.4.4 invisibly to anyone testing at default settings. */
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

/** Body text starts at 1.5 because WCAG 1.4.12 requires content to survive it. */
export const lineHeight = {
  tight: 1.25,
  normal: 1.5,
  relaxed: 1.65,
} as const;

export const letterSpacing = {
  tight: "-0.01em",
  normal: "0",
} as const;

/** The intended API: components reference `textStyle.body`, not size and weight
 * tokens individually. */
export const textStyle = {
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

/** Comfortable reading is 45–75 characters per line; enforced as a token rather
 * than left to each layout. */
export const proseMaxWidth = "68ch";
