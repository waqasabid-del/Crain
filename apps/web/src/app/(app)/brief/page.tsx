"use client";

import type { ReactNode } from "react";

import { BriefPage } from "../../../routes/BriefPage.js";

/** The daily narrative, moved off `/` when the overview took the home slot.
 * Its own route rather than a tab: it is a document somebody reads, links to
 * and comes back to. */
export default function Page(): ReactNode {
  return <BriefPage />;
}
