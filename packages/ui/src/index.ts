/**
 * CAIRN design system.
 *
 * Black and white, minimalist, WCAG 2.1 AA — verified by tests rather than
 * asserted (see src/a11y/contrast.test.ts).
 *
 * Consumers import the stylesheet once at the app root:
 *   import "@cairn/ui/styles";
 */

// Tokens
export * from "./tokens/color.js";
export * from "./tokens/typography.js";
export * from "./tokens/layout.js";

// Accessibility utilities
export * from "./a11y/contrast.js";
export { visuallyHidden } from "./styles/utilities.js";

// Components
export { Button } from "./components/Button.js";
export type { ButtonProps, ButtonSize, ButtonVariant } from "./components/Button.js";
export { CertaintyBadge } from "./components/CertaintyBadge.js";
export type { CertaintyBadgeProps } from "./components/CertaintyBadge.js";
