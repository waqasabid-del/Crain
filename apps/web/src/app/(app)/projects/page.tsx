"use client";

import { Suspense, type ReactNode } from "react";

import { ProjectsPage } from "../../../routes/ProjectsPage.js";

/**
 * The portfolio, behind a Suspense boundary.
 *
 * `ProjectsPage` reads `?state=` so a filtered portfolio is a shareable link,
 * and `useSearchParams` opts a page out of static rendering unless the part
 * reading it is suspended. The fallback is empty for the same reason `/login`
 * documents: reading the query string takes no measurable time, and a spinner
 * would flash on every load.
 */
export default function Page(): ReactNode {
  return (
    <Suspense fallback={null}>
      <ProjectsPage />
    </Suspense>
  );
}
