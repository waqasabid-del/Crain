import type { ReactNode } from "react";

import styles from "./AuthCard.module.css";

export interface AuthCardProps {
  /** The `<h1>`. These screens have no `PageHeader`, so the card owns it. */
  title: string;
  subtitle?: ReactNode;
  /** The cairn mark. Off for screens that are a continuation rather than an
   * arrival — a redeemed invitation already knows where it is. */
  brand?: boolean;
  children: ReactNode;
  /** Below the body, quiet and centred — "Already have an account?" */
  footer?: ReactNode;
}

/** Three stones, stacked. Inline rather than an asset: it is eleven elements of
 * SVG, and a request for it would be a request on the very first paint. */
function CairnMark(): ReactNode {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true" focusable="false">
      <rect x="4" y="12.5" width="10" height="3" rx="1.2" fill="currentColor" />
      <rect x="5.5" y="7.75" width="7" height="3" rx="1.2" fill="currentColor" />
      <rect x="7" y="3" width="4" height="3" rx="1.2" fill="currentColor" />
    </svg>
  );
}

/**
 * The full-viewport centred card that sign-in, sign-up and invitation
 * redemption all are.
 */
export function AuthCard({
  title,
  subtitle,
  brand = true,
  children,
  footer,
}: AuthCardProps): ReactNode {
  return (
    <div className={styles.page}>
      <div className={styles.card}>
        {brand && (
          <div className={styles.brand}>
            <CairnMark />
            <span className={styles.brandName}>Cairn</span>
          </div>
        )}

        <h1 className={styles.title}>{title}</h1>
        {subtitle !== undefined && <p className={styles.subtitle}>{subtitle}</p>}

        <div className={styles.body}>{children}</div>

        {footer !== undefined && <div className={styles.footer}>{footer}</div>}
      </div>
    </div>
  );
}
