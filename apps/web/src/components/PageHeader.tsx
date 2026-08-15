import type { ReactNode } from "react";

import styles from "./PageHeader.module.css";

export interface PageHeaderProps {
  title: string;
  description?: string;
  meta?: ReactNode;
}

/**
 * The top of every screen.
 *
 * Owns the single `<h1>`. Heading level is structure, not size, and letting each
 * page choose its own is how a document ends up with two `<h1>`s or a jump from
 * `<h1>` to `<h3>` — both of which break the heading-navigation that screen
 * reader users rely on to skim a page (WCAG 1.3.1, 2.4.6).
 */
export function PageHeader({ title, description, meta }: PageHeaderProps): ReactNode {
  return (
    <div className={styles.header}>
      <h1 className={styles.title}>{title}</h1>
      {description !== undefined && <p className={styles.description}>{description}</p>}
      {meta !== undefined && <p className={styles.meta}>{meta}</p>}
    </div>
  );
}
