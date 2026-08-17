import clsx from "clsx";
import type { ReactNode } from "react";

import styles from "./StatusNote.module.css";

export interface StatusNoteProps {
  children: ReactNode;
  id?: string;
  /**
   * Announce the note when it appears. Default `true`.
   *
   * Set `false` for a note that is on screen from first paint — standing
   * guidance rather than the result of something the reader just did. A live
   * region that was never live is noise a screen reader user cannot switch off.
   */
  live?: boolean;
  className?: string;
}

/**
 * A control visibly did something.
 *
 * `role="status"` is polite: it waits for a gap in speech rather than
 * interrupting, which is right for a confirmation and wrong for a failure — use
 * `InlineProblem` for that.
 */
export function StatusNote({ children, id, live = true, className }: StatusNoteProps): ReactNode {
  return (
    <p className={clsx(styles.note, className)} id={id} role={live ? "status" : undefined}>
      {children}
    </p>
  );
}
