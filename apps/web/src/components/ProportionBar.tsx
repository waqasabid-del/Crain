import type { ReactNode } from "react";

import styles from "./ProportionBar.module.css";

export interface ProportionBarProps {
  /** How many items are in this state. */
  value: number;
  /** How many there are altogether. Zero renders an empty track. */
  total: number;
  /** What the bar is about, for the accessible name. */
  label: string;
}

/**
 * How much of the portfolio sits in one state.
 *
 * A proportion of a *set of projects*, never of a person's work and never a
 * completion figure: CAIRN holds no planned-work model, so "60% done" would be
 * an invention. This bar can only ever say "three of eight projects".
 *
 * The number is always rendered as text beside it — the bar is a second,
 * redundant encoding, so nothing here is communicated by shape alone.
 *
 * Production call site: the Overview's state-distribution strip.
 */
export function ProportionBar({ value, total, label }: ProportionBarProps): ReactNode {
  const share = total === 0 ? 0 : Math.round((value / total) * 100);
  return (
    <div
      className={styles.track}
      role="img"
      aria-label={`${label}: ${String(value)} of ${String(total)} projects`}
    >
      <div className={styles.fill} style={{ inlineSize: `${String(share)}%` }} />
    </div>
  );
}
