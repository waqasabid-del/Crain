import clsx from "clsx";
import type { ReactNode } from "react";

import styles from "./StateBadge.module.css";

/** The five states a project may be in. Mirrors the API's enum exactly; a
 * state the client does not recognise renders as its own text rather than
 * being coerced into one of these. */
export type ProjectStateName = "active" | "paused" | "blocked" | "completed" | "unknown";

const LABEL: Readonly<Record<string, string>> = {
  active: "Active",
  paused: "Paused",
  blocked: "Blocked",
  completed: "Completed",
  unknown: "Not declared",
};

/**
 * A project's declared state.
 *
 * **Differentiated by weight and border, never by hue.** The palette is
 * monochrome by decision, and a red "blocked" chip would be the first colour
 * on a screen — but more importantly, a state nobody declared (`unknown`) sits
 * beside states somebody did, and colour would make the absence of a
 * declaration look like a verdict. `unknown` is deliberately the quietest.
 *
 * Production call sites: portfolio cards, the project detail header, the
 * Overview's state-distribution strip.
 */
export function StateBadge({ state }: { state: string }): ReactNode {
  const known = state in LABEL;
  return (
    <span
      className={clsx(styles.badge, known && styles[state])}
      data-state={state}
      // The label is the whole content, so no extra announcement is needed —
      // but "Not declared" alone is a fragment, so the category is spoken too.
      aria-label={`Project state: ${LABEL[state] ?? state}`}
    >
      {LABEL[state] ?? state}
    </span>
  );
}
