/**
 * Spacing, radii, borders, shadows and motion.
 *
 * All spacing derives from a 4px base. A single rhythm applied consistently is
 * what makes an interface feel considered; arbitrary values are what make it
 * feel improvised.
 */

const BASE_UNIT_PX = 4;

/** Spacing scale in rem, derived from a 4px base at a 16px root. */
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

/** Convert a spacing step to pixels. Used by the token tests. */
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

/**
 * Shadows are deliberately minimal.
 *
 * In a monochrome interface heavy shadows read as noise. Elevation is mostly
 * communicated through borders and background steps instead.
 */
export const shadow = {
  none: "none",
  sm: "0 1px 2px 0 rgb(0 0 0 / 0.05)",
  md: "0 4px 8px -2px rgb(0 0 0 / 0.08)",
} as const;

/**
 * Minimum interactive target size.
 *
 * WCAG 2.2 (2.5.8 Target Size, Minimum) sets 24×24 CSS px. This uses 44px,
 * the stricter mobile guideline, because CAIRN's most important repeated
 * action — correcting your own record — must be effortless on any device
 * (md/05 §A.3). A correction that is fiddly is a correction that never happens,
 * and an error that silently persists.
 */
export const minTargetSize = "44px";

/**
 * Focus ring.
 *
 * A monochrome interface tends to fail WCAG 2.4.7 (Focus Visible), because the
 * usual approach of tinting a background does not read against greyscale. The
 * ring is therefore an explicit, high-contrast outline with an offset so it
 * stays visible against both light and dark surfaces.
 */
export const focusRing = {
  width: "2px",
  offset: "2px",
  style: "solid",
} as const;

/**
 * Motion.
 *
 * Short and unobtrusive. Every duration here is well under the 5 second
 * threshold at which WCAG 2.2.2 requires a pause control, and all motion must
 * be disabled under `prefers-reduced-motion`.
 */
export const duration = {
  instant: "0ms",
  fast: "120ms",
  normal: "200ms",
} as const;

export const easing = {
  standard: "cubic-bezier(0.2, 0, 0, 1)",
  decelerate: "cubic-bezier(0, 0, 0, 1)",
} as const;
