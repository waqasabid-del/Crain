"use client";

import {
  ApiError,
  type ProjectDetail,
  type TaskDetail,
  type TaskState,
  type TaskUpdateBody,
} from "@cairn/api-client";
import { Button } from "@cairn/ui";
import clsx from "clsx";
import Link from "next/link";
import { useCallback, useState, type ReactNode, type SyntheticEvent } from "react";

import { useApiClient } from "../api/context.js";
import { useAuth } from "../auth/context.js";
import { Avatar } from "../components/Avatar.js";
import { Card } from "../components/Card.js";
import { Field } from "../components/Field.js";
import { InlineProblem } from "../components/InlineProblem.js";
import { PageHeader } from "../components/PageHeader.js";
import { EmptyState, ErrorState, LoadingState } from "../components/States.js";
import { StatusNote } from "../components/StatusNote.js";
import { describeError, type DescribedError } from "../errors.js";
import { useAsync } from "../hooks/useAsync.js";
import utility from "../styles/utility.module.css";
import styles from "./TaskDetailPage.module.css";

/**
 * One task: what it is, where it may move next, and everything that has
 * happened to it.
 *
 * **The workflow is a closed table and the API owns it.** The buttons below
 * offer exactly the moves that are legal from the current state, but the table
 * here is a copy for the screen, never the authority — an illegal move still
 * goes to the server and the server's own refusal is what the reader sees.
 *
 * **History is an audit trail, not a feed.** The server renders each entry
 * into one neutral sentence, identically for every reader. The page lists
 * them in order and adds nothing: no grouping, no per-person anything, no
 * count. A history that can be re-aggregated per person is a scoreboard with
 * extra steps.
 */
export function TaskDetailPage({ taskId }: { taskId: string }): ReactNode {
  const { activeWorkspace } = useAuth();

  if (activeWorkspace === null) {
    return (
      <>
        <PageHeader title="Task" />
        <EmptyState title="Join a workspace to see this task">
          Join a workspace to see this task.
        </EmptyState>
      </>
    );
  }

  return <Detail workspaceId={activeWorkspace.id} taskId={taskId} />;
}

/** One member row, as the generated client types it. */
type MemberEntry = NonNullable<ProjectDetail["members"]>[number];

/** The workflow columns, in the words the board uses for them. */
const STATE_LABEL: Readonly<Record<string, string>> = {
  todo: "To do",
  in_progress: "In progress",
  in_review: "In review",
  blocked: "Blocked",
  done: "Done",
};

/** How a priority reads. A value the client does not recognise renders as its
 * own word rather than being coerced into one of these. */
const PRIORITY_LABEL: Readonly<Record<string, string>> = {
  low: "Low",
  normal: "Normal",
  high: "High",
  urgent: "Urgent",
};

const PRIORITY_CHOICES: readonly { value: string; label: string }[] = [
  { value: "low", label: "Low" },
  { value: "normal", label: "Normal" },
  { value: "high", label: "High" },
  { value: "urgent", label: "Urgent" },
];

/** One move the workflow allows, in the word the button shows. */
interface Move {
  to: TaskState;
  label: string;
}

/**
 * The workflow, copied for the screen. Mirrors the server's closed table:
 * `done` deliberately has no entry — done is terminal, and the sentence the
 * page shows instead explains the archive-and-recreate path.
 */
const MOVES: Readonly<Record<string, readonly Move[]>> = {
  todo: [
    { to: "in_progress", label: "Start" },
    { to: "blocked", label: "Mark blocked" },
  ],
  in_progress: [
    { to: "in_review", label: "Send to review" },
    { to: "blocked", label: "Mark blocked" },
  ],
  in_review: [
    { to: "done", label: "Mark done" },
    { to: "in_progress", label: "Send back" },
  ],
  blocked: [
    { to: "in_progress", label: "Unblock" },
    { to: "todo", label: "Return to to-do" },
  ],
  done: [],
};

/**
 * A refusal the server wrote a sentence for, or the app's own copy otherwise.
 *
 * A 409 on this page is the product speaking — "review means somebody else
 * looked" — and paraphrasing it would soften a rule into a suggestion. The
 * server's own sentence surfaces verbatim; every other failure keeps the
 * app's one voice from `describeError`.
 */
function describeRefusal(error: unknown, action: string): DescribedError {
  if (error instanceof ApiError && error.status === 409 && error.problem.detail) {
    const described: DescribedError = { message: error.problem.detail };
    if (error.problem.requestId !== undefined) described.requestId = error.problem.requestId;
    return described;
  }
  return describeError(error, action);
}

interface TaskView {
  task: TaskDetail;
  project: ProjectDetail;
}

/** What the read produced: the task and its project, or the honest fact that
 * no task answers to this link. */
type Loaded = { found: true; view: TaskView } | { found: false };

