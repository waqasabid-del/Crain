"use client";

import type { MyTasks, ProjectList, TaskSummary } from "@cairn/api-client";
import Link from "next/link";
import { useCallback, type ReactNode } from "react";

import { useApiClient } from "../api/context.js";
import { useAuth } from "../auth/context.js";
import { formatDay } from "../components/dates.js";
import { PageHeader } from "../components/PageHeader.js";
import { EmptyState, ErrorState, LoadingState } from "../components/States.js";
import { useAsync } from "../hooks/useAsync.js";
import styles from "./MyTasksPage.module.css";

/**
 * The signed-in person's own tasks, grouped by workflow column.
 *
 * Self-scoped by construction: `listMyTasks` keys on the caller's own Person,
 * so this screen can only ever show someone their own work — the My Week idiom.
 * A caller with no Person row receives empty groups, not an error, and this
 * page treats that as the ordinary state it is.
 *
 * **No counts anywhere, deliberately.** A heading is "In progress", never
 * "3 in progress": a number beside a person's own work is a tally, and a tally
 * beside work is the first step towards a scoreboard. "Recently done" carries
 * only what the API sends — a memory aid, with no figure saying how many.
 */
export function MyTasksPage(): ReactNode {
  const { activeWorkspace } = useAuth();

  if (activeWorkspace === null) {
    return (
      <>
        <PageHeader title="My tasks" description="The work assigned to you, by column." />
        <EmptyState title="Join a workspace to see your tasks">
          Join a workspace and the work assigned to you appears here.
        </EmptyState>
      </>
    );
  }

  return <Board workspaceId={activeWorkspace.id} />;
}

/**
 * The columns, in the order a reader triages their own day: what is moving,
 * what is waiting on review, what is stuck, what has not started, and lastly
 * what recently finished — a reminder, not a record of throughput.
 */
const GROUPS: readonly { key: keyof MyTasks; heading: string }[] = [
  { key: "inProgress", heading: "In progress" },
  { key: "inReview", heading: "In review" },
  { key: "blocked", heading: "Blocked" },
  { key: "todo", heading: "To do" },
  { key: "done", heading: "Recently done" },
];

/** Priority as a word, plainly. Copy, not a derived capitalisation — and a
 * value the client does not recognise renders as its own text. */
const PRIORITY_LABEL: Readonly<Record<string, string>> = {
  low: "Low",
  normal: "Normal",
  medium: "Medium",
  high: "High",
  urgent: "Urgent",
};

interface BoardData {
  tasks: MyTasks;
  projects: ProjectList;
}

function Board({ workspaceId }: { workspaceId: string }): ReactNode {
  const client = useApiClient();

  // Both in one load: the task rows carry only a project id, and the project
  // list is what turns it into the name a reader actually recognises.
  const load = useCallback(
    async (signal: AbortSignal): Promise<BoardData> => {
      const [tasks, projects] = await Promise.all([
        client.listMyTasks(workspaceId, { signal }),
        client.listProjects(workspaceId, undefined, { signal }),
      ]);
      return { tasks, projects };
    },
    [client, workspaceId],
  );
  const { state, reload } = useAsync(load, "load your tasks");

  return (
    <>
      <PageHeader title="My tasks" description="The work assigned to you, by column." />

      {state.status === "loading" && <LoadingState label="your tasks" shape="rows" lines={4} />}

      {state.status === "failed" && (
        <ErrorState title="Your tasks could not be loaded" error={state.error} onRetry={reload} />
      )}

      {state.status === "ready" && <Groups data={state.data} />}
    </>
  );
}

function Groups({ data }: { data: BoardData }): ReactNode {
  const projectNames = new Map(
    (data.projects.projects ?? []).map((project) => [project.id, project.name]),
  );

  const groups = GROUPS.map((group) => ({
    ...group,
    tasks: data.tasks[group.key] ?? [],
  })).filter((group) => group.tasks.length > 0);

  if (groups.length === 0) {
    return <EmptyState title="Nothing assigned">Nothing is assigned to you right now.</EmptyState>;
  }

  return (
    <div className={styles.groups}>
      {groups.map((group) => (
        <section key={group.key} className={styles.group} aria-label={group.heading}>
          {/* The heading is the column's name and nothing more. Never a count:
            "3 in progress" is a tally beside a person's own work. */}
          <h2 className={styles.groupHeading}>{group.heading}</h2>
          <ul className={styles.taskList}>
            {group.tasks.map((task) => (
              <li key={task.id}>
                <TaskRow task={task} projectName={projectNames.get(task.projectId) ?? null} />
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}

function TaskRow({
  task,
  projectName,
}: {
  task: TaskSummary;
  projectName: string | null;
}): ReactNode {
  return (
    <div className={styles.task}>
      <div className={styles.taskMain}>
        <Link className={styles.taskTitle} href={`/tasks/${task.id}`}>
          {task.title}
        </Link>
        {projectName !== null && <span className={styles.taskProject}>{projectName}</span>}
      </div>
      <div className={styles.taskMeta}>
        {/* Weight and border carry the priority, never colour: a red "urgent"
          would be the first hue on the screen, and urgency theatre besides. */}
        <span
          className={styles.priority}
          aria-label={`Priority: ${PRIORITY_LABEL[task.priority] ?? task.priority}`}
        >
          {PRIORITY_LABEL[task.priority] ?? task.priority}
        </span>
        {task.dueOn !== undefined && task.dueOn !== null && (
          <span className={styles.due}>
            Due <time dateTime={task.dueOn}>{formatDay(task.dueOn)}</time>
          </span>
        )}
      </div>
    </div>
  );
}
