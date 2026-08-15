"use client";

import { Suspense, type ReactNode } from "react";

import { LoginPage } from "../../routes/LoginPage.js";

/**
 * The login screen, behind a Suspense boundary.
 *
 * `LoginPage` reads `?next=` to send the reader where they were going, and
 * `useSearchParams` opts a page out of static rendering unless the part that
 * reads it is suspended. The boundary is *here* rather than around a fragment
 * of the form so that the fallback is the whole card — a half-rendered login
 * form is worse than a moment of nothing.
 *
 * The fallback is deliberately empty rather than a spinner. Reading the query
 * string takes no measurable time; a spinner would flash on every load and read
 * as slowness the app does not have.
 */
export default function Page(): ReactNode {
  return (
    <Suspense fallback={null}>
      <LoginPage />
    </Suspense>
  );
}
