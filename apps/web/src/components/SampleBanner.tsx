import type { ReactNode } from "react";

import styles from "./SampleBanner.module.css";

/**
 * Says, unmistakably, that what follows was not read from anyone's work.
 *
 * Not dismissable, and there is no close button by design. A notice a reader can
 * hide is a notice that is absent the second time they look at the screen — and
 * the whole risk this guards against is someone forgetting which of these
 * sentences came from a source.
 *
 * Rendered only when `VITE_CAIRN_CONTENT_SOURCE=sample`. See env.ts for why the
 * default is the real API.
 */
export function SampleBanner(): ReactNode {
  return (
    // Not `role="alert"`: this is a standing condition of the page, and an alert
    // interrupts whatever a screen reader is currently reading. `role="note"`
    // puts it in the landmark list where a reader can find it deliberately.
    <div className={styles.banner} role="note">
      <span className={styles.label}>Example content.</span>
      <span>
        The brief endpoints are still being built, so these sentences are a fixed sample. Nothing
        here was read from your team&rsquo;s work, and no citation below points at a real source.
      </span>
    </div>
  );
}
