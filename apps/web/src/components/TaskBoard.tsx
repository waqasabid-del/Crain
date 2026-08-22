"use client";

import type { TaskCreateBody, TaskSummary } from "@cairn/api-client";
import { Button } from "@cairn/ui";
import { useCallback, useId, useState, type ReactNode, type SyntheticEvent } from "react";

import { useApiClient } from "../api/context.js";
import { useAuth } from "../auth/context.js";
import { describeError, type DescribedError } from "../errors.js";
import { useAsync } from "../hooks/useAsync.js";
import { Card } from "./Card.js";
import { Field } from "./Field.js";
import { InlineProblem } from "./InlineProblem.js";
import { QuickAddTask, type QuickAddTarget } from "./QuickAddTask.js";
import { ErrorState, LoadingState } from "./States.js";
import { StatusNote } from "./StatusNote.js";
import { TaskCard } from "./TaskCard.js";
import styles from "./TaskBoard.module.css";

/** Somebody a task can be handed to: a current member of the project. */
export interface AssignableMember {
  personId: string;
  displayName: string;
}

/**
 * The five workflow columns, in workflow order and nothing else.
 *
 * The header is the plain state name — **never a count**. "To do (12)" is a
 * backlog figure, and the moment a column carries a number the board reads as
 * a progress meter over the people working it.
 */
const COLUMNS: readonly { state: string; label: string; creatable: boolean }[] = [
  { state: "todo", label: "To do", creatable: true },
  { state: "in_progress", label: "In progress", creatable: true },
  { state: "in_review", label: "In review", creatable: true },
  // No quick composer: a task is blocked by something that happened to it, so
  // the API refuses a task opened straight into blocked. Offering the control
  // here would be offering a request that comes back 422 every time.
  { state: "blocked", label: "Blocked", creatable: false },
  { state: "done", label: "Done", creatable: true },
];

/** The four priorities the form offers, led by the default. */
const PRIORITY_CHOICES: readonly { value: string; label: string }[] = [
  { value: "low", label: "Low" },
  { value: "normal", label: "Normal" },
  { value: "high", label: "High" },
  { value: "urgent", label: "Urgent" },
];

/**
 * A project's task board: five columns in workflow order, ordered within each
 * column by creation time — which measures nothing about anyone.
 *
 * Owns its own read, deliberately: a failed task read is an `ErrorState`
 * inside this card with its own retry, and the hero, Team and Work sections
 * around it render untouched. Archived tasks are excluded by the API's
 * default and this board asks for nothing more.
 */
export function TaskBoard({
  workspaceId,
  projectId,
  members,
}: {
  workspaceId: string;
  projectId: string;
  /** The project's current members, for the assignee choice. */
  members: AssignableMember[];
}): ReactNode {
  const client = useApiClient();
  const { activeRole } = useAuth();

  const load = useCallback(
    (signal: AbortSignal) => client.listTasks(workspaceId, projectId, undefined, { signal }),
    [client, workspaceId, projectId],
  );
  const { state, reload } = useAsync(load, "load the tasks on this project");
  /*
   * Which column's quick composer stands open — one across the board, or null.
   * Held here rather than in the board below because a create re-reads the
   * tasks, and the board is unmounted while that read is in flight: a composer
   * that owned its own open flag would close itself every time it succeeded.
   */
  const [openColumn, setOpenColumn] = useState<string | null>(null);

  // Decides what to *offer*, never what to allow: the API holds the permission
  // and refuses a request this screen was wrong to show. Viewers read the
  // board; they are not offered a control that would be refused.
  const canCreate = activeRole === "owner" || activeRole === "admin" || activeRole === "member";

  return (
    <Card title="Tasks" description="Work this project has decided to do.">
      {canCreate && (
        <NewTask
          workspaceId={workspaceId}
          projectId={projectId}
          members={members}
          onCreated={reload}
        />
      )}

      {state.status === "loading" && (
        <LoadingState label="the tasks on this project" shape="rows" lines={3} />
      )}

      {state.status === "failed" && (
        <ErrorState
          title="The tasks could not be loaded"
          error={state.error}
          onRetry={reload}
          headingLevel={3}
        />
      )}

      {state.status === "ready" && (
        <Board
          tasks={state.data.tasks ?? []}
          workspaceId={workspaceId}
          projectId={projectId}
          members={members}
          canCreate={canCreate}
          openColumn={openColumn}
          onOpenColumn={setOpenColumn}
          onCreated={reload}
        />
      )}
    </Card>
  );
}

