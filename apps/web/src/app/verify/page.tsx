"use client";

import { Suspense, type ReactNode } from "react";

import { VerifyEmailPage } from "../../routes/VerifyEmailPage.js";

/**
 * Suspended for the same reason as `/login` — the page reads `?token=`, and
 * `useSearchParams` opts a page out of static rendering unless the part that
 * reads it is suspended. Without the boundary the production build fails on
 * prerendering this route.
 */
export default function Page(): ReactNode {
  return (
    <Suspense fallback={null}>
      <VerifyEmailPage />
    </Suspense>
  );
}
