import { Button } from "@cairn/ui";
import type { ReactNode } from "react";

import type { DescribedError } from "../errors.js";
import utility from "../styles/utility.module.css";
import { headingTag, type HeadingLevel } from "./headings.js";
import styles from "./States.module.css";

/** The three states every asynchronous surface has to have. */

/**
 * The shape the skeleton should take.
 *
 * A skeleton is only worth drawing if it occupies the space the real content
 * will. Three prose lines standing in for a table of six people is a layout
 * shift with extra steps, so the caller says which layout is coming and the
 * placeholder reserves that.
 */
export type LoadingShape = "prose" | "rows" | "table";

export interface LoadingStateProps {
  /** What is loading, as a noun phrase — "today's brief". Required: a skeleton
   * tells a screen reader nothing, so this text is the whole announcement. */
  label: string;
  /** Lines for `prose`, rows for `rows` and `table`. */
  lines?: number;
  shape?: LoadingShape;
}

export function LoadingState({ label, lines = 3, shape = "prose" }: LoadingStateProps): ReactNode {
  return (
    // `role="status"` is polite — right for progress, wrong for errors.
    <div className={styles[shape]} role="status">
      <span className={utility.visuallyHidden}>Loading {label}.</span>
      {Array.from({ length: lines }, (_, index) =>
        // Index keys: interchangeable placeholders with no identity or reorder.
        shape === "prose" ? (
          <span key={index} className={styles.line} aria-hidden="true" />
        ) : (
          <span key={index} className={styles.row} aria-hidden="true">
            <span className={styles.rowPrimary} />
            <span className={styles.rowSecondary} />
          </span>
        ),
      )}
    </div>
  );
}

export interface EmptyStateProps {
  title: string;
  children: ReactNode;
  action?: ReactNode;
  /**
   * Default 2, which is right when this panel is a direct child of the page.
   *
   * Inside a `Section` it is not: the panel's heading is a *sibling* of the
   * section's own `<h2>`, so the section reads as having two titles and heading
   * navigation lands on the wrong one. Pass 3 there. Defaulted rather than
   * required so every existing caller keeps the level it already had.
   */
  headingLevel?: HeadingLevel;
}

/** Nothing to show is a legitimate answer, not a failure: state it rather than
 * apologise for it (md/05 §A.7). */
export function EmptyState({
  title,
  children,
  action,
  headingLevel = 2,
}: EmptyStateProps): ReactNode {
  const Heading = headingTag(headingLevel);

  return (
    <div className={styles.panel}>
      <Heading className={styles.title}>{title}</Heading>
      <p className={styles.body}>{children}</p>
      {action !== undefined && <div className={styles.actions}>{action}</div>}
    </div>
  );
}

export interface ErrorStateProps {
  title: string;
  error: DescribedError;
  onRetry?: () => void;
  /**
   * Whether trying again could plausibly work. Default `true`.
   *
   * A permission or configuration failure will be refused identically forever,
   * and a "Try again" button in front of one is a promise the product cannot
   * keep — the reader clicks it three times and learns not to believe the next
   * thing the screen says. Pass `false` there and give `action` somewhere to
   * actually go.
   */
  retryable?: boolean;
  /** A way forward when retrying is not one — a link to the settings or to the
   * Trust Center. Rendered beside "Try again" when both are present. */
  action?: ReactNode;
  /** See `EmptyStateProps.headingLevel` — same reasoning, same default. */
  headingLevel?: HeadingLevel;
}

export function ErrorState({
  title,
  error,
  onRetry,
  retryable = true,
  action,
  headingLevel = 2,
}: ErrorStateProps): ReactNode {
  const Heading = headingTag(headingLevel);
  const showRetry = onRetry !== undefined && retryable;

  return (
    // `role="alert"`, or the failure waits for the next focus move.
    <div className={styles.panel} role="alert">
      <Heading className={styles.title}>{title}</Heading>
      <p className={styles.body}>{error.message}</p>
      {(showRetry || action !== undefined) && (
        <div className={styles.actions}>
          {showRetry && (
            <Button variant="primary" onClick={onRetry}>
              Try again
            </Button>
          )}
          {action}
        </div>
      )}
      {error.requestId !== undefined && (
        <p className={styles.reference}>Reference: {error.requestId}</p>
      )}
    </div>
  );
}
