import clsx from "clsx";
import { useId, type ReactNode } from "react";

import { headingTag, type HeadingLevel } from "./headings.js";
import styles from "./Section.module.css";

export type SectionVariant = "plain" | "eyebrow";

export interface SectionProps {
  title: ReactNode;
  /** Where this section sits under the page's `<h1>`. Default 2. */
  headingLevel?: HeadingLevel;
  variant?: SectionVariant;
  description?: ReactNode;
  children: ReactNode;
  className?: string;
  /** For the one case the variants do not cover — a count set beside the title,
   * as the feed does. Applied to the heading, not the section. */
  headingClassName?: string;
}

/**
 * A labelled region.
 *
 * The `aria-labelledby` is the point: a bare `<section>` is not a landmark and
 * is skipped by region navigation entirely, so the heading has to be wired to it
 * for the region to exist at all.
 *
 * The id comes from `useId` rather than the caller, because hand-written ids
 * collide — `id="never"` was written on two different routes, and a duplicate id
 * makes `aria-labelledby` resolve to whichever element happens to come first.
 * That is silent, and it survives review.
 */
export function Section({
  title,
  headingLevel = 2,
  variant = "plain",
  description,
  children,
  className,
  headingClassName,
}: SectionProps): ReactNode {
  const headingId = useId();
  const Heading = headingTag(headingLevel);

  return (
    <section className={clsx(styles.section, className)} aria-labelledby={headingId}>
      <Heading className={clsx(styles[variant], headingClassName)} id={headingId}>
        {title}
      </Heading>
      {description !== undefined && <p className={styles.description}>{description}</p>}
      {children}
    </section>
  );
}