function Board({
  tasks,
  workspaceId,
  projectId,
  members,
  canCreate,
  openColumn,
  onOpenColumn,
  onCreated,
}: {
  tasks: TaskSummary[];
  workspaceId: string;
  projectId: string;
  members: AssignableMember[];
  canCreate: boolean;
  openColumn: string | null;
  onOpenColumn: (state: string | null) => void;
  onCreated: () => void;
}): ReactNode {
  if (tasks.length === 0) {
    // One line, not a panel: an empty board is a legitimate answer, and the
    // create control above stays for those who can use it.
    return <p className={styles.empty}>No tasks yet.</p>;
  }

  // The board is one project's, so its composers already know where they
  // create: no project control, and this project's members throughout.
  const target: QuickAddTarget = { kind: "fixed", projectId, members };

  return (
    <div className={styles.board}>
      {COLUMNS.map((column) => (
        <Column
          key={column.state}
          label={column.label}
          tasks={tasks.filter((task) => task.state === column.state)}
          workspaceId={workspaceId}
          target={target}
          canAdd={canCreate && column.creatable}
          createState={column.state}
          composerOpen={openColumn === column.state}
          onOpenComposer={() => {
            onOpenColumn(column.state);
          }}
          onCloseComposer={() => {
            onOpenColumn(null);
          }}
          onCreated={onCreated}
        />
      ))}
    </div>
  );
}

function Column({
  label,
  tasks,
  workspaceId,
  target,
  canAdd,
  createState,
  composerOpen,
  onOpenComposer,
  onCloseComposer,
  onCreated,
}: {
  label: string;
  tasks: TaskSummary[];
  workspaceId: string;
  target: QuickAddTarget;
  /** Whether this reader is offered the quick composer in this column. */
  canAdd: boolean;
  createState: string;
  composerOpen: boolean;
  onOpenComposer: () => void;
  onCloseComposer: () => void;
  onCreated: () => void;
}): ReactNode {
  const headingId = useId();

  return (
    // A named region per column, so "To do" is a place a screen reader can
    // land rather than a heading floating over an unlabelled list.
    <section className={styles.column} aria-labelledby={headingId}>
      <h3 className={styles.columnTitle} id={headingId}>
        {label}
      </h3>
      {tasks.length === 0 ? (
        <p className={styles.columnEmpty}>None</p>
      ) : (
        <ul className={styles.columnList}>
          {tasks.map((task) => (
            <li key={task.id}>
              <TaskCard task={task} />
            </li>
          ))}
        </ul>
      )}

      {/* At the foot, under the work: you add where you are looking. Viewers
        are offered nothing here — the same gating as the panel above. */}
      {canAdd && (
        <QuickAddTask
          workspaceId={workspaceId}
          columnLabel={label}
          state={createState}
          target={target}
          canAssign
          open={composerOpen}
          onOpen={onOpenComposer}
          onClose={onCloseComposer}
          onCreated={onCreated}
        />
      )}
    </section>
  );
}

/**
 * Create a task — a disclosure in the Tasks section, following the portfolio's
 * NewProject panel: two to five fields do not justify a dialog, a focus trap
 * and an inert background, and the board behind this panel is the context the
 * creator is working from.
 */
