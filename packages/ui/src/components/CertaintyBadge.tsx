import clsx from "clsx";

import styles from "./CertaintyBadge.module.css";

export type Certainty = "verified" | "observed" | "suggested";

export interface CertaintyBadgeProps {
  certainty: Certainty;
  className?: string;
}

const LABEL: Record<Certainty, string> = {
  verified: "Verified",
  observed: "Observed",
  suggested: "Suggested",
};

const DESCRIPTION: Record<Certainty, string> = {
  verified: "Taken directly from an unambiguous source, such as a merged pull request.",
  observed: "Drawn from clear discussion, or corroborated across more than one source.",
  suggested: "Inferred from a single source such as a meeting transcript. Worth checking.",
};

/** Tiers differ by weight and border, never colour (WCAG 1.4.1, and colour reads
 * as a judgement about the person). No percentages — md/05 §A.2.1. */
export function CertaintyBadge({ certainty, className }: CertaintyBadgeProps): React.JSX.Element {
  return (
    <span
      className={clsx(styles.badge, styles[certainty], className)}
      // role="img": a bare <span> is role="generic", where ARIA forbids naming.
      role="img"
      // Focusable so the description is reachable without a pointer (WCAG 1.4.13).
      // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex
      tabIndex={0}
      title={DESCRIPTION[certainty]}
      aria-label={`${LABEL[certainty]}: ${DESCRIPTION[certainty]}`}
    >
      {LABEL[certainty]}
      <span className={styles.description} aria-hidden="true">
        {DESCRIPTION[certainty]}
      </span>
    </span>
  );
}
