import type { TaskSummary } from "@cairn/api-client";
import Link from "next/link";
import type { ReactNode } from "react";

import { Avatar } from "./Avatar.js";
import { formatDay } from "./dates.js";
import styles from "./TaskCard.module.css";

/** The four priorities the API speaks. A value the client does not recognise
 * renders as its own text rather than being coerced into one of these. */
const PRIORITY_LABEL: Readonly<Record<string, string>> = {
  low: "Low",
  normal: "Normal",
  high: "High",
  urgent: "Urgent",
};

/**
 * One task on a project's board.
 *
 * Title, priority, who holds it, and when it is due — and nothing measured.
 * The card deliberately carries no age, no "time in column", no activity
 * decoration: a board that decorates its cards with movement is a leaderboard
 * of the people working it.
 *
 * The whole card is a click target via the stretched `::after` on the title
 * link — the same pattern as the Team grid's person cards — so the accessible
 * name of the link stays the task's title rather than every word on the card.
 */
export function TaskCard({ task }: { task: TaskSummary }): ReactNode {
  const priority = PRIORITY_LABEL[task.priority] ?? task.priority;
  const assignee = task.assigneeName ?? null;

  return (
    <article className={styles.card}>
      {/* A small mono pill, following StateBadge: weight and border carry the
        priority, colour never does — an "urgent" in red would be the first
        colour on the page and would read as a verdict. */}
      <span className={styles.priority} aria-label={`Priority: ${priority}`}>
        {priority}
      </span>

      <p className={styles.title}>
        <Link className={styles.link} href={`/tasks/${task.id}`}>
          {task.title}
        </Link>
      </p>

      <div className={styles.foot}>
        {assignee === null ? (
          // Unassigned is a fact about the task, not a gap to nag about.
          <span className={styles.unassigned}>Unassigned</span>
        ) : (
          <span className={styles.assignee}>
            <Avatar name={assignee} size="sm" />
            {assignee}
          </span>
        )}
        {task.dueOn != null && (
          <time className={styles.due} dateTime={task.dueOn}>
            {`Due ${formatDay(task.dueOn)}`}
          </time>
        )}
      </div>
    </article>
  );
}