function NewTask({
  workspaceId,
  projectId,
  members,
  onCreated,
}: {
  workspaceId: string;
  projectId: string;
  members: AssignableMember[];
  onCreated: () => void;
}): ReactNode {
  const client = useApiClient();
  const panelId = useId();
  const priorityId = useId();
  const assigneeId = useId();
  const descriptionId = useId();
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [priority, setPriority] = useState("normal");
  const [assignee, setAssignee] = useState("");
  const [dueOn, setDueOn] = useState("");
  const [saving, setSaving] = useState(false);
  const [problem, setProblem] = useState<DescribedError | null>(null);
  const [created, setCreated] = useState<string | null>(null);

  function reset(): void {
    setTitle("");
    setDescription("");
    setPriority("normal");
    setAssignee("");
    setDueOn("");
  }

  const submit = (event: SyntheticEvent<HTMLFormElement>): void => {
    event.preventDefault();
    setProblem(null);
    setCreated(null);
    setSaving(true);

    const madeTitle = title;
    const body: TaskCreateBody = {
      title,
      description: description.trim(),
      priority,
      // This form creates ordinary work, so it opens in the first column. The
      // columns' own "+ Add task" composers are what create straight into a
      // later state; this panel exists for the fields they deliberately omit —
      // description and due date.
      state: "todo",
      // Spread rather than sending an empty string: an unassigned task has no
      // assignee, not an assignee called "".
      ...(assignee === "" ? {} : { assigneePersonId: assignee }),
      ...(dueOn === "" ? {} : { dueOn }),
    };

    client
      .createTask(workspaceId, projectId, body)
      .then(() => {
        setCreated(madeTitle);
        reset();
        setOpen(false);
        // Re-read rather than patch the copy on screen: the server owns the
        // board's order and the task's stamped fields.
        onCreated();
      })
      .catch((error: unknown) => {
        // The typed values are deliberately left alone: a refusal is something
        // to adjust, not a reason to retype five fields.
        setProblem(describeError(error, "create this task"));
      })
      .finally(() => {
        setSaving(false);
      });
  };

  return (
    <div className={styles.create}>
      <div className={styles.createHead}>
        <p className={styles.createNote}>Title is the only requirement.</p>
        <Button
          type="button"
          variant={open ? "secondary" : "primary"}
          aria-expanded={open}
          aria-controls={panelId}
          onClick={() => {
            setCreated(null);
            setOpen(!open);
          }}
        >
          {open ? "Cancel" : "New task"}
        </Button>
      </div>

      {open && (
        <form className={styles.createForm} id={panelId} onSubmit={submit}>
          <Field
            label="Title"
            required
            maxLength={200}
            value={title}
            onChange={(event) => {
              setTitle(event.target.value);
            }}
          />

          <div className={styles.control}>
            <label className={styles.label} htmlFor={descriptionId}>
              Description
            </label>
            <textarea
              className={styles.textarea}
              id={descriptionId}
              rows={3}
              maxLength={2000}
              value={description}
              onChange={(event) => {
                setDescription(event.target.value);
              }}
            />
            <p className={styles.hint}>What done looks like, in a sentence or two. Optional.</p>
          </div>

          <div className={styles.control}>
            <label className={styles.label} htmlFor={priorityId}>
              Priority
            </label>
            <select
              className={styles.select}
              id={priorityId}
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
            </select>
          </div>

          <div className={styles.control}>
            <label className={styles.label} htmlFor={assigneeId}>
              Assignee
            </label>
            <select
              className={styles.select}
              id={assigneeId}
              value={assignee}
              onChange={(event) => {
                setAssignee(event.target.value);
              }}
            >
              {/* The honest default: a task nobody holds yet is a true
                statement, not a gap the form should fill in. */}
              <option value="">Nobody yet</option>
              {members.map((member) => (
                <option key={member.personId} value={member.personId}>
                  {member.displayName}
                </option>
              ))}
            </select>
          </div>

          <Field
            label="Due date"
            type="date"
            hint="Optional."
            value={dueOn}
            onChange={(event) => {
              setDueOn(event.target.value);
            }}
          />

          <Button type="submit" variant="primary" loading={saving}>
            Create task
          </Button>
          {problem !== null && <InlineProblem error={problem} />}
        </form>
      )}

      {created !== null && <StatusNote>{`${created} was created.`}</StatusNote>}
    </div>
  );
}