function Detail({ workspaceId, taskId }: { workspaceId: string; taskId: string }): ReactNode {
  const client = useApiClient();

  const load = useCallback(
    async (signal: AbortSignal): Promise<Loaded> => {
      let task: TaskDetail;
      try {
        task = await client.getTask(workspaceId, taskId, { signal });
      } catch (error) {
        // A 404 is an answer, not a failure: nothing here matches the link.
        if (error instanceof ApiError && error.status === 404) return { found: false };
        throw error;
      }
      // The project supplies its own name for the hero and its member list
      // for the assignee control; the task payload carries neither.
      const project = await client.getProject(workspaceId, task.projectId, { signal });
      return { found: true, view: { task, project } };
    },
    [client, workspaceId, taskId],
  );

  const { state, reload } = useAsync(load, "load this task");

  if (state.status === "loading") {
    return (
      <>
        <PageHeader eyebrow="Task" title="Loading" />
        <LoadingState label="this task" shape="rows" lines={4} />
      </>
    );
  }

  if (state.status === "failed") {
    return (
      <>
        <PageHeader eyebrow="Task" title="Task" />
        <ErrorState
          title="This task could not be loaded"
          error={state.error}
          onRetry={reload}
          action={
            <Link className={utility.actionLink} href="/tasks">
              My tasks
            </Link>
          }
        />
      </>
    );
  }

  if (!state.data.found) {
    return (
      <>
        <PageHeader eyebrow="Task" title="Task" />
        <EmptyState
          title="Task not found"
          action={
            <Link className={utility.actionLink} href="/tasks">
              My tasks
            </Link>
          }
        >
          No task in this workspace matches this link.
        </EmptyState>
      </>
    );
  }

  const { task, project } = state.data.view;
  const archived = task.archivedAt != null;

  return (
    <div className={styles.stack}>
      <Hero workspaceId={workspaceId} task={task} project={project} onChanged={reload} />
      <Description text={task.description} />
      <MoveTask workspaceId={workspaceId} task={task} archived={archived} onChanged={reload} />
      <EditTask
        workspaceId={workspaceId}
        task={task}
        members={project.members ?? []}
        archived={archived}
        onChanged={reload}
      />
      <History task={task} />
    </div>
  );
}

/** The head of the page: what this task is and where it stands. */
function Hero({
  workspaceId,
  task,
  project,
  onChanged,
}: {
  workspaceId: string;
  task: TaskDetail;
  project: ProjectDetail;
  onChanged: () => void;
}): ReactNode {
  const archived = task.archivedAt != null;

  return (
    <Card className={styles.hero}>
      <div className={styles.heroBand}>
        <div className={styles.heroText}>
          <span className={styles.eyebrow}>Task</span>
          <h1 className={styles.heroTitle}>{task.title}</h1>

          <div className={styles.badges}>
            <TaskStateBadge state={task.state} />
            <span className={styles.priority}>
              {PRIORITY_LABEL[task.priority] ?? task.priority}
            </span>
            {archived && <span className={styles.archivedWord}>Archived</span>}
          </div>

          <dl className={styles.facts}>
            <div className={styles.fact}>
              <dt className={styles.factName}>Project</dt>
              <dd className={styles.factValue}>
                <Link className={styles.factLink} href={`/projects/${task.projectId}`}>
                  {project.name}
                </Link>
              </dd>
            </div>

            <div className={styles.fact}>
              <dt className={styles.factName}>Assignee</dt>
              <dd className={styles.factValue}>
                {task.assigneePersonId != null ? (
                  <Link className={styles.assignee} href={`/people/${task.assigneePersonId}`}>
                    <Avatar name={task.assigneeName ?? "Someone"} size="sm" />
                    <span>{task.assigneeName ?? "Someone"}</span>
                  </Link>
                ) : (
                  <span className={styles.muted}>Unassigned</span>
                )}
              </dd>
            </div>

            {task.dueOn != null && (
              <div className={styles.fact}>
                <dt className={styles.factName}>Due</dt>
                <dd className={styles.factValue}>{formatDay(task.dueOn)}</dd>
              </div>
            )}
          </dl>
        </div>

        <ArchiveControl workspaceId={workspaceId} task={task} onChanged={onChanged} />
      </div>
    </Card>
  );
}

/**
 * A task's workflow column, said the badge way the project pages already say
 * state: weight and border, never hue. A state the client does not recognise
 * renders as its own text rather than being coerced into a column.
 */
function TaskStateBadge({ state }: { state: string }): ReactNode {
  const known = state in STATE_LABEL;
  return (
    <span
      className={clsx(styles.stateBadge, known && styles[`state_${state}`])}
      data-state={state}
      aria-label={`Task state: ${STATE_LABEL[state] ?? state}`}
    >
      {STATE_LABEL[state] ?? state}
    </span>
  );
}

