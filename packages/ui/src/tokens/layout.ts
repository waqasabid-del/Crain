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
