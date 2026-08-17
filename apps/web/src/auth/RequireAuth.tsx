"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, type ReactNode } from "react";

import { ErrorState, LoadingState } from "../components/States.js";
import utility from "../styles/utility.module.css";
import { useAuth } from "./context.js";
import styles from "./RequireAuth.module.css";

/**
 * Every gate state is a page, and a page owes a level-one heading.
 *
 * Visually hidden rather than drawn: these screens are deliberately bare — a
 * skeleton, or one small panel — and a headline above them would be the loudest
 * thing on a screen whose whole job is to be brief. Hidden text still gives a
 * screen-reader user the document outline, so `ErrorState`'s `h2` sits under an
 * `h1` instead of being the highest heading on the page.
 */
function Gate({ heading, children }: { heading: string; children: ReactNode }): ReactNode {
  return (
    <div className={styles.gate}>
      <div className={styles.inner}>
        <h1 className={utility.visuallyHidden}>{heading}</h1>
        {children}
      </div>
    </div>
  );
}

/** The gate in front of every screen but login: a layout route, not a per-page
 * wrapper someone must remember. A redirect, not a security control — the API
 * refuses to answer without a session. */
export function RequireAuth({ children }: { children: ReactNode }): ReactNode {
  const { status, error, retry } = useAuth();
  const router = useRouter();
  const pathname = usePathname();
  const search = useSearchParams().toString();

  // An effect, not a render-time `router.replace`: navigating during render
  // updates router state while React is rendering.
  useEffect(() => {
    if (status !== "anonymous") return;
    const attempted = search ? `${pathname}?${search}` : pathname;
    // `replace`, so Back from login does not loop. `next` is attacker-supplied,
    // and `LoginPage` uses it only if it is a same-site absolute path.
    router.replace(`/login?next=${encodeURIComponent(attempted)}`);
  }, [status, router, pathname, search]);

  if (status === "loading") {
    return (
      <Gate heading="Opening your workspace">
        <LoadingState label="your workspace" />
      </Gate>
    );
  }

  if (status === "unavailable") {
    return (
      <Gate heading="Sign in unavailable">
        <ErrorState
          title="CAIRN could not sign you in"
          error={error ?? { message: "CAIRN could not reach the server." }}
          onRetry={retry}
        />
      </Gate>
    );
  }

  if (status === "anonymous") {
    // Never render the children. The announcement says what is actually
    // happening: the effect above is navigating to the sign-in screen, and
    // "Loading your workspace" told a screen-reader user to wait for a
    // workspace that is not coming.
    return (
      <Gate heading="Signing in required">
        <p className={styles.notice} role="status">
          Taking you to the sign-in screen.
        </p>
      </Gate>
    );
  }

  return children;
}