function Description({ text }: { text: string }): ReactNode {
  const paragraphs = text
    .split(/\n+/)
    .map((line) => line.trim())
    .filter((line) => line !== "");

  return (
    <Card title="Description">
      {paragraphs.length === 0 ? (
        <p className={styles.muted}>No description.</p>
      ) : (
        paragraphs.map((paragraph, index) => (
          <p className={styles.paragraph} key={index}>
            {paragraph}
          </p>
        ))
      )}
    </Card>
  );
}

/** The moves the workflow allows from here, and only those. */
function MoveTask({
  workspaceId,
  task,
  archived,
  onChanged,
}: {
  workspaceId: string;
  task: TaskDetail;
  archived: boolean;
  onChanged: () => void;
}): ReactNode {
  const client = useApiClient();
  const [moving, setMoving] = useState<TaskState | null>(null);
  const [problem, setProblem] = useState<DescribedError | null>(null);

  const moves = MOVES[task.state] ?? [];

  const move = (to: TaskState): void => {
    setMoving(to);
    setProblem(null);
    client
      .setTaskState(workspaceId, task.id, to)
      .then(() => {
        onChanged();
      })
      .catch((error: unknown) => {
        setProblem(describeRefusal(error, "move this task"));
      })
      .finally(() => {
        setMoving(null);
      });
  };

  return (
    <Card title="Move this task" description="One step along the workflow at a time.">
      {archived ? (
        <p className={styles.muted}>An archived task cannot move. Restore it first.</p>
      ) : task.state === "done" ? (
        <p className={styles.muted}>
          Done is final. A task closed in error is archived, and the work reopened as a new task.
        </p>
      ) : (
        <div className={styles.moves}>
          {moves.map((choice) => (
            <Button
              key={choice.to}
              onClick={() => {
                move(choice.to);
              }}
              loading={moving === choice.to}
              disabled={moving !== null && moving !== choice.to}
            >
              {choice.label}
            </Button>
          ))}
        </div>
      )}
      {problem !== null && <InlineProblem error={problem} />}
    </Card>
  );
}

/** Title, description, priority, assignee and due date — behind a disclosure,
 * because reading a task is the common case and editing it is not. */
function EditTask({
  workspaceId,
  task,
  members,
  archived,
  onChanged,
}: {
  workspaceId: string;
  task: TaskDetail;
  members: MemberEntry[];
  archived: boolean;
  onChanged: () => void;
}): ReactNode {
  const client = useApiClient();
  const [title, setTitle] = useState(task.title);
  const [description, setDescription] = useState(task.description);
  const [priority, setPriority] = useState(task.priority);
  const [assignee, setAssignee] = useState(task.assigneePersonId ?? "");
  const [dueOn, setDueOn] = useState(task.dueOn ?? "");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [problem, setProblem] = useState<DescribedError | null>(null);

  if (archived) {
    return (
      <Card title="Edit">
        <p className={styles.muted}>An archived task is read-only. Restore it to make changes.</p>
      </Card>
    );
  }

  const current = members.filter((member) => member.removedAt == null);
  // An assignee who has since left the project stays selectable as themselves,
  // so opening the form does not silently unassign them.
  const assigneeMissing =
    task.assigneePersonId != null &&
    !current.some((member) => member.personId === task.assigneePersonId);

  const submit = (event: SyntheticEvent<HTMLFormElement>): void => {
    event.preventDefault();
    setSaved(false);
    setProblem(null);

    // Only what changed goes on the wire: the API reads an omitted field as
    // "leave it alone" and an explicit null assignee as "unassign".
    const body: TaskUpdateBody = {};
    if (title !== task.title) body.title = title;
    if (description !== task.description) body.description = description;
    if (priority !== task.priority) body.priority = priority;
    if (dueOn !== (task.dueOn ?? "")) body.dueOn = dueOn === "" ? null : dueOn;
    if (assignee !== (task.assigneePersonId ?? "")) {
      body.assigneePersonId = assignee === "" ? null : assignee;
    }

    if (Object.keys(body).length === 0) {
      setSaved(true);
      return;
    }

    setSaving(true);
    client
      .updateTask(workspaceId, task.id, body)
      .then(() => {
        setSaved(true);
        onChanged();
      })
      .catch((error: unknown) => {
        setProblem(describeRefusal(error, "save this task"));
      })
      .finally(() => {
        setSaving(false);
      });
  };

  return (
    <Card title="Edit">
      <details className={styles.disclosure}>
        <summary className={styles.summary}>Edit this task</summary>

        <form className={styles.form} onSubmit={submit}>
          <Field
            label="Title"
            name="title"
            value={title}
            onChange={(event) => {
              setTitle(event.target.value);
            }}
          />

          <div className={styles.control}>
            <label className={styles.label} htmlFor="task-description">
              Description
            </label>
            <textarea
              className={styles.textarea}
              id="task-description"
              name="description"
              rows={4}
              value={description}
              onChange={(event) => {
                setDescription(event.target.value);
              }}
            />
          </div>

          <div className={styles.control}>
            <label className={styles.label} htmlFor="task-priority">
              Priority
            </label>
            <select
              className={styles.select}
              id="task-priority"
              value={priority}
              onChange={(event) => {
                setPriority(event.target.value);
              }}
            >
              {PRIORITY_CHOICES.map((choice) => (
                <option key={choice.value} value={choice.value}>
                  {choice.label}
                </option>
              ))}
              {!PRIORITY_CHOICES.some((choice) => choice.value === task.priority) && (
                <option value={task.priority}>{task.priority}</option>
              )}
            </select>
            <p className={styles.hint}>Priority describes the work, never the person doing it.</p>
          </div>

          <div className={styles.control}>
            <label className={styles.label} htmlFor="task-assignee">
              Assignee
            </label>
            <select
              className={styles.select}
              id="task-assignee"
              value={assignee}
              onChange={(event) => {
                setAssignee(event.target.value);
              }}
            >
              <option value="">Unassigned</option>
              {current.map((member) => (
                <option key={member.personId} value={member.personId}>
                  {member.displayName}
                </option>
              ))}
              {assigneeMissing && task.assigneePersonId != null && (
                <option value={task.assigneePersonId}>
                  {task.assigneeName ?? "Current assignee"}
                </option>
              )}
            </select>
          </div>

          <div className={styles.control}>
            <label className={styles.label} htmlFor="task-due">
              Due date
            </label>
            <input
              className={styles.select}
              id="task-due"
              name="dueOn"
              type="date"
              value={dueOn}
              onChange={(event) => {
                setDueOn(event.target.value);
              }}
            />
            <p className={styles.hint}>Leave empty for no due date.</p>
          </div>

          {problem !== null && <InlineProblem error={problem} />}
          {saved && problem === null && <StatusNote>Saved. This task has been updated.</StatusNote>}

          <div className={styles.actions}>
            <Button type="submit" variant="primary" loading={saving}>
              Save changes
            </Button>
          </div>
        </form>
      </details>
    </Card>
  );
}

