"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, type ReactNode } from "react";

import { ErrorState, LoadingState } from "../components/States.js";
import { useAuth } from "./context.js";
import styles from "./RequireAuth.module.css";

function Gate({ children }: { children: ReactNode }): ReactNode {
  return (
    <div className={styles.gate}>
      <div className={styles.inner}>{children}</div>
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
      <Gate>
        <LoadingState label="your workspace" />
      </Gate>
    );
  }

  if (status === "unavailable") {
    return (
      <Gate>
        <ErrorState
          title="CAIRN could not sign you in"
          error={error ?? { message: "CAIRN could not reach the server." }}
          onRetry={retry}
        />
      </Gate>
    );
  }

  if (status === "anonymous") {
    // Held on loading while the effect navigates; never render the children.
    return (
      <Gate>
        <LoadingState label="your workspace" />
      </Gate>
    );
  }

  return children;
}
