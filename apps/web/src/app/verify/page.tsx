"use client";

import { Suspense, type ReactNode } from "react";

import { VerifyPage } from "../../routes/VerifyPage.js";

/**
 * The path every verification email links to — and, until this file existed,
 * a 404 in every inbox.
 *
 * Outside the `(app)` group for the same reason as `/invite`: somebody clicking
 * a link from their inbox may have no session in this browser, and a screen
 * behind the auth guard would redirect them to sign in, discarding the token
 * they arrived with.
 *
 * Suspended because it reads `?token=`, and `useSearchParams` opts a page out of
 * static rendering unless the part that reads it is suspended.
 */
export default function Page(): ReactNode {
  return (
    <Suspense fallback={null}>
      <VerifyPage />
    </Suspense>
  );
}
