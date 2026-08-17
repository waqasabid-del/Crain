/** Class-name primitives that are not worth a component.
 *
 * Exported from the package because the alternative is what happened: the same
 * eight declarations hand-copied into four stylesheets, where a change to one
 * of them silently means four behaviours. */

import styles from "./utilities.module.css";

/** Visible to a screen reader, invisible on screen — for labels that would be
 * redundant beside an icon a sighted user can already read. */
export const visuallyHidden: string = styles.visuallyHidden ?? "";