/** Archive closes a task without deleting its history; restore reopens it.
 * Offered plainly — the API decides who may, and a refusal says so here. */
function ArchiveControl({
  workspaceId,
  task,
  onChanged,
}: {
  workspaceId: string;
  task: TaskDetail;
  onChanged: () => void;
}): ReactNode {
  const client = useApiClient();
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<DescribedError | null>(null);

  const archived = task.archivedAt != null;

  const act = (): void => {
    setBusy(true);
    setProblem(null);
    const call = archived
      ? client.restoreTask(workspaceId, task.id)
      : client.archiveTask(workspaceId, task.id);
    call
      .then(() => {
        onChanged();
      })
      .catch((error: unknown) => {
        setProblem(describeRefusal(error, archived ? "restore this task" : "archive this task"));
      })
      .finally(() => {
        setBusy(false);
      });
  };

  return (
    <div className={styles.archiveControl}>
      <Button size="sm" onClick={act} loading={busy}>
        {archived ? "Restore" : "Archive"}
      </Button>
      {problem !== null && <InlineProblem error={problem} />}
    </div>
  );
}

/** Everything that has happened to this task, in order, in the server's own
 * sentences. A list, never a feed: no grouping, no totals, nothing per person. */
function History({ task }: { task: TaskDetail }): ReactNode {
  const events = task.events ?? [];

  return (
    <Card title="History" description="Everything that has happened to this task, in order.">
      {events.length === 0 ? (
        <p className={styles.muted}>Nothing has happened to this task yet.</p>
      ) : (
        <ol className={styles.history}>
          {events.map((event, index) => (
            <li className={styles.entry} key={`${event.at}-${String(index)}`}>
              <span className={styles.sentence}>{event.sentence}</span>
              <time className={styles.when} dateTime={event.at}>
                {formatWhen(event.at)}
              </time>
            </li>
          ))}
        </ol>
      )}
    </Card>
  );
}

/** A date-only value, as a readable day. "" for one that will not parse —
 * a broken date is not a fact worth printing. */
function formatDay(iso: string): string {
  const day = new Date(`${iso}T00:00:00`);
  if (Number.isNaN(day.getTime())) return "";
  return day.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

/** A timestamp, as a readable moment. Absolute rather than relative: this is
 * an audit trail, and "3d ago" drifts while a record should not. */
function formatWhen(iso: string): string {
  const then = new Date(iso);
  if (Number.isNaN(then.getTime())) return "";
  return then.toLocaleString(undefined, {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}
