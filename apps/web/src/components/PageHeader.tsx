import type { ReactNode } from "react";

import styles from "./PageHeader.module.css";

/** 1 for the page's own header, 2 for a header opening a section within a page.
 * Deliberately not `number`: a heading level is structure, and "any number"
 * invites the h1 → h3 jump that breaks heading navigation. */
export type HeadingLevel = 1 | 2;

export interface PageHeaderProps {
  /** A short label above the title — the section this screen belongs to. Never
   * a sentence: it is orientation, not content. */
  eyebrow?: string;
  title: string;
  description?: string;
  /** Supporting metadata beneath the description — when a brief was generated,
   * how many people are in a workspace. */
  meta?: ReactNode;
  /** Screen-level controls. Right-aligned beside the title on wide viewports,
   * wrapped beneath it when there is no room. */
  actions?: ReactNode;
  headingLevel?: HeadingLevel;
}

/**
 * The top of every screen.
 *
 * Owns the `<h1>` by default. Heading level is structure, not size, and letting
 * each page choose its own is how a document ends up with two `<h1>`s or a jump
 * from `<h1>` to `<h3>` — both of which break the heading navigation screen
 * reader users rely on to skim a page (WCAG 1.3.1, 2.4.6). `headingLevel` exists
 * for the second use — a header opening a section inside a page that already has
 * its own `<h1>` — and admits only 1 or 2 so the order cannot skip.
 *
 * The eyebrow is plain text above the heading, deliberately *not* folded into
 * the heading's accessible name: the title is what a reader searches the page
 * for and what the heading list reads out, and prefixing every entry with its
 * section makes that list harder to skim, not easier. The section is already
 * announced by the navigation, where `aria-current` sits.
 */
export function PageHeader({
  eyebrow,
  title,
  description,
  meta,
  actions,
  headingLevel = 1,
}: PageHeaderProps): ReactNode {
  const Heading = headingLevel === 1 ? "h1" : "h2";

  return (
    /*
     * A `div`, not a `header`. Per HTML-AAM a `header` that descends from
     * `main` has **no role at all**, so this element is generic in the
     * accessibility tree either way and assistive technology cannot tell the
     * two spellings apart. What the spelling does change is tooling:
     * testing-library's role mapping does not implement that scoping and counts
     * every `header` as a `banner`, so the shell's real banner and this one
     * became two — and `getByRole("banner")` started failing as ambiguous on
     * every page. Teaching the landmark tests to tolerate two banners would
     * have hidden a genuine second one later; this costs nothing real instead.
     */
    <div className={styles.header}>
      <div className={styles.top}>
        <div className={styles.headingBlock}>
          {eyebrow !== undefined && <span className={styles.eyebrow}>{eyebrow}</span>}
          <Heading className={styles.title} data-level={headingLevel}>
            {title}
          </Heading>
        </div>
        {actions !== undefined && <div className={styles.actions}>{actions}</div>}
      </div>
      {description !== undefined && <p className={styles.description}>{description}</p>}
      {meta !== undefined && <p className={styles.meta}>{meta}</p>}
    </div>
  );
}
