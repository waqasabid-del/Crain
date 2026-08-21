import clsx from "clsx";
import { useId, type ReactNode } from "react";

import { headingTag, type HeadingLevel } from "./headings.js";
import styles from "./Card.module.css";

export interface CardProps {
  /** Optional label. A card without one is a container, not a region. */
  title?: ReactNode | undefined;
  /** Where the title sits under the page's `<h1>`. Default 2. */
  headingLevel?: HeadingLevel | undefined;
  /** One line under the title. */
  description?: ReactNode | undefined;
  /** Rendered at the top right of the card head — a link or a control. */
  action?: ReactNode | undefined;
  children: ReactNode;
  className?: string | undefined;
}

/**
 * The surface everything on the dashboard sits on: white, hairline, one radius,
 * no shadow until it is interactive.
 *
 * A titled card is a real `<section>` wired to its heading with
 * `aria-labelledby`, because a bare `<section>` is not a landmark and is
 * skipped by region navigation entirely — the same reasoning `Section.tsx`
 * documents. An untitled card is a plain `<div>`: a region with no accessible
 * name is worse than no region, since it appears in the landmark list as
 * "section" and tells the reader nothing.
 *
 * Production call sites: the Overview's stat row, portfolio strip and two
 * detail columns; the Projects portfolio cards; every section of a project's
 * detail page.
 */
export function Card({
  title,
  headingLevel = 2,
  description,
  action,
  children,
  className,
}: CardProps): ReactNode {
  const headingId = useId();
  const Heading = headingTag(headingLevel);

  if (title === undefined) {
    return <div className={clsx(styles.card, className)}>{children}</div>;
  }

  return (
    <section className={clsx(styles.card, className)} aria-labelledby={headingId}>
      <div className={styles.head}>
        <div className={styles.headText}>
          <Heading className={styles.title} id={headingId}>
            {title}
          </Heading>
          {description !== undefined && <p className={styles.description}>{description}</p>}
        </div>
        {action !== undefined && <div className={styles.action}>{action}</div>}
      </div>
      {children}
    </section>
  );
}
