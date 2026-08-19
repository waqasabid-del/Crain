import type { ReactNode } from "react";

import styles from "../routes/SignInCard.module.css";

/**
 * The auth screens' shared brand badge — the star mark on the sign-in card,
 * not the stacked-stones icon used elsewhere in the app. `inverse` flips the
 * badge for the dark aside, matching the design's `.logo--inverse`. One
 * definition, because five identical copies is how the mark drifts.
 */
export function BrandMark({ inverse = false }: { inverse?: boolean }): ReactNode {
  return (
    <span className={inverse ? styles.logoMarkInverse : styles.logoMark}>
      <svg
        width="16"
        height="16"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
        focusable="false"
      >
        <path d="M12 3l3 5 6 1-4.5 4 1 6-5.5-3-5.5 3 1-6L3 9l6-1z" />
      </svg>
    </span>
  );
}
