"use client";

import { Suspense, type ReactNode } from "react";

import { InvitePage } from "../../routes/InvitePage.js";

/**
 * Outside the `(app)` group, and that is the point: an invited person has no
 * session yet, so a screen behind the auth guard would redirect them to sign in
 * for an account they have not created.
 *
 * Suspended for the same reason as `/login` — it reads `?token=`, and
 * `useSearchParams` opts a page out of static rendering unless the part that
 * reads it is suspended.
 */
export default function Page(): ReactNode {
  return (
    <Suspense fallback={null}>
      <InvitePage />
    </Suspense>
  );
}
