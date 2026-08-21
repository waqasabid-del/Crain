"use client";

import { use, type ReactNode } from "react";

import { PersonDetailPage } from "../../../../routes/PersonDetailPage.js";

export default function Page({ params }: { params: Promise<{ personId: string }> }): ReactNode {
  const { personId } = use(params);
  return <PersonDetailPage personId={personId} />;
}
