"use client";

import { use, type ReactNode } from "react";

import { TaskDetailPage } from "../../../../routes/TaskDetailPage.js";

export default function Page({ params }: { params: Promise<{ taskId: string }> }): ReactNode {
  const { taskId } = use(params);
  return <TaskDetailPage taskId={taskId} />;
}
