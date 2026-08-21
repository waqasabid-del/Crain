"use client";

import { use, type ReactNode } from "react";

import { ProjectDetailPage } from "../../../../routes/ProjectDetailPage.js";

export default function Page({ params }: { params: Promise<{ projectId: string }> }): ReactNode {
  const { projectId } = use(params);
  return <ProjectDetailPage projectId={projectId} />;
}
