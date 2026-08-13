/**
 * Colour tokens.
 *
 * CAIRN's palette is black and white. This is not minimalism for its own sake —
 * it is doing real product work:
 *
 * 1. A calm, neutral interface reinforces "this tool observes and informs; it
 *    does not judge or rank". Given how close this product sits to workplace
 *    monitoring, visual restraint is positioning (md/05 §A.4).
 * 2. Colour carries meaning, and meaning about people is exactly what CAIRN
 *    refuses to imply. A red/amber/green vocabulary would smuggle judgement in
 *    through the back door.
 *
 * There is therefore no semantic "success/warning/danger" colour scale for
 * anything describing a person's work. Status colours exist only for *system*
 * state — a failed integration, an unsaved form — never for human activity.
 *
 * @see md/05-ux-design-privacy.md §A.1, §A.4
 */

/**
 * The neutral ramp. Every value is a true grey (equal R/G/B) so the interface
 * has no colour temperature at all.
 *
 * Steps are named by lightness rather than by role, so that light and dark
 * themes can map roles to different steps without renaming anything.
 */
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

/**
 * The single accent, used only for focus rings and interactive affordances.
 *
 * Deliberately one colour, not a palette. It exists so that keyboard focus is
 * unmistakable — a WCAG 2.1 AA requirement (2.4.7 Focus Visible) that a purely
 * monochrome interface tends to fail.
 */
export const accent = {
  light: "#1d4ed8",
  dark: "#60a5fa",
} as const;

/**
 * Semantic tokens for the light theme.
 *
 * Roles, not colours. Components reference `fg.default`, never `neutral[900]`,
 * so a theme change never requires touching a component.
 */
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
    /** Decorative dividers and card outlines. See the note on §border below. */
    default: neutral[200],
    /** Emphasised dividers. Still decorative. */
    strong: neutral[300],
    /** Boundaries that identify a control — inputs, toggles. Must meet 3:1. */
    interactive: neutral[500],
    focus: accent.light,
  },
  accent: {
    default: accent.light,
  },
} as const;

/** Semantic tokens for the dark theme. Mirrors `lightTheme` role for role. */
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
} as const;

export type Theme = typeof lightTheme;

/**
 * A note on borders, since the distinction is easy to collapse and expensive to
 * get wrong.
 *
 * WCAG 1.4.11 requires 3:1 contrast for "visual information required to
 * identify user interface components and states" — but not for decoration. A
 * hairline dividing two sections carries no information: remove it and the
 * layout still reads. The outline of a text input carries essential
 * information: remove it and a user cannot tell where to type.
 *
 * So `border.default` and `border.strong` are deliberately low-contrast and
 * carry no accessibility requirement, while `border.interactive` meets 3:1 in
 * both themes and is mandatory for anything that identifies a control.
 *
 * The alternative — darkening every border to 3:1 — would satisfy a naive
 * reading of the guideline while making the interface heavy and noisy, which
 * works against the calm, restrained direction the product depends on. Deciding
 * this deliberately is the difference between accessible and merely compliant.
 */

/**
 * Visual treatment for the three certainty tiers.
 *
 * This is the most product-specific part of the design system, and the part
 * most easily got wrong.
 *
 * CAIRN's sources vary enormously in reliability — a GitHub assignment is
 * unambiguous, while a meeting-derived commitment carries roughly 30% speaker
 * misattribution risk (md/03 §2). The interface must show that difference, or
 * it presents a guess with the same authority as a fact.
 *
 * The obvious approach — green / amber / red — is wrong here for two reasons:
 * it would be the only colour in a monochrome system, drawing the eye to
 * *uncertainty* rather than to content; and traffic-light colouring reads as a
 * judgement about the person the claim concerns, not about the evidence.
 *
 * So certainty is expressed through **weight, opacity and border treatment**
 * instead. A less certain claim looks quieter, not more alarming. This also
 * means the distinction survives greyscale printing and colour-blindness
 * without any additional work.
 *
 * Note there is no numeric confidence anywhere: a "73%" badge looks rigorous,
 * means nothing to a non-technical reader, and invites false precision
 * (md/05 §A.2.1).
 */
export const certaintyTreatment = {
  verified: {
    fgToken: "fg.default",
    borderStyle: "solid",
    opacity: 1,
  },
  observed: {
    fgToken: "fg.default",
    borderStyle: "solid",
    opacity: 0.85,
  },
  suggested: {
    fgToken: "fg.muted",
    borderStyle: "dashed",
    opacity: 0.75,
  },
} as const;
