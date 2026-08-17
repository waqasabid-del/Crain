/** Spacing, radii, borders, shadows and motion, all on a 4px base. */

const BASE_UNIT_PX = 4;

export const space = {
  0: "0",
  1: "0.25rem",
  2: "0.5rem",
  3: "0.75rem",
  4: "1rem",
  5: "1.25rem",
  6: "1.5rem",
  8: "2rem",
  10: "2.5rem",
  12: "3rem",
  16: "4rem",
  20: "5rem",
  24: "6rem",
} as const;

export type SpaceStep = keyof typeof space;

/** Exists so the 4px rhythm can be asserted rather than assumed. */
export function spaceToPx(step: SpaceStep): number {
  return step * BASE_UNIT_PX;
}

export const radius = {
  none: "0",
  sm: "0.25rem",
  md: "0.375rem",
  lg: "0.5rem",
  full: "9999px",
} as const;

export const borderWidth = {
  thin: "1px",
  thick: "2px",
} as const;

/** Minimal by design: in a monochrome interface heavy shadows read as noise. */
export const shadow = {
  none: "none",
  sm: "0 1px 2px 0 rgb(0 0 0 / 0.05)",
  md: "0 4px 8px -2px rgb(0 0 0 / 0.08)",
} as const;

/** 44px, not the 24px of WCAG 2.5.8: correcting your own record must be
 * effortless on any device (md/05 §A.3). */
export const minTargetSize = "44px";

/** The WCAG 2.5.8 floor, for controls that sit inline inside a line of prose —
 * a badge in a sentence cannot be 44px tall without breaking the leading of the
 * paragraph around it. Anything standalone uses `minTargetSize`. */
export const minTargetSizeInline = "24px";

/**
 * Layout breakpoints.
 *
 * The px values are the source of truth. CSS custom properties are resolved
 * against an element, and a media query is evaluated before any element exists,
 * so `@media (width <= var(--bp-tablet))` can never work — no polyfill changes
 * that. Media queries therefore repeat the literal, and this scale exists so
 * there is one place to look up which literal is correct and one value for
 * JavaScript (`matchMedia`) to share with the stylesheet.
 *
 * The steps are the widths the product is verified at, not a generic device
 * ladder: `narrow` is the smallest supported viewport, `phone` the common one
 * below it, and layouts change at `tablet` and `desktop`.
 */
export const breakpointPx = {
  narrow: 320,
  phone: 375,
  tablet: 768,
  desktop: 1024,
} as const;

export type Breakpoint = keyof typeof breakpointPx;

/** The same steps in rem, for the `width <= 48rem` style of query: rem respects
 * the browser font-size setting, px does not. */
export const breakpoint: Readonly<Record<Breakpoint, string>> = {
  narrow: "20rem",
  phone: "23.4375rem",
  tablet: "48rem",
  desktop: "64rem",
};

/** Ready-made query strings, so `matchMedia` in a component and the stylesheet
 * cannot drift apart. Mobile-first: each matches at or above its step. */
export const mediaQuery: Readonly<Record<Breakpoint, string>> = {
  narrow: `(min-width: ${breakpoint.narrow})`,
  phone: `(min-width: ${breakpoint.phone})`,
  tablet: `(min-width: ${breakpoint.tablet})`,
  desktop: `(min-width: ${breakpoint.desktop})`,
};

/** An explicit high-contrast outline with an offset: tinting a background does
 * not read against greyscale, so a monochrome interface fails WCAG 2.4.7. */
export const focusRing = {
  width: "2px",
  offset: "2px",
  style: "solid",
} as const;

/** All well under the 5s at which WCAG 2.2.2 requires a pause control, and all
 * motion must be disabled under `prefers-reduced-motion`. */
export const duration = {
  instant: "0ms",
  fast: "120ms",
  normal: "200ms",
} as const;

export const easing = {
  standard: "cubic-bezier(0.2, 0, 0, 1)",
  decelerate: "cubic-bezier(0, 0, 0, 1)",
} as const;
