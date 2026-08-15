"use client";

import { useParams } from "next/navigation";
import type { ReactNode } from "react";

import { ArchivedBriefPage } from "../../../../routes/ArchivedBriefPage.js";

export default function Page(): ReactNode {
  const params = useParams<{ briefId: string }>();
  return <ArchivedBriefPage briefId={params.briefId} />;
}
