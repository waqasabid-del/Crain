import clsx from "clsx";

import styles from "./CertaintyBadge.module.css";

export type Certainty = "verified" | "observed" | "suggested";

export interface CertaintyBadgeProps {
  certainty: Certainty;
  className?: string;
}

/**
 * Human-readable labels.
 *
 * Wording matters as much as styling. "Suggested" invites correction;
 * "Low confidence" sounds like a defect report about the person the claim
 * concerns.
 */
const LABEL: Record<Certainty, string> = {
  verified: "Verified",
  observed: "Observed",
  suggested: "Suggested",
};

/**
 * Explanations surfaced on hover and to assistive technology.
 *
 * The badge alone is meaningless to someone who has not been told what the
 * tiers mean, so the explanation travels with it rather than living in a help
 * page nobody opens.
 */
const DESCRIPTION: Record<Certainty, string> = {
  verified: "Taken directly from an unambiguous source, such as a merged pull request.",
  observed: "Drawn from clear discussion, or corroborated across more than one source.",
  suggested: "Inferred from a single source such as a meeting transcript. Worth checking.",
};

/**
 * CertaintyBadge — the most product-specific component in the system.
 *
 * CAIRN's sources vary enormously in reliability. A GitHub assignment is
 * unambiguous; a commitment inferred from a meeting carries roughly 30% speaker
 * misattribution risk (md/03 §2). Presenting both with equal authority is the
 * fastest way to lose a user's trust permanently.
 *
 * Three deliberate choices:
 *
 * 1. **No colour coding.** Traffic-light styling would be the only colour in a
 *    monochrome system, drawing attention to uncertainty rather than content —
 *    and amber/red reads as a judgement about the person, not the evidence.
 *    Tiers differ by weight and border style instead, which also survives
 *    greyscale and colour-blindness with no extra work.
 *
 * 2. **No percentages.** "73% confident" looks rigorous, means nothing to a
 *    non-technical reader, and invites false precision (md/05 §A.2.1).
 *
 * 3. **Never colour alone.** WCAG 1.4.1 forbids conveying information by colour
 *    alone; here the text label carries the meaning and the styling reinforces
 *    it.
 */
export function CertaintyBadge({ certainty, className }: CertaintyBadgeProps): React.JSX.Element {
  return (
    <span
      className={clsx(styles.badge, styles[certainty], className)}
      // `role="img"` is required for the name to be exposed at all. A bare
      // <span> maps to role="generic", where ARIA prohibits naming — several
      // screen readers drop `aria-label` there entirely, silently discarding
      // the explanation this component depends on.
      role="img"
      title={DESCRIPTION[certainty]}
      aria-label={`${LABEL[certainty]}: ${DESCRIPTION[certainty]}`}
    >
      {LABEL[certainty]}
    </span>
  );
}
