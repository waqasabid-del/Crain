"use client";

import type { ReactNode } from "react";

import { DashboardPage } from "../../routes/DashboardPage.js";

/** The workspace overview is the home screen: what the team has delivered,
 * what is still open, and the evidence behind each line. The daily narrative
 * moved to `/brief`, one click away and linked as this page's primary action. */
export default function Page(): ReactNode {
  return <DashboardPage />;
}
