/**
 * Heading level as a first-class prop.
 *
 * `<h1>` is deliberately absent: `PageHeader` owns the single `<h1>` on every
 * screen, and a component that can be dropped anywhere must never be able to
 * mint a second one. Everything below it is a judgement the *caller* has to
 * make, because only the caller knows how deep it sits — which is why the
 * hardcoded `<h2>` in `EmptyState` produced two sibling `<h2>`s wherever it was
 * used inside a section (WCAG 1.3.1).
 */

export type HeadingLevel = 2 | 3 | 4 | 5 | 6;

/** A lookup rather than `` `h${level}` ``: a template literal over a number is
 * exactly the expression the lint rule exists to catch, and the map is checked
 * to be total by the index signature. */
const TAGS = { 2: "h2", 3: "h3", 4: "h4", 5: "h5", 6: "h6" } as const satisfies Record<
  HeadingLevel,
  string
>;

export function headingTag(level: HeadingLevel): (typeof TAGS)[HeadingLevel] {
  return TAGS[level];
}
