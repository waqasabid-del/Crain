/** Colour tokens. The palette is black and white: no success/warning/danger
 * scale for anything describing a person's work, because colour would smuggle
 * judgement in. Status colour is for system state only.
 * @see md/05-ux-design-privacy.md §A.1, §A.4 */

/** True greys (equal R/G/B), named by lightness rather than role. */
export const neutral = {
  0: "#ffffff",
  50: "#fafafa",
  100: "#f5f5f5",
  200: "#e5e5e5",
  300: "#d4d4d4",
  400: "#a3a3a3",
  500: "#737373",
  600: "#525252",
  700: "#404040",
  800: "#262626",
  900: "#171717",
  950: "#0a0a0a",
  1000: "#000000",
} as const;

export type NeutralStep = keyof typeof neutral;

/** One accent, for focus rings only: keyboard focus must be unmistakable (WCAG
 * 2.4.7), which a purely monochrome interface tends to fail. */
export const accent = {
  light: "#1d4ed8",
  dark: "#60a5fa",
} as const;

/** Roles, not colours: components reference `fg.default`, never `neutral[900]`. */
export const lightTheme = {
  bg: {
    default: neutral[0],
    subtle: neutral[50],
    muted: neutral[100],
    inverse: neutral[950],
  },
  fg: {
    default: neutral[950],
    muted: neutral[600],
    subtle: neutral[500],
    inverse: neutral[0],
    onAccent: neutral[0],
  },
  border: {
    default: neutral[200],
    strong: neutral[300],
    /** Identifies a control — inputs, toggles. Must meet 3:1 (WCAG 1.4.11);
     * `default` and `strong` are decorative and deliberately do not. */
    interactive: neutral[500],
    focus: accent.light,
  },
  accent: {
    default: accent.light,
  },
} as const satisfies Theme;

export const darkTheme = {
  bg: {
    default: neutral[950],
    subtle: neutral[900],
    muted: neutral[800],
    inverse: neutral[0],
  },
  fg: {
    default: neutral[50],
    muted: neutral[400],
    subtle: neutral[500],
    inverse: neutral[950],
    onAccent: neutral[950],
  },
  border: {
    default: neutral[800],
    strong: neutral[700],
    interactive: neutral[500],
    focus: accent.dark,
  },
  accent: {
    default: accent.dark,
  },
} as const satisfies Theme;

/** Structural, not `typeof lightTheme`: the token objects are `as const`, so
 * that type would narrow to literal hex strings and reject `darkTheme`. */
export interface Theme {
  readonly bg: Readonly<Record<"default" | "subtle" | "muted" | "inverse", string>>;
  readonly fg: Readonly<Record<"default" | "muted" | "subtle" | "inverse" | "onAccent", string>>;
  readonly border: Readonly<Record<"default" | "strong" | "interactive" | "focus", string>>;
  readonly accent: Readonly<Record<"default", string>>;
}

/** Certainty is carried by weight, border and wording — never colour, which reads
 * as a judgement about the person (md/03 §2), and never numbers (md/05 §A.2.1).
 * Not opacity either: dimming to 75% drops `fg.muted` near 3:1. */
export const certaintyTreatment = {
  verified: {
    fgToken: "fg.default",
    borderToken: "border.strong",
    borderStyle: "solid",
    weight: "medium",
  },
  observed: {
    fgToken: "fg.default",
    borderToken: "border.default",
    borderStyle: "solid",
    weight: "normal",
  },
  suggested: {
    fgToken: "fg.muted",
    borderToken: "border.default",
    borderStyle: "dashed",
    weight: "normal",
  },
} as const;

export type CertaintyTier = keyof typeof certaintyTreatment;
