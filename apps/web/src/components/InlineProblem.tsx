import { Button } from "@cairn/ui";
import clsx from "clsx";
import type { ReactNode } from "react";

import type { DescribedError } from "../errors.js";
import styles from "./InlineProblem.module.css";

export interface InlineProblemProps {
  error: DescribedError;
  /**
   * Applied to the message paragraph, so a form control can name it in
   * `aria-describedby`.
   *
   * On the paragraph rather than on the wrapper deliberately: a description is
   * flattened to the text of whatever it points at, and pointing at the wrapper
   * would append "Try again" and the reference ID to the field's description —
   * read out on every focus, and neither of them a description of the field.
   */
  id?: string;
  /** Offered whenever the action is repeatable. Eleven hand-written copies of
   * this message offered nothing, leaving reload as the only way forward. */
  onRetry?: () => void;
  className?: string;
}

/**
 * Something went wrong, said where the reader is looking.
 *
 * `role="alert"` because a failure that waits for the next focus move is a
 * failure the reader acts on too late — they have already retyped the field or
 * pressed the button again.
 */
export function InlineProblem({ error, id, onRetry, className }: InlineProblemProps): ReactNode {
  return (
    <div className={clsx(styles.problem, className)} role="alert">
      <p className={styles.message} id={id}>
        {error.message}
      </p>
      {onRetry !== undefined && (
        <Button size="sm" onClick={onRetry}>
          Try again
        </Button>
      )}
      {error.requestId !== undefined && (
        <p className={styles.reference}>Reference: {error.requestId}</p>
      )}
    </div>
  );
}
